"""FA-016 Protected Trees & Exclusions -- the structural-safety layer sitting
between Managed Root authority (FA-015) and classification.

MANAGED ROOT AUTHORITY DOES NOT IMPLY STRUCTURAL ELIGIBILITY. A folder can be
an authorized ManagedRoot and still contain (or itself BE) a software-project
structure FileAgent must leave intact. This package owns exactly two,
independent decisions:

- Hard exclusions: a directory whose bare NAME matches a fixed,
  ecosystem-specific list (node_modules, .venv, .git, ...) is never
  descended into/read, unconditionally -- including when it is the
  ManagedRoot's own directory.
- Protected Trees: a directory whose own immediate children include a
  strong project marker (.git, pyproject.toml, package.json, ...) becomes a
  protected root; every descendant, inclusive of the marker's own
  directory, is ineligible for ordinary organization -- including when the
  ManagedRoot's own directory is the one that qualifies.

Zero dependencies beyond the standard library (os, stat, pathlib, dataclasses,
enum, collections.abc) -- deliberately importable by both scanner/ (scan-time
pruning) and application/ (live re-verification) without creating any
directional dependency on either. Nothing here performs a filesystem
mutation; every function is read-only inspection.

=== The live re-check primitive: find_structural_protection ===

Registration/discovery-time validation only proves a path was safe ONCE.
Every later use must re-derive that proof fresh: an ancestor between an
already-persisted file and its ManagedRoot can be turned into a
symlink/junction after the file was discovered, and the file ITSELF can be
individually replaced by a reference object at its own path, independent of
its ancestors. find_structural_protection is the ONE primitive that closes
both gaps, called fresh on every use, never cached:

  1. Containment precondition: candidate_path must be a strict descendant of
     root_path, checked before any I/O.
  2. SOURCE mode only (inspect_candidate_reference=True): candidate_path
     itself is conclusively verified not to be a symlink/junction/reparse
     object before anything else. DESTINATION mode (=False) never inspects
     the leaf at all -- a prospective destination normally doesn't exist,
     and its absence must never be mistaken for a failure.
  3. Every ancestor from candidate_path.parent up to and including root_path:
     reference/reparse status is checked FIRST, fail-closed on any
     uncertainty -- nothing past an ancestor whose status could not be
     conclusively proven NORMAL is ever listed. Only then: unconditional
     hard-exclusion-by-name (root_path included), then marker-based
     protection via a fresh directory listing.

Residual TOCTOU, explicitly accepted, not closed by this design: the
reference-check-then-list sequence at each level is a fail-closed,
POINT-IN-TIME proof, not an atomic Windows-handle guarantee. A concurrent,
adversarial process with write access to the relevant directory tree could in
principle swap a component between the reference check and the subsequent
listing call, within a single find_structural_protection invocation. Closing
this fully would require Windows File ID/USN-journal tracking or directory
handles held open across the whole sequence -- explicitly out of scope here,
matching this codebase's other accepted TOCTOU windows (managed_roots.py's
own _resolve_safe_managed_root, vault_engine/safety.py,
transaction_engine's destination-side reparse checks).

See tests/application/test_structural_safety_ast_guardrail.py for the
structural guardrail enforcing that every application-layer live structural
decision goes through this one function -- never a hand-rolled equivalent.
"""

import os
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# --- Value types --------------------------------------------------------------


class ProjectMarkerType(str, Enum):
    GIT = "git"
    PACKAGE_JSON = "package_json"
    PYPROJECT_TOML = "pyproject_toml"
    CARGO_TOML = "cargo_toml"
    GO_MOD = "go_mod"
    POM_XML = "pom_xml"
    BUILD_GRADLE = "build_gradle"
    SETTINGS_GRADLE = "settings_gradle"
    DOTNET_SOLUTION = "dotnet_solution"
    """*.sln"""
    DOTNET_PROJECT = "dotnet_project"
    """*.csproj"""
    CMAKE_LISTS = "cmake_lists"
    """CMakeLists.txt"""
    COMPOSER_JSON = "composer_json"
    GEMFILE = "gemfile"


class StructuralProtectionKind(str, Enum):
    PROTECTED_TREE = "protected_tree"
    """Marker-based: `root_path` contains a strong project marker among its
    own immediate children."""
    HARD_EXCLUSION = "hard_exclusion"
    """Name-based: `root_path`'s own bare name matches a fixed,
    ecosystem-specific exclusion list, unconditionally -- ManagedRoot
    authority never exempts it."""


