"""FA-015 Managed Roots -- the product's filesystem authority boundary.

FileAgent may only analyze/organize files inside an explicitly registered,
currently-active ManagedRoot. This module owns:

- The read-model DTOs (`ManagedRootView`, `ManagedRootUnavailable`,
  `RemoveManagedRootResult`) that `application/service.py`'s public methods
  return.
- `_resolve_safe_managed_root` -- the ONE shared, live-reinspecting
  primitive that turns a persisted `ManagedRoot.path` into an operational
  `SandboxRoot`. Registration-time success only proves a path was safe
  ONCE; every operation that later uses that root re-derives this proof
  FRESH, because the filesystem can change after registration with zero
  action by FileAgent -- most importantly, an ancestor directory of an
  already-registered root can later itself become a symlink/junction,
  silently redirecting FileAgent's authority to a different physical tree.
  Every call site that needs a live SandboxRoot from a ManagedRoot MUST go
  through this function -- see tests/application/test_managed_root_ast_guardrail.py
  for the structural guardrail enforcing that.
- Registration validation (`register_managed_root`) and the two read
  orchestration functions (`list_managed_root_views`, `remove_managed_root`)
  `application/service.py`'s add/list/remove_managed_root methods delegate
  to.

Residual TOCTOU window (documented explicitly, consistent with this
codebase's existing convention for accepted filesystem-race gaps -- see
vault_engine/safety.py's own docstring for the precedent): every check in
`_resolve_safe_managed_root` (lexical ancestor-reparse inspection -> final
SandboxRoot.from_path/resolve -> app-data disjointness) is a fail-closed,
POINT-IN-TIME proof, not an atomic filesystem snapshot. A concurrent,
adversarial external process with write access to the relevant directory
tree could in principle swap a component between one internal check and the
next within a single `_resolve_safe_managed_root` call. FA-015 does not
close this window -- doing so would require Windows File ID/USN-journal
tracking, directory handles held open across the whole check-then-use
sequence, or a global filesystem lock, none of which are introduced here
(see the FA-015 design's explicit non-goals). This is the same class of
residual race already accepted elsewhere in this codebase (e.g.
transaction_engine's destination-side reparse checks, vault_engine's own
root-disjointness check).

Deliberately NOT part of the live primitive (registration-only, evaluated
once at acceptance time, not re-verified on every later use): breadth
policy (drive-root/user-profile/system-directory rejection) and the
overlap/duplicate check against other active roots. Neither is a safety
property that can be silently violated by an unrelated filesystem change
the way reparse-point hijacking and app-data collision can.
"""

import os
import stat
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from uuid import UUID

from file_agent.application.errors import (
    AppDataManagedRootError,
    DuplicateManagedRootError,
    FilesystemRootManagedRootError,
    InvalidManagedRootPathError,
    ManagedRootRegistrationError,
    ManagedRootReparsePointError,
    OverlappingManagedRootError,
    SystemDirectoryManagedRootError,
    UserProfileManagedRootError,
)
from file_agent.domain import ManagedRoot
from file_agent.persistence import AppPaths, FileAgentStore
from file_agent.scanner import SandboxRoot
from file_agent.scanner.sandbox_root import SandboxRootError

# --- Read-model DTOs ---------------------------------------------------------


class ManagedRootStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ManagedRootView:
    """Product-facing, output-only view of one active ManagedRoot. `status`
    is always computed fresh via `_resolve_safe_managed_root` -- never
    cached, never continuously monitored (no watcher/background health
    check, per the ticket's own non-goal)."""

    id: UUID
    path: Path
    status: ManagedRootStatus


class ManagedRootLookupStatus(str, Enum):
    NOT_FOUND = "not_found"
    """The id was never registered, or was removed -- both collapse to "not
    currently authoritative" from a caller's perspective."""
    UNAVAILABLE = "unavailable"
    """Registered/active, but _resolve_safe_managed_root currently fails for
    it: missing, renamed, unsafe, or its ancestor chain has since been
    hijacked by a reparse point."""


@dataclass(frozen=True, slots=True)
class ManagedRootUnavailable:
    managed_root_id: UUID
    status: ManagedRootLookupStatus
    detail: str


