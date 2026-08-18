"""DirectoryScanner — read-only recursive discovery of files inside a SandboxRoot.

Path-based, not handle-based: this safely detects and blocks every
symlink/junction/reparse-point escape observed at classification time, but
does not provide a race-free guarantee against a filesystem entry being
concurrently swapped between classification and read. Closing that fully
would require Win32 handle-based traversal, which is explicitly out of scope
here — see the FA-002 design plan's "Threat model and limitations" section.
This is an accepted limitation: the scanner only ever reads metadata, never
file content.
"""

import os
import stat
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from file_agent.domain import (
    DiscoveredFile,
    DomainEvent,
    EntityType,
    EventType,
    ScanRun,
    ScanStatus,
)
from file_agent.reserved_artifacts import is_file_agent_internal_artifact
from file_agent.scanner._paths import file_times_from_stat, resolve_reference_target
from file_agent.scanner.issues import ScanIssue, ScanIssueSeverity, ScanIssueType
from file_agent.scanner.result import ScanResult
from file_agent.scanner.sandbox_root import SandboxRoot
from file_agent.structural_safety import (
    StructuralProtection,
    classify_directory,
    is_hard_excluded_directory_name,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DirectoryScanner:
    """Recursively discovers files inside a SandboxRoot without modifying the filesystem."""

    def __init__(
        self,
        sandbox_root: SandboxRoot,
        managed_root_id: UUID,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._sandbox_root = sandbox_root
        self._managed_root_id = managed_root_id
        self._clock = clock
        self._scan_id: UUID | None = None

    def run(self) -> ScanResult:
        """Run one scan to completion. Never raises — problems become issues or FAILED status."""
        scan_run = ScanRun(root_path=self._sandbox_root.path, started_at=self._clock())
        scan_run = scan_run.evolve(status=ScanStatus.RUNNING)
        self._scan_id = scan_run.id
        root_path = self._sandbox_root.path

        files: list[DiscoveredFile] = []
        events: list[DomainEvent] = []
        issues: list[ScanIssue] = []
        protected_trees: list[StructuralProtection] = []
        aborted = False

        # FA-016: checked FIRST, zero I/O, before even attempting to list the
        # root's contents -- if the Managed Root's own basename is
        # hard-excluded, the ENTIRE root is structurally protected,
        # unconditionally. Managed Root authority (FA-015) never exempts
        # root_path from this layer. Silent, consistent with hard-exclusion's
        # established treatment at every other depth -- no protected_trees
        # entry, no event, matching how a node_modules/ found deeper in the
        # tree is also never individually reported.
        if is_hard_excluded_directory_name(root_path.name):
            scan_run = scan_run.evolve(
                status=ScanStatus.COMPLETED,
                completed_at=self._clock(),
                files_discovered=0,
            )
            return ScanResult(
                scan_run=scan_run, files=(), events=(), issues=(), protected_trees=()
            )

        try:
            root_entries = list(os.scandir(root_path))
        except OSError as exc:
            aborted = True
            issues.append(
                self._issue(
                    root_path,
                    ScanIssueType.SCAN_ABORTED,
                    ScanIssueSeverity.CRITICAL,
                    f"sandbox root became inaccessible: {exc}",
                )
            )
            root_entries = []

        if not aborted:
            try:
                # FA-016: marker-based root protection -- the Managed Root's
                # own directory is classified exactly like any other
                # directory (reached only once hard-exclusion-by-name has
                # already been ruled out above).
                root_membership = classify_directory(root_path, root_entries)
                if root_membership is not None:
                    protected_trees.append(root_membership)
                    events.append(self._build_protected_tree_event(root_membership))
                else:
                    for entry in root_entries:
                        self._process_entry(
                            entry, files, events, issues, protected_trees
                        )
            except Exception as exc:  # noqa: BLE001 -- defensive: run() must never raise
                aborted = True
                issues.append(
                    self._issue(
                        root_path,
                        ScanIssueType.SCAN_ABORTED,
                        ScanIssueSeverity.CRITICAL,
                        f"unexpected error during scan: {exc}",
                    )
                )

        final_status = ScanStatus.FAILED if aborted else ScanStatus.COMPLETED
        scan_run = scan_run.evolve(
            status=final_status, completed_at=self._clock(), files_discovered=len(files)
        )
        return ScanResult(
            scan_run=scan_run,
            files=tuple(files),
            events=tuple(events),
            issues=tuple(issues),
            protected_trees=tuple(protected_trees),
        )

    def _walk_subdirectory(
        self,
        directory: Path,
        files: list[DiscoveredFile],
        events: list[DomainEvent],
        issues: list[ScanIssue],
        protected_trees: list[StructuralProtection],
    ) -> None:
        try:
            entries = list(os.scandir(directory))
        except PermissionError as exc:
            issues.append(
                self._issue(
                    directory,
                    ScanIssueType.PERMISSION_DENIED,
                    ScanIssueSeverity.WARNING,
                    str(exc),
                )
            )
            return
        except OSError as exc:
            issues.append(
                self._issue(
                    directory,
                    ScanIssueType.STAT_FAILED,
                    ScanIssueSeverity.WARNING,
                    str(exc),
                )
            )
            return
        # FA-016: marker-based classification, reusing the already-
        # materialized `entries` list -- zero extra I/O. A match prunes this
        # entire subtree (marker's own directory inclusive) wholesale; none
        # of `entries` is processed further.
        membership = classify_directory(directory, entries)
        if membership is not None:
            protected_trees.append(membership)
            events.append(self._build_protected_tree_event(membership))
            return
        for entry in entries:
            self._process_entry(entry, files, events, issues, protected_trees)

    def _process_entry(
        self,
        entry: "os.DirEntry[str]",
        files: list[DiscoveredFile],
        events: list[DomainEvent],
        issues: list[ScanIssue],
        protected_trees: list[StructuralProtection],
    ) -> None:
        # FileAgent-owned internal artifacts (e.g. RecoveryEngine's reserved
        # restore-temp namespace) are invisible to organization scanning --
        # checked first, using only the already-available entry.name, before
        # any stat/symlink/junction/content I/O. Not user content, so no
        # DiscoveredFile, no FILE_DISCOVERED event, no ScanIssue either --
        # it is fully skipped, not modeled as UNKNOWN/OTHER/REVIEW/BLOCK.
        if is_file_agent_internal_artifact(entry.name):
            return
        # FA-016: hard-exclusion-by-name, checked next -- zero I/O, before
        # symlink/junction detection so an excluded directory that happens
        # to be a reference doesn't generate a spurious NOT_FOLLOWED issue
        # for something already being silently excluded by name. Directories
        # only (is_dir(follow_symlinks=False) is False for a symlink/
        # junction entry, so those fall through unchanged to the existing
        # reference handling below).
        if entry.is_dir(follow_symlinks=False) and is_hard_excluded_directory_name(
            entry.name
        ):
            return
        entry_path = Path(entry.path)
        try:
            if entry.is_symlink():
                self._handle_reference(entry_path, is_junction=False, issues=issues)
                return
            if entry.is_junction():
                self._handle_reference(entry_path, is_junction=True, issues=issues)
                return
            st = self._stat_entry(entry)
            if st.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                issues.append(
                    self._issue(
                        entry_path,
                        ScanIssueType.UNSUPPORTED_REPARSE_POINT,
                        ScanIssueSeverity.WARNING,
                        "unclassified reparse point; not followed",
                    )
                )
                return
            if stat.S_ISDIR(st.st_mode):
                self._walk_subdirectory(
                    entry_path, files, events, issues, protected_trees
                )
            elif stat.S_ISREG(st.st_mode):
                discovered = self._build_discovered_file(entry_path, st)
                files.append(discovered)
                events.append(self._build_event(discovered))
            else:
                issues.append(
                    self._issue(
                        entry_path,
                        ScanIssueType.UNSUPPORTED_ENTRY_TYPE,
                        ScanIssueSeverity.WARNING,
                        "not a regular file or directory",
                    )
                )
        except FileNotFoundError as exc:
            issues.append(
                self._issue(
                    entry_path,
                    ScanIssueType.NOT_FOUND,
                    ScanIssueSeverity.WARNING,
                    str(exc),
                )
            )
        except PermissionError as exc:
            issues.append(
                self._issue(
                    entry_path,
                    ScanIssueType.PERMISSION_DENIED,
                    ScanIssueSeverity.WARNING,
                    str(exc),
                )
            )
        except OSError as exc:
            issues.append(
                self._issue(
                    entry_path,
                    ScanIssueType.STAT_FAILED,
                    ScanIssueSeverity.WARNING,
                    str(exc),
                )
            )

    def _stat_entry(self, entry: "os.DirEntry[str]") -> os.stat_result:
        return entry.stat(follow_symlinks=False)

    def _handle_reference(
        self, entry_path: Path, *, is_junction: bool, issues: list[ScanIssue]
    ) -> None:
        target = resolve_reference_target(entry_path)
        not_followed_type = (
            ScanIssueType.JUNCTION_NOT_FOLLOWED
            if is_junction
            else ScanIssueType.SYMLINK_NOT_FOLLOWED
        )
        if target is None:
            issues.append(
                self._issue(
                    entry_path,
                    ScanIssueType.UNRESOLVABLE_REFERENCE,
                    ScanIssueSeverity.WARNING,
                    "reference target could not be resolved",
                )
            )
            return
        if target.is_relative_to(self._sandbox_root.path):
            issues.append(
                self._issue(
                    entry_path,
                    not_followed_type,
                    ScanIssueSeverity.INFO,
                    "reference not followed",
                )
            )
        else:
            issues.append(
                self._issue(
                    entry_path,
                    ScanIssueType.SANDBOX_ESCAPE_ATTEMPT,
                    ScanIssueSeverity.CRITICAL,
                    f"reference target outside sandbox: {target}",
                )
            )

    def _build_discovered_file(self, path: Path, st: os.stat_result) -> DiscoveredFile:
        created_at, modified_at = file_times_from_stat(st)
        return DiscoveredFile(
            path=path,
            size_bytes=st.st_size,
            created_at=created_at,
            modified_at=modified_at,
            discovered_at=self._clock(),
            discovered_by_scan_id=self._scan_id,
            managed_root_id=self._managed_root_id,
        )

    def _build_event(self, discovered: DiscoveredFile) -> DomainEvent:
        return DomainEvent(
            event_type=EventType.FILE_DISCOVERED,
            entity_type=EntityType.FILE,
            entity_id=discovered.id,
            timestamp=self._clock(),
            payload={"scan_id": str(self._scan_id), "path": str(discovered.path)},
        )

    def _build_protected_tree_event(
        self, membership: StructuralProtection
    ) -> DomainEvent:
        """FA-016: one event per detected marker-based Protected Tree root --
        every membership reaching this call site is guaranteed
        kind=PROTECTED_TREE, since classify_directory (the only producer of
        protected_trees entries at scan time) never returns a HARD_EXCLUSION
        result. entity_type=SCAN, entity_id=scan_run.id, mirroring how
        FILE_DISCOVERED is keyed off this same scan."""
        assert membership.marker is not None and membership.marker_path is not None
        assert self._scan_id is not None
        return DomainEvent(
            event_type=EventType.PROTECTED_TREE_DETECTED,
            entity_type=EntityType.SCAN,
            entity_id=self._scan_id,
            timestamp=self._clock(),
            payload={
                "scan_id": str(self._scan_id),
                "root_path": str(membership.root_path),
                "marker": membership.marker.value,
                "marker_path": str(membership.marker_path),
            },
        )

    def _issue(
        self,
        path: Path,
        issue_type: ScanIssueType,
        severity: ScanIssueSeverity,
        message: str,
    ) -> ScanIssue:
        return ScanIssue(
            path=str(path),
            issue_type=issue_type,
            severity=severity,
            message=message,
            detected_at=self._clock(),
        )


def scan_sandbox(sandbox_root: SandboxRoot, managed_root_id: UUID) -> ScanResult:
    """Convenience entry point: ``DirectoryScanner(sandbox_root, managed_root_id).run()``."""
    return DirectoryScanner(sandbox_root, managed_root_id).run()