@dataclass(frozen=True, slots=True)
class StructuralProtection:
    """The unified result: one shape, discriminated by `kind`, so every
    caller needs exactly one isinstance check to know "reject this," while
    still carrying enough detail for audit purposes."""

    kind: StructuralProtectionKind
    root_path: Path
    marker: ProjectMarkerType | None
    """Populated iff kind is PROTECTED_TREE."""
    marker_path: Path | None
    """Populated iff kind is PROTECTED_TREE."""
    excluded_name: str | None
    """Populated iff kind is HARD_EXCLUSION."""


@dataclass(frozen=True, slots=True)
class StructuralInspectionFailure:
    """Fail-closed: covers containment-precondition failure, a reparse
    point (or inconclusive reference-status check) anywhere in the chain
    (candidate or ancestor), and any OSError listing an ancestor. Every
    caller treats this identically to a confirmed StructuralProtection --
    never distinguished at the public API boundary. `detail` is free-form,
    English/technical, audit-only text -- never rendered verbatim in
    Spanish (matches ManagedRootPathFailure.detail's own precedent)."""

    path: Path
    detail: str


# --- Hard exclusions -----------------------------------------------------------

_HARD_EXCLUDED_DIRECTORY_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "vendor",
        "target",
        ".gradle",
        ".idea",
        ".vscode",
        "dist",
        "build",
    }
)


def is_hard_excluded_directory_name(name: str) -> bool:
    """Case-insensitive (casefold) match against a fixed, ecosystem-specific
    directory-name list. A pure string comparison -- zero I/O, zero
    filesystem access -- deliberately cheap so it can always be checked
    before any directory listing."""
    return name.casefold() in _HARD_EXCLUDED_DIRECTORY_NAMES


# --- Project markers -------------------------------------------------------


class _MarkerMatchKind(Enum):
    GIT_DIR = "git_dir"
    EXACT_FILE = "exact_file"
    SUFFIX_FILE = "suffix_file"


_MARKER_DEFINITIONS: tuple[tuple[ProjectMarkerType, _MarkerMatchKind, str], ...] = (
    (ProjectMarkerType.GIT, _MarkerMatchKind.GIT_DIR, ".git"),
    (ProjectMarkerType.PACKAGE_JSON, _MarkerMatchKind.EXACT_FILE, "package.json"),
    (ProjectMarkerType.PYPROJECT_TOML, _MarkerMatchKind.EXACT_FILE, "pyproject.toml"),
    (ProjectMarkerType.CARGO_TOML, _MarkerMatchKind.EXACT_FILE, "cargo.toml"),
    (ProjectMarkerType.GO_MOD, _MarkerMatchKind.EXACT_FILE, "go.mod"),
    (ProjectMarkerType.POM_XML, _MarkerMatchKind.EXACT_FILE, "pom.xml"),
    (ProjectMarkerType.BUILD_GRADLE, _MarkerMatchKind.EXACT_FILE, "build.gradle"),
    (ProjectMarkerType.SETTINGS_GRADLE, _MarkerMatchKind.EXACT_FILE, "settings.gradle"),
    (ProjectMarkerType.DOTNET_SOLUTION, _MarkerMatchKind.SUFFIX_FILE, ".sln"),
    (ProjectMarkerType.DOTNET_PROJECT, _MarkerMatchKind.SUFFIX_FILE, ".csproj"),
    (ProjectMarkerType.CMAKE_LISTS, _MarkerMatchKind.EXACT_FILE, "cmakelists.txt"),
    (ProjectMarkerType.COMPOSER_JSON, _MarkerMatchKind.EXACT_FILE, "composer.json"),
    (ProjectMarkerType.GEMFILE, _MarkerMatchKind.EXACT_FILE, "gemfile"),
)
"""Fixed marker-priority order (the ticket's own listed order) -- determines
only which marker gets REPORTED when a directory happens to satisfy more
than one (e.g. both .git and pyproject.toml); the exclusion decision itself
is identical either way."""


