"""FileHasher — read-only streaming SHA-256 computation for a DiscoveredFile.

Path-based, not handle-based — same documented limitation as the scanner
(see file_agent.scanner.scanner module docstring): the gap between the
pre-open reference check and open() cannot be prevented, only detected
after the fact via file identity (st_dev/st_ino) comparison. In-place
content modification during the read is detected, never prevented (no
exclusive lock is taken, so hashing stays a passive, non-disruptive reader).
"""

import hashlib
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from file_agent.domain import DiscoveredFile, DomainEvent, EntityType, EventType
from file_agent.hasher._paths import has_reparse_attribute, resolve_for_containment
from file_agent.hasher.issues import HashIssue, HashIssueSeverity, HashIssueType
from file_agent.hasher.result import HashFailure, HashOutcome, HashSuccess
from file_agent.scanner import SandboxRoot


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class _IdentitySnapshot:
    """(st_dev, st_ino, st_size, st_mtime, st_ctime) at one point in time."""

    st_dev: int
    st_ino: int
    st_size: int
    st_mtime: float
    st_ctime: float

    @classmethod
    def from_stat(cls, st: os.stat_result) -> "_IdentitySnapshot":
        return cls(
            st_dev=st.st_dev,
            st_ino=st.st_ino,
            st_size=st.st_size,
            st_mtime=st.st_mtime,
            st_ctime=st.st_ctime,
        )


