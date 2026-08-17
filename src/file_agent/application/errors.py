"""Errors raised by the Application Service itself.

FA-012 introduced exactly one new exception type (TerminalPersistenceError).
FA-013 introduced one more (DuplicatePolicyDecisionIdError). FA-014 reuses
DuplicatePolicyDecisionIdError verbatim for apply_items (the exact same
contract applies) and introduces exactly one new type
(EmptyBatchSelectionError). FA-015 introduces MixedManagedRootsError (same
"reject before I/O where possible" category as the two above) and the
ManagedRootRegistrationError hierarchy (add_managed_root's validation
rejections). Every other exception a caller might see already exists in a
lower layer (persistence's
DatabaseUnavailableError/IntegrityConstraintError, vault_engine's/
recovery_engine's
InvalidVaultConfigurationError/InvalidRecoveryConfigurationError) and is
re-raised as-is, never wrapped.
"""

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from file_agent.application.dto import ApplyResult, RestoreResult, UndoResult


class TerminalPersistenceError(Exception):
    """Raised when a managed-file mutation (or recovery/vault operation)
    already completed via commit(), but persisting the terminal audit event
    failed. The operation is NOT rolled back and its real outcome is NOT
    reinterpreted as failure -- this exists solely to surface the audit gap
    distinctly, without silently swallowing it or misreporting what actually
    happened on disk.

    A caller catching this has the accurate, already-computed result (with
    status SUCCEEDED, and the real destination/restored path) via
    `.result` -- never a fabricated REJECTED/FAILED outcome. One shared
    class, not three per-DTO subclasses: `.result` is a union type, and
    `isinstance(exc.result, ApplyResult)` (etc.) is sufficient for a caller
    that needs to discriminate.
    """

    def __init__(
        self,
        result: ApplyResult | UndoResult | RestoreResult,
        cause: Exception,
    ) -> None:
        super().__init__(
            f"terminal event persistence failed after {type(result).__name__} "
            f"completed with status={result.status}: {cause}"
        )
        self.result = result


class DuplicatePolicyDecisionIdError(ValueError):
    """Raised by build_organization_plan (create_organization_plan) when
    policy_decision_ids contains a duplicate. Duplicate ids are invalid
    caller input -- a programming error in the caller, not a business-state
    outcome -- and are never represented as a PlanIssue. Validated before any
    persistence query or filesystem observation, so raising this never has
    any side effect."""

    def __init__(self, duplicate_ids: tuple[UUID, ...]) -> None:
        super().__init__(f"duplicate policy_decision_id(s) in input: {duplicate_ids}")
        self.duplicate_ids = duplicate_ids


class EmptyBatchSelectionError(ValueError):
    """Raised by apply_items(policy_decision_ids=[]). An empty batch apply
    is a caller/UI programming error, not a business outcome -- it must not
    create a BATCH_APPLY_STARTED history entry (no history noise for
    nothing selected). Validated before any persistence query."""

    def __init__(self) -> None:
        super().__init__("apply_items() requires at least one policy_decision_id")


def reject_duplicate_policy_decision_ids(policy_decision_ids: Sequence[UUID]) -> None:
    """Shared by create_organization_plan (FA-013) and apply_items (FA-014)
    -- identical contract: duplicates are invalid caller input, rejected
    before any persistence query or filesystem I/O, never silently
    deduplicated."""
    seen: set[UUID] = set()
    duplicates: list[UUID] = []
    for policy_decision_id in policy_decision_ids:
        if policy_decision_id in seen:
            duplicates.append(policy_decision_id)
        seen.add(policy_decision_id)
    if duplicates:
        raise DuplicatePolicyDecisionIdError(tuple(duplicates))


class MixedManagedRootsError(ValueError):
    """FA-015. Raised by create_organization_plan/apply_items when the
    selected ids' independently-resolvable lineage disagrees on which
    ManagedRoot they belong to -- one plan/batch must be scoped to exactly
    one root (single-root invariant). A structural, cross-item consistency
    problem over the selected SET, analogous to DuplicatePolicyDecisionIdError
    -- unlike that check, detecting this requires resolving each id's
    lineage (real persistence reads), not a free in-memory set operation;
    see application/managed_roots.py and planner.py for the exact ordering
    this is raised in (always before any filesystem inspection/mutation).
    Ids that fail lineage resolution entirely never trigger this error --
    only two or more SUCCESSFULLY resolved ids disagreeing does."""

    def __init__(
        self, policy_decision_ids: Sequence[UUID], roots_seen: set[UUID]
    ) -> None:
        super().__init__(
            f"policy_decision_ids resolve to {len(roots_seen)} distinct "
            f"managed roots {sorted(roots_seen, key=str)}; a single plan/batch "
            "must be scoped to exactly one managed root"
        )
        self.policy_decision_ids = tuple(policy_decision_ids)
        self.roots_seen = frozenset(roots_seen)


class ManagedRootRegistrationError(ValueError):
    """FA-015. Base for every add_managed_root() validation rejection.
    Registration-time validation is a deterministic, before-any-write
    decision given (proposed path, current active roots, AppPaths) -- the
    same "reject invalid caller input before I/O" category as
    DuplicatePolicyDecisionIdError/EmptyBatchSelectionError, not a runtime
    business-state outcome. A common catchable base exists for a UI that
    just wants the generic Spanish fallback; concrete subclasses below carry
    structured data for precise messaging/tests."""

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"cannot register managed root {path!r}: {reason}")
        self.path = path
        self.reason = reason


class InvalidManagedRootPathError(ManagedRootRegistrationError):
    """Unsupported syntax (not absolute, contains . / ..), or the base
    SandboxRoot.from_path checks fail (does not exist, not a directory,
    UNC)."""


class ManagedRootReparsePointError(ManagedRootRegistrationError):
    """The proposed root, or any ancestor of it up to the drive root, is a
    symlink/junction/reparse point -- checked against the original,
    unresolved lexical path (see _resolve_safe_managed_root)."""


class FilesystemRootManagedRootError(ManagedRootRegistrationError):
    """The proposed path is a bare drive/filesystem root (e.g. C:\\)."""


class UserProfileManagedRootError(ManagedRootRegistrationError):
    """The proposed path is a Windows user-profile directory (any user)."""


class SystemDirectoryManagedRootError(ManagedRootRegistrationError):
    """The proposed path exactly equals an OS-standard broad system
    directory (e.g. %WINDIR%) -- exact-match only; descendants are not
    rejected by this check (see FA-015 design §8)."""


class AppDataManagedRootError(ManagedRootRegistrationError):
    """The proposed (or, live, the freshly-resolved) root equals, is inside,
    or contains AppPaths.root."""


class DuplicateManagedRootError(ManagedRootRegistrationError):
    """The proposed path exactly equals an already-active ManagedRoot's
    path."""

    def __init__(self, path: Path, existing_managed_root_id: UUID) -> None:
        super().__init__(
            path,
            f"already registered as managed root {existing_managed_root_id}",
        )
        self.existing_managed_root_id = existing_managed_root_id


class OverlappingManagedRootError(ManagedRootRegistrationError):
    """The proposed path is nested with (in either direction) an already-
    active ManagedRoot's path."""

    def __init__(
        self, path: Path, existing_managed_root_id: UUID, existing_path: Path
    ) -> None:
        super().__init__(
            path,
            f"overlaps already-registered managed root {existing_managed_root_id} "
            f"at {existing_path!r}",
        )
        self.existing_managed_root_id = existing_managed_root_id
        self.existing_path = existing_path