def classify_directory(
    directory: Path, entries: Sequence["os.DirEntry[str]"]
) -> StructuralProtection | None:
    """Scan-time AND live-recheck use: marker check (kind is always
    PROTECTED_TREE when non-None) against `directory`'s own children,
    given as an already-obtained `entries` sequence -- zero extra I/O beyond
    whatever produced `entries`. Never checks `directory`'s own name for
    hard-exclusion or reference/reparse status; both are the caller's job
    (see scanner.py for scan-time, find_structural_protection for the live
    re-check). Every match uses follow_symlinks=False semantics via
    DirEntry.is_dir()/is_file(), so a symlinked entry never establishes
    protection -- it falls through unmodified to whatever reference handling
    the caller already applies elsewhere."""
    for marker, kind, pattern in _MARKER_DEFINITIONS:
        for entry in entries:
            name_cf = entry.name.casefold()
            if kind is _MarkerMatchKind.GIT_DIR:
                matched = name_cf == pattern and entry.is_dir(follow_symlinks=False)
            elif kind is _MarkerMatchKind.EXACT_FILE:
                matched = name_cf == pattern and entry.is_file(follow_symlinks=False)
            else:  # SUFFIX_FILE
                matched = name_cf.endswith(pattern) and entry.is_file(
                    follow_symlinks=False
                )
            if matched:
                return StructuralProtection(
                    StructuralProtectionKind.PROTECTED_TREE,
                    root_path=directory,
                    marker=marker,
                    marker_path=directory / entry.name,
                    excluded_name=None,
                )
    return None


# --- Reference/reparse-point inspection (fail-closed) -----------------------


@dataclass(frozen=True, slots=True)
class _StatIdentity:
    """(st_dev, st_ino, st_mtime) from one stat call -- bundled together
    (not three separate Optional fields) so a single `is None` check
    narrows all three at once for callers, since they are only ever
    known or unknown together."""

    st_dev: int
    st_ino: int
    mtime: float


@dataclass(frozen=True, slots=True)
class _ReferenceInspection:
    """Fail-closed reference/reparse inspection, enriched with the
    identity+mtime observed by the SAME stat call -- used by
    ScanStructuralContext (below) to detect ancestor replacement, rename,
    or content change (e.g. a marker file added/removed) without any
    extra syscalls beyond what this inspection already required for its
    own, unrelated, always-fresh reparse-point purpose. `stat_identity`
    is None exactly when the path does not currently exist, mirroring the
    FileNotFoundError -> conclusively-not-a-reparse-point precedent
    documented below."""

    is_reparse: bool
    stat_identity: _StatIdentity | None


