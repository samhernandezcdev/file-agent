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


class _ReferenceState(Enum):
    NORMAL = "normal"
    REPARSE_POINT = "reparse_point"


def _inspect_reference_state(
    path: Path,
) -> "_ReferenceState | StructuralInspectionFailure":
    """Three-way, fail-closed reference inspection. NEVER silently coerces
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
            return _ReferenceState.REPARSE_POINT
        if os.path.isjunction(path):
            return _ReferenceState.REPARSE_POINT
        st = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return _ReferenceState.NORMAL
    except OSError as exc:
        return StructuralInspectionFailure(
            path, f"could not determine reference status: {exc}"
        )
    if st.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return _ReferenceState.REPARSE_POINT
    return _ReferenceState.NORMAL


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
        leaf_state = _inspect_reference_state(candidate_path)
        if isinstance(leaf_state, StructuralInspectionFailure):
            return leaf_state
        if leaf_state is _ReferenceState.REPARSE_POINT:
            return StructuralInspectionFailure(
                candidate_path,
                "candidate itself is a symlink, junction, or reparse point",
            )

    ancestors = [p for p in candidate_path.parents if p.is_relative_to(root_path)]
    for ancestor in ancestors:
        reference_state = _inspect_reference_state(ancestor)
        if isinstance(reference_state, StructuralInspectionFailure):
            return reference_state
        if reference_state is _ReferenceState.REPARSE_POINT:
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


__all__ = [
    "ProjectMarkerType",
    "StructuralInspectionFailure",
    "StructuralProtection",
    "StructuralProtectionKind",
    "classify_directory",
    "find_structural_protection",
    "is_hard_excluded_directory_name",
]