class ManagedRootActionStatus(str, Enum):
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class RemoveManagedRootResult:
    managed_root_id: UUID
    status: ManagedRootActionStatus
    reason_code: str | None
    """e.g. "managed_root_not_found" -- unknown id or already-removed id
    (idempotent-safe: removing twice is a normal REJECTED outcome, never an
    error)."""
    reason: str | None


class ManagedRootPathFailureReason(str, Enum):
    UNSUPPORTED_SYNTAX = "unsupported_syntax"
    """Not absolute, or contains a '.'/'..' path component."""
    REPARSE_POINT_IN_CHAIN = "reparse_point_in_chain"
    """The root itself, or any ancestor up to the drive root, in the
    ORIGINAL unresolved path, is a symlink/junction/reparse point."""
    INVALID_OR_UNAVAILABLE = "invalid_or_unavailable"
    """SandboxRoot.from_path itself failed: missing, not a directory, UNC,
    or any other base check."""
    APP_DATA_OVERLAP = "app_data_overlap"
    """The freshly RESOLVED root now equals / is inside / contains
    AppPaths.root."""


@dataclass(frozen=True, slots=True)
class ManagedRootPathFailure:
    reason: ManagedRootPathFailureReason
    detail: str


# --- Lexical ancestor-reparse-point inspection -------------------------------
#
# A small local copy of scanner._paths.is_reparse_point's exact logic,
# rather than a cross-package private import -- matches this codebase's
# established convention (see recovery_engine/_paths.py's own docstring for
# the precedent: small pure-path helpers are duplicated per-package, while
# higher-level orchestration is shared at the public-API boundary).