def _inspect_reference_state(
    path: Path,
) -> "_ReferenceInspection | StructuralInspectionFailure":
    """Fail-closed reference inspection. NEVER silently coerces
    a genuine inspection failure into "not a reparse point": the ENTIRE
    sequence below -- not just the final os.stat fallback -- is wrapped in
    one try/except, so a failure from ANY of the three underlying stdlib
    calls produces an explicit StructuralInspectionFailure. A local,
    stdlib-only reimplementation -- deliberately NOT imported from
    scanner._paths.is_reparse_point, to keep structural_safety free of any
    dependency on scanner (see this module's own docstring) -- mirroring
    managed_roots.py's own already-established local copy of this exact
    logic, itself following this codebase's convention of duplicating small
    pure-path helpers per package (see recovery_engine/_paths.py's own
    docstring for the original precedent).

    FileNotFoundError is deliberately NOT an inspection failure: a path
    that does not exist at all is CONCLUSIVELY, not uncertainly, not a
    reparse point -- there is nothing there to redirect anywhere, and
    nothing an attacker could hide by deleting a directory (its contents
    would be gone too). Treating "missing" as NORMAL lets legitimate,
    already-handled business cases -- a not-yet-created destination
    category folder, a source file already moved away by an earlier apply
    -- fall through to whatever downstream check already owns that concern
    (inspect_destination's DESTINATION_PARENT_MISSING, FileHasher's own
    NOT_FOUND handling), rather than being misreported as a structural
    hijack. Every OTHER OSError (permission denied, or any exotic failure)
    remains a genuine, fail-closed StructuralInspectionFailure."""
    try:
        if path.is_symlink():
            return _ReferenceInspection(is_reparse=True, stat_identity=None)
        if os.path.isjunction(path):
            return _ReferenceInspection(is_reparse=True, stat_identity=None)
        st = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return _ReferenceInspection(is_reparse=False, stat_identity=None)
    except OSError as exc:
        return StructuralInspectionFailure(
            path, f"could not determine reference status: {exc}"
        )
    is_reparse = bool(st.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    return _ReferenceInspection(
        is_reparse=is_reparse,
        stat_identity=_StatIdentity(
            st_dev=st.st_dev, st_ino=st.st_ino, mtime=st.st_mtime
        ),
    )


# --- The shared, live-reinspecting primitive --------------------------------


def find_structural_protection(
    candidate_path: Path,
    root_path: Path,
    *,
    inspect_candidate_reference: bool,
) -> StructuralProtection | StructuralInspectionFailure | None:
    """THE one live structural-safety primitive -- see this module's own
    docstring for the full rationale. Never cached, never assumed from a
    prior scan/preview/analysis generation; re-derived fresh on every call.

    `inspect_candidate_reference` has NO default -- every call site must
    explicitly declare its shape:
      - True: `candidate_path` is an EXISTING SOURCE object. Verified
        itself, first, before its ancestors.
      - False: `candidate_path` is a PROSPECTIVE DESTINATION that normally
        does not exist yet. Never inspected itself; only its ancestor chain
        matters. An existing-but-unsafe destination leaf remains
        TransactionEngine's own, separate, unmodified responsibility.

    Returns None (eligible), a StructuralProtection, or a
    StructuralInspectionFailure -- the latter is indistinguishable from a
    confirmed StructuralProtection to every caller (fail closed).
    """
    if candidate_path == root_path or not candidate_path.is_relative_to(root_path):
        return StructuralInspectionFailure(
            candidate_path, "candidate_path is not a strict descendant of root_path"
        )

    if inspect_candidate_reference:
        leaf_inspection = _inspect_reference_state(candidate_path)
        if isinstance(leaf_inspection, StructuralInspectionFailure):
            return leaf_inspection
        if leaf_inspection.is_reparse:
            return StructuralInspectionFailure(
                candidate_path,
                "candidate itself is a symlink, junction, or reparse point",
            )

    ancestors = [p for p in candidate_path.parents if p.is_relative_to(root_path)]
    for ancestor in ancestors:
        reference_inspection = _inspect_reference_state(ancestor)
        if isinstance(reference_inspection, StructuralInspectionFailure):
            return reference_inspection
        if reference_inspection.is_reparse:
            return StructuralInspectionFailure(
                ancestor, "ancestor is a symlink, junction, or reparse point"
            )
        if is_hard_excluded_directory_name(ancestor.name):
            return StructuralProtection(
                StructuralProtectionKind.HARD_EXCLUSION,
                root_path=ancestor,
                marker=None,
                marker_path=None,
                excluded_name=ancestor.name,
            )
        try:
            entries = list(os.scandir(ancestor))
        except FileNotFoundError:
            # This ancestor does not exist (yet) -- conclusively, not
            # uncertainly, nothing here to protect (a missing directory has
            # no contents to hide a marker inside, and no attacker gains
            # anything by deleting one -- its contents are gone too).
            # Legitimate, already-handled business cases (a not-yet-created
            # destination category folder) must fall through to whatever
            # downstream check owns that concern, never be misreported as
            # a structural hijack. Continue checking the remaining
            # ancestors above it.
            continue
        except OSError as exc:
            return StructuralInspectionFailure(ancestor, str(exc))
        membership = classify_directory(ancestor, entries)
        if membership is not None:
            return membership

    return None


# --- Scan-scoped ancestor-fact reuse (FA-017.7B.3) --------------------------


@dataclass(frozen=True, slots=True)
class _CachedAncestorFact:
    """A shared ancestor's classification, plus the two cheap fields
    (besides identity itself) needed to detect it having become stale
    without re-doing the expensive os.scandir/classify_directory work:
    `name` (renamed into/out of a hard-exclusion match) and `mtime` (a
    marker file added/removed -- NTFS updates a directory's own mtime
    when its immediate children change). `fact` is None for "clear, not
    protected" -- the same vocabulary find_structural_protection's own
    ancestor loop already uses (None = keep checking/eligible)."""

    name: str
    mtime: float
    fact: StructuralProtection | None


class ScanStructuralContext:
    """A scan-scoped (ONE analyze_managed_root / analyze_file /
    build_organization_plan invocation, never longer) cache of shared-
    ANCESTOR structural facts -- eliminating the redundant os.scandir +
    classify_directory work find_structural_protection would otherwise
    repeat, unchanged, for every candidate that shares an ancestor (the
    common case: many files under one flat or lightly-nested folder).

    SCAN-SCOPED STRUCTURAL REUSE != EXECUTION AUTHORIZATION: this class
    has no method that returns anything other than exactly what
    find_structural_protection itself already returns
    (StructuralProtection | StructuralInspectionFailure | None) --
    consumed identically by every existing caller. It is never
    serialized, never persisted, never stored on
    FileAgentApplicationService.self, never threaded into Apply/Undo/
    Restore/destination-setup, and never shared between two separate
    invocations (each of those constructs its own, fresh instance -- see
    application/service.py::analyze_managed_root/analyze_file and
    application/planner.py::build_organization_plan).

    SHARED-ANCESTOR REUSE != SOURCE-LEAF REUSE: the candidate leaf's own
    reference/reparse state (`inspect_candidate_reference=True`) is
    ALWAYS re-derived fresh, on every single call, via the exact same
    _inspect_reference_state call find_structural_protection itself would
    make -- never cached, never inferred from any ancestor fact.

    Fail-closed, by construction: a StructuralInspectionFailure for an
    ancestor is returned directly and NEVER cached as a reusable fact
    (Part 7) -- the next candidate under that same ancestor re-attempts
    the full inspection fresh. An ancestor that currently cannot be
    conclusively proven to exist with a stable identity (FileNotFoundError
    from either the identity stat or the subsequent os.scandir) is never
    cached either -- only a conclusively-existing, successfully-
    classified ancestor becomes a cache entry. A directory replaced
    (new st_dev/st_ino), renamed (new name), or whose own contents
    changed (new mtime -- e.g. a marker file appearing) after being
    cached is detected on the very next candidate that touches it and
    forces a full, fresh re-derivation -- the cached entry is never
    trusted once any of these three cheap, already-available fields
    disagrees with what a fresh stat just observed. A directory turned
    into a symlink/junction/reparse point is caught unconditionally,
    every time, for every candidate, regardless of cache state, because
    that check is never part of the cached fact in the first place --
    _inspect_reference_state's own reparse detection runs fresh on every
    call, exactly as find_structural_protection already does today.
    """

    def __init__(self, root_path: Path) -> None:
        self._root_path = root_path
        self._ancestor_facts: dict[tuple[int, int], _CachedAncestorFact] = {}

    def check_candidate(
        self,
        candidate_path: Path,
        *,
        inspect_candidate_reference: bool,
    ) -> StructuralProtection | StructuralInspectionFailure | None:
        """Drop-in equivalent of find_structural_protection(candidate_path,
        self._root_path, inspect_candidate_reference=...) -- identical
        return type and semantics, reusing shared-ancestor facts across
        calls within this one context's lifetime wherever safe to do so."""
        root_path = self._root_path
        if candidate_path == root_path or not candidate_path.is_relative_to(root_path):
            return StructuralInspectionFailure(
                candidate_path, "candidate_path is not a strict descendant of root_path"
            )

        if inspect_candidate_reference:
            leaf_inspection = _inspect_reference_state(candidate_path)
            if isinstance(leaf_inspection, StructuralInspectionFailure):
                return leaf_inspection
            if leaf_inspection.is_reparse:
                return StructuralInspectionFailure(
                    candidate_path,
                    "candidate itself is a symlink, junction, or reparse point",
                )

        ancestors = [p for p in candidate_path.parents if p.is_relative_to(root_path)]
        for ancestor in ancestors:
            fact_or_rejection = self._ancestor_fact(ancestor)
            if fact_or_rejection is not None:
                return fact_or_rejection

        return None

    def _ancestor_fact(
        self, ancestor: Path
    ) -> StructuralProtection | StructuralInspectionFailure | None:
        """One ancestor's outcome -- None means "clear, keep checking the
        next ancestor," mirroring find_structural_protection's own
        per-ancestor loop body exactly. Reparse/inspection-failure/
        missing-ancestor outcomes are always freshly re-derived and never
        cached (see class docstring)."""
        reference_inspection = _inspect_reference_state(ancestor)
        if isinstance(reference_inspection, StructuralInspectionFailure):
            return reference_inspection
        if reference_inspection.is_reparse:
            return StructuralInspectionFailure(
                ancestor, "ancestor is a symlink, junction, or reparse point"
            )
        stat_identity = reference_inspection.stat_identity
        if stat_identity is None:
            # Does not currently exist -- never cached (nothing stable to
            # key on), conclusively nothing to protect here, matching
            # find_structural_protection's own FileNotFoundError handling
            # around its os.scandir call below.
            return None

        key = (stat_identity.st_dev, stat_identity.st_ino)
        cached = self._ancestor_facts.get(key)
        if (
            cached is not None
            and cached.name == ancestor.name
            and cached.mtime == stat_identity.mtime
        ):
            return cached.fact

        if is_hard_excluded_directory_name(ancestor.name):
            fact: StructuralProtection | None = StructuralProtection(
                StructuralProtectionKind.HARD_EXCLUSION,
                root_path=ancestor,
                marker=None,
                marker_path=None,
                excluded_name=ancestor.name,
            )
            self._ancestor_facts[key] = _CachedAncestorFact(
                name=ancestor.name, mtime=stat_identity.mtime, fact=fact
            )
            return fact

        try:
            entries = list(os.scandir(ancestor))
        except FileNotFoundError:
            # Existed a moment ago (the identity stat above just
            # succeeded); gone now. A genuine, already-accepted TOCTOU
            # gap (see this module's own docstring) -- never cached.
            return None
        except OSError as exc:
            return StructuralInspectionFailure(ancestor, str(exc))

        membership = classify_directory(ancestor, entries)
        self._ancestor_facts[key] = _CachedAncestorFact(
            name=ancestor.name, mtime=stat_identity.mtime, fact=membership
        )
        return membership


# --- Leaf inspection (FA-017.2 destination-setup TOCTOU) --------------------


class LeafState(str, Enum):
    """Fail-closed classification of exactly what currently sits at a
    single path -- used by destination_engine's create-directory sequence
    both as the pre-mkdir check and as the post-FileExistsError
    re-inspection (see application/service.py::prepare_destinations).
    Distinct from _ReferenceState above: this classifies the FULL leaf
    (including plain-file vs plain-directory), not just reparse-point
    status, and is a public, reusable primitive rather than this module's
    own private helper."""

    ABSENT = "absent"
    NORMAL_DIRECTORY = "normal_directory"
    NORMAL_FILE = "normal_file"
    REPARSE_POINT = "reparse_point"
    INSPECTION_FAILED = "inspection_failed"


def inspect_leaf(path: Path) -> LeafState:
    """Fail-closed classification of exactly what currently sits at `path`,
    never following symlinks. Uses the identical three-way reparse/reference
    detection technique as _inspect_reference_state above (is_symlink(),
    then isjunction(), then the stat result's own
    FILE_ATTRIBUTE_REPARSE_POINT flag) rather than a second, independently
    written implementation of the same check.

    FileNotFoundError -> ABSENT (conclusive: an entry that isn't there
    can't hide a marker or a reparse point -- same reasoning
    _inspect_reference_state already documents). Any other OSError during
    inspection -> INSPECTION_FAILED, never silently coerced to a
    normal-entry classification. A stat result that is neither a directory
    nor a regular file -> INSPECTION_FAILED (fail closed on an exotic
    object type -- a block/char device, FIFO, or socket -- rather than
    guessing)."""
    try:
        if path.is_symlink():
            return LeafState.REPARSE_POINT
        if os.path.isjunction(path):
            return LeafState.REPARSE_POINT
        st = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return LeafState.ABSENT
    except OSError:
        return LeafState.INSPECTION_FAILED
    if st.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return LeafState.REPARSE_POINT
    if stat.S_ISDIR(st.st_mode):
        return LeafState.NORMAL_DIRECTORY
    if stat.S_ISREG(st.st_mode):
        return LeafState.NORMAL_FILE
    # block/char device, FIFO, socket, or any other mode this design has
    # no defined meaning for.
    return LeafState.INSPECTION_FAILED


__all__ = [
    "LeafState",
    "ProjectMarkerType",
    "ScanStructuralContext",
    "StructuralInspectionFailure",
    "StructuralProtection",
    "StructuralProtectionKind",
    "classify_directory",
    "find_structural_protection",
    "inspect_leaf",
    "is_hard_excluded_directory_name",
]