class FileHasher:
    """Computes a trusted SHA-256 for a DiscoveredFile, or rejects it as untrusted.

    Requires a SandboxRoot and independently re-validates containment for
    every call — this, not any provenance field on DiscoveredFile, is what
    enforces "never hash a path outside the scanner's safety boundary."
    """

    def __init__(
        self, sandbox_root: SandboxRoot, *, clock: Callable[[], datetime] = _utc_now
    ) -> None:
        self._sandbox_root = sandbox_root
        self._clock = clock

    def hash_file(self, discovered: DiscoveredFile) -> HashOutcome:
        """Hash one DiscoveredFile. Never raises — every problem becomes a HashFailure."""
        try:
            return self._hash_file(discovered)
        except Exception as exc:  # noqa: BLE001 -- defensive: hash_file() must never raise
            return self._fail(
                discovered,
                HashIssueType.INTERNAL_ERROR,
                HashIssueSeverity.CRITICAL,
                str(exc),
            )

    def _hash_file(self, discovered: DiscoveredFile) -> HashOutcome:
        # Step 1: containment (must pass before anything else is inspected).
        resolved = resolve_for_containment(discovered.path)
        if resolved is None:
            return self._fail(
                discovered,
                HashIssueType.UNRESOLVABLE_PATH,
                HashIssueSeverity.WARNING,
                "path could not be resolved",
            )
        if not resolved.is_relative_to(self._sandbox_root.path):
            return self._fail(
                discovered,
                HashIssueType.PATH_OUTSIDE_SANDBOX,
                HashIssueSeverity.CRITICAL,
                f"path resolves outside sandbox: {resolved}",
            )

        # Step 2: reference check (never follow a symlink/junction/reparse point).
        if discovered.path.is_symlink():
            return self._fail(
                discovered,
                HashIssueType.REPARSE_POINT_ENCOUNTERED,
                HashIssueSeverity.WARNING,
                "path is a symlink; not followed",
            )
        if os.path.isjunction(discovered.path):
            return self._fail(
                discovered,
                HashIssueType.REPARSE_POINT_ENCOUNTERED,
                HashIssueSeverity.WARNING,
                "path is a junction; not followed",
            )

        # Content is never opened until steps 1 and 2 have both passed.
        try:
            pre_open_stat = os.stat(discovered.path, follow_symlinks=False)
        except FileNotFoundError as exc:
            return self._fail(
                discovered, HashIssueType.NOT_FOUND, HashIssueSeverity.WARNING, str(exc)
            )
        except PermissionError as exc:
            return self._fail(
                discovered,
                HashIssueType.PERMISSION_DENIED,
                HashIssueSeverity.WARNING,
                str(exc),
            )
        except OSError as exc:
            return self._fail(
                discovered,
                HashIssueType.READ_FAILED,
                HashIssueSeverity.WARNING,
                str(exc),
            )

        if has_reparse_attribute(pre_open_stat):
            return self._fail(
                discovered,
                HashIssueType.REPARSE_POINT_ENCOUNTERED,
                HashIssueSeverity.WARNING,
                "path is an unclassified reparse point; not followed",
            )
        if not stat.S_ISREG(pre_open_stat.st_mode):
            return self._fail(
                discovered,
                HashIssueType.UNSUPPORTED_ENTRY_TYPE,
                HashIssueSeverity.WARNING,
                "not a regular file",
            )

        # Check A: Checkpoint 1 (pre-open path stat) vs the FA-002 observation.
        observed_modified_at = datetime.fromtimestamp(pre_open_stat.st_mtime, tz=UTC)
        observed_created_at = datetime.fromtimestamp(pre_open_stat.st_ctime, tz=UTC)
        if (
            pre_open_stat.st_size != discovered.size_bytes
            or observed_modified_at != discovered.modified_at
            or observed_created_at != discovered.created_at
        ):
            return self._fail(
                discovered,
                HashIssueType.METADATA_MISMATCH_BEFORE_HASH,
                HashIssueSeverity.WARNING,
                "current file metadata does not match the discovered observation",
            )

        checkpoint1 = _IdentitySnapshot.from_stat(pre_open_stat)

        try:
            handle = open(discovered.path, "rb")  # noqa: SIM115 -- closed explicitly below via `with`
        except FileNotFoundError as exc:
            return self._fail(
                discovered, HashIssueType.NOT_FOUND, HashIssueSeverity.WARNING, str(exc)
            )
        except PermissionError as exc:
            return self._fail(
                discovered,
                HashIssueType.PERMISSION_DENIED,
                HashIssueSeverity.WARNING,
                str(exc),
            )
        except OSError as exc:
            return self._fail(
                discovered,
                HashIssueType.READ_FAILED,
                HashIssueSeverity.WARNING,
                str(exc),
            )

        with handle:
            # Checkpoint 2: opened-handle stat.
            checkpoint2 = _IdentitySnapshot.from_stat(os.fstat(handle.fileno()))

            # Check B: Checkpoint 1 vs Checkpoint 2 — did open() resolve to a
            # different file than what the pre-open path check inspected?
            if (checkpoint2.st_dev, checkpoint2.st_ino) != (
                checkpoint1.st_dev,
                checkpoint1.st_ino,
            ):
                return self._fail(
                    discovered,
                    HashIssueType.IDENTITY_MISMATCH_ON_OPEN,
                    HashIssueSeverity.WARNING,
                    "opened file identity differs from the pre-open path check",
                )

            try:
                digest = hashlib.file_digest(handle, "sha256")
            except OSError as exc:
                return self._fail(
                    discovered,
                    HashIssueType.READ_FAILED,
                    HashIssueSeverity.WARNING,
                    str(exc),
                )

            bytes_read = (
                handle.tell()
            )  # auxiliary signal only — see module docs / plan §3

            # Checkpoint 3: post-read handle stat (same handle throughout).
            checkpoint3 = _IdentitySnapshot.from_stat(os.fstat(handle.fileno()))

        # Check C: Checkpoint 2 vs Checkpoint 3 — did anything change while reading?
        if checkpoint3 != checkpoint2:
            return self._fail(
                discovered,
                HashIssueType.MODIFIED_DURING_HASH,
                HashIssueSeverity.WARNING,
                f"file identity/metadata changed during read (bytes_read={bytes_read})",
            )

        hex_digest = digest.hexdigest()
        hashed = discovered.with_sha256(hex_digest)
        event = DomainEvent(
            event_type=EventType.FILE_HASHED,
            entity_type=EntityType.FILE,
            entity_id=hashed.id,
            timestamp=self._clock(),
            payload={"sha256": hex_digest, "path": str(discovered.path)},
        )
        return HashSuccess(original=discovered, hashed=hashed, event=event)

    def _fail(
        self,
        discovered: DiscoveredFile,
        issue_type: HashIssueType,
        severity: HashIssueSeverity,
        message: str,
    ) -> HashFailure:
        return HashFailure(
            original=discovered,
            issue=self._issue(discovered.path, issue_type, severity, message),
        )

    def _issue(
        self,
        path: Path,
        issue_type: HashIssueType,
        severity: HashIssueSeverity,
        message: str,
    ) -> HashIssue:
        return HashIssue(
            path=str(path),
            issue_type=issue_type,
            severity=severity,
            message=message,
            detected_at=self._clock(),
        )


def hash_discovered_file(
    discovered: DiscoveredFile, sandbox_root: SandboxRoot
) -> HashOutcome:
    """Convenience entry point: ``FileHasher(sandbox_root).hash_file(discovered)``."""
    return FileHasher(sandbox_root).hash_file(discovered)