def _is_reparse_point(path: Path) -> bool:
    """True if `path` itself (not its target) is a symlink, NTFS junction,
    or any other reparse-tagged entry. Never follows `path` -- correct even
    for a reparse point whose target is missing/unresolvable."""
    if path.is_symlink():
        return True
    if os.path.isjunction(path):
        return True
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return bool(st.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _find_reparse_ancestor(path: Path) -> Path | None:
    """Walk every prefix of `path`, drive root through leaf, IN ORDER,
    checking each for reparse-point status BEFORE any resolve() -- this is
    what catches a junction anywhere in the lexical chain (including one
    introduced after this exact path was last used safely), regardless of
    what it would currently resolve to. Returns the first offending prefix,
    or None. `_is_reparse_point` is checked before existence at each step
    specifically so a reparse point with a broken/unresolvable target is
    still caught (Path.exists() follows the link and would otherwise report
    False, masking the very entry this function exists to find)."""
    current = Path(path.anchor)
    if _is_reparse_point(current):
        return current
    for part in path.parts[1:]:
        current = current / part
        if _is_reparse_point(current):
            return current
        if not current.exists():
            # Nothing deeper can exist under a nonexistent prefix; the
            # eventual SandboxRoot.from_path(strict=True) call rejects this
            # missing-path case with its own, appropriately-scoped failure.
            break
    return None


def _has_unsupported_dot_components(path: Path) -> bool:
    """Rejects '.'/'..' outright rather than lexically collapsing them.

    A pure textual collapse of '..' (e.g. via os.path.normpath, with no
    filesystem awareness) is only safe when no '..' sits immediately after
    a component that is itself a reparse point. Consider
    C:\\Users\\Ana\\Alias\\..\\Sensitive where Alias is a junction to
    D:\\External: a real, symlink-aware OS walk would enter Alias first
    (landing in D:\\External) and only then apply '..' FROM THERE --
    landing somewhere under D:\\, not under C:\\Users\\Ana at all. A blind
    textual collapse instead cancels "Alias\\.." as a pair and produces
    C:\\Users\\Ana\\Sensitive, silently erasing the very component the
    ancestor scan needs to see. A real folder-picker UI never produces
    '.'/'..' in a selected path anyway, so disallowing them entirely
    removes this ambiguity completely rather than trying to resolve it
    cleverly.
    """
    return "." in path.parts or ".." in path.parts


# --- The shared, live-reinspecting resolution primitive ---------------------


def _resolve_safe_managed_root(
    path: Path, app_paths: AppPaths
) -> SandboxRoot | ManagedRootPathFailure:
    """The ONE trusted path-to-SandboxRoot resolution primitive for every
    ManagedRoot operation -- registration included. Called fresh on every
    single use: never cached, never assumed from a prior successful call.
    Registration-time success proves a path was safe THEN; this proves it
    is safe NOW. Returns a structured failure, never raises, never guesses,
    never substitutes a cached or previously-resolved value.
    """
    if not path.is_absolute() or _has_unsupported_dot_components(path):
        return ManagedRootPathFailure(
            ManagedRootPathFailureReason.UNSUPPORTED_SYNTAX,
            f"path must be absolute with no '.'/'..' components, got: {path!r}",
        )

    offending = _find_reparse_ancestor(path)
    if offending is not None:
        return ManagedRootPathFailure(
            ManagedRootPathFailureReason.REPARSE_POINT_IN_CHAIN,
            f"{offending!r} is a symlink, junction, or reparse point",
        )

    try:
        sandbox_root = SandboxRoot.from_path(path)
    except SandboxRootError as exc:
        return ManagedRootPathFailure(
            ManagedRootPathFailureReason.INVALID_OR_UNAVAILABLE, str(exc)
        )

    # App-data disjointness, re-checked live against the FRESHLY resolved
    # root -- not the persisted/input path string -- since an ancestor swap
    # can cause the resolved target to drift into AppPaths.root even when
    # the original lexical input never came near it. Mirrors
    # vault_engine.safety.ensure_disjoint_roots's exact three-way shape
    # (equal / app-inside-root / root-inside-app); inlined here rather than
    # imported, per this module's own per-package-duplication convention.
    app_root = app_paths.root.resolve(strict=False)
    managed = sandbox_root.path
    if (
        app_root == managed
        or app_root.is_relative_to(managed)
        or managed.is_relative_to(app_root)
    ):
        return ManagedRootPathFailure(
            ManagedRootPathFailureReason.APP_DATA_OVERLAP,
            f"managed root {managed!r} is not disjoint from the "
            f"application-owned root {app_root!r}",
        )

    return sandbox_root


_REGISTRATION_ERROR_FOR_REASON: dict[
    ManagedRootPathFailureReason, type[ManagedRootRegistrationError]
] = {
    ManagedRootPathFailureReason.UNSUPPORTED_SYNTAX: InvalidManagedRootPathError,
    ManagedRootPathFailureReason.INVALID_OR_UNAVAILABLE: InvalidManagedRootPathError,
    ManagedRootPathFailureReason.REPARSE_POINT_IN_CHAIN: ManagedRootReparsePointError,
    ManagedRootPathFailureReason.APP_DATA_OVERLAP: AppDataManagedRootError,
}


# --- Registration-only checks (breadth policy, overlap) ----------------------

_SYSTEM_DIRECTORY_ENV_VARS: tuple[str, ...] = (
    "WINDIR",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMDATA",
)


def _reject_bare_drive_root(resolved: Path) -> None:
    if resolved == Path(resolved.anchor):
        raise FilesystemRootManagedRootError(
            resolved,
            "cannot register an entire filesystem drive; choose a specific folder",
        )


def _reject_user_profile_root(resolved: Path) -> None:
    """Rejects ANY Windows user-profile directory, not just the current
    user's -- keyed structurally off Path.home()'s own parent, never a
    hardcoded username, so this equally catches C:\\Users\\Ana,
    C:\\Users\\Bob, and C:\\Users\\Public via one principled rule."""
    home_parent = Path.home().resolve(strict=False).parent
    if resolved.parent == home_parent:
        raise UserProfileManagedRootError(
            resolved,
            "cannot register an entire Windows user-profile directory; "
            "choose a specific folder inside it",
        )


def _reject_system_directory_root(resolved: Path) -> None:
    """Exact-equality only, deliberately -- a descendant such as
    C:\\Windows\\System32 is NOT rejected by this check (that comprehensive
    a policy belongs to FA-016's Protected Trees, not here)."""
    for var in _SYSTEM_DIRECTORY_ENV_VARS:
        raw = os.environ.get(var)
        if not raw:
            continue
        candidate = Path(raw).resolve(strict=False)
        if resolved == candidate:
            raise SystemDirectoryManagedRootError(
                resolved,
                f"cannot register the OS-standard directory referenced by %{var}%",
            )


def _reject_overlap(resolved: Path, active_roots: Sequence[ManagedRoot]) -> None:
    """Checked against active roots only -- a removed root imposes no
    constraint on future registrations. Three-way check per existing active
    root, mirroring vault_engine.safety.ensure_disjoint_roots's exact shape:
    equality, new-inside-existing, existing-inside-new. No "most specific
    root wins" -- overlap is always a hard reject."""
    for existing in active_roots:
        if resolved == existing.path:
            raise DuplicateManagedRootError(resolved, existing.id)
        if resolved.is_relative_to(existing.path) or existing.path.is_relative_to(
            resolved
        ):
            raise OverlappingManagedRootError(resolved, existing.id, existing.path)


# --- Orchestration (store-facing) --------------------------------------------


def register_managed_root(
    store: FileAgentStore,
    app_paths: AppPaths,
    path: Path,
    *,
    clock: Callable[[], datetime],
) -> ManagedRootView:
    """Full add_managed_root validation order: the shared live primitive
    first (proving syntax/reparse-safety/existence/app-data-disjointness),
    then registration-only breadth policy, then registration-only
    overlap/duplicate checking against the currently-active set -- pure
    validation (read-only filesystem inspection + a store read) until the
    final persist. Raises a ManagedRootRegistrationError subclass on any
    failure; never partially registers."""
    outcome = _resolve_safe_managed_root(path, app_paths)
    if isinstance(outcome, ManagedRootPathFailure):
        raise _REGISTRATION_ERROR_FOR_REASON[outcome.reason](path, outcome.detail)

    resolved = outcome.path
    _reject_bare_drive_root(resolved)
    _reject_user_profile_root(resolved)
    _reject_system_directory_root(resolved)

    active_roots = [root for root in store.list_managed_roots() if root.is_active]
    _reject_overlap(resolved, active_roots)

    managed_root = ManagedRoot(path=resolved, created_at=clock())
    store.record_managed_root(managed_root)
    return ManagedRootView(
        managed_root.id, managed_root.path, ManagedRootStatus.AVAILABLE
    )


def list_managed_root_views(
    store: FileAgentStore, app_paths: AppPaths
) -> tuple[ManagedRootView, ...]:
    """Active roots only -- a removed root is no longer one of "the folders
    FileAgent can organize" and is not shown here (contrast with History,
    which remains fully readable for removed roots). Status is computed
    fresh, per root, via the shared live primitive -- no caching, no
    continuous health monitoring."""
    views: list[ManagedRootView] = []
    for root in store.list_managed_roots():
        if not root.is_active:
            continue
        outcome = _resolve_safe_managed_root(root.path, app_paths)
        status = (
            ManagedRootStatus.AVAILABLE
            if isinstance(outcome, SandboxRoot)
            else ManagedRootStatus.UNAVAILABLE
        )
        views.append(ManagedRootView(root.id, root.path, status))
    return tuple(views)


def remove_managed_root(
    store: FileAgentStore, managed_root_id: UUID, *, clock: Callable[[], datetime]
) -> RemoveManagedRootResult:
    """Soft-delete only -- sets removed_at, never deletes the row, never
    touches the filesystem. Idempotent-safe: removing an already-removed or
    unknown id is a normal REJECTED outcome, never an exception."""
    existing = store.get_managed_root(managed_root_id)
    if existing is None or not existing.is_active:
        return RemoveManagedRootResult(
            managed_root_id,
            ManagedRootActionStatus.REJECTED,
            "managed_root_not_found",
            f"no active managed root with id={managed_root_id}",
        )
    store.remove_managed_root(managed_root_id, clock())
    return RemoveManagedRootResult(
        managed_root_id, ManagedRootActionStatus.SUCCEEDED, None, None
    )
