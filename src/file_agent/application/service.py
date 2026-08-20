"""FileAgentApplicationService -- the sole product-facing orchestration
boundary between UI/CLI and every engine below it. See package __init__.py
for the trust-boundary contract.
"""

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4
from weakref import WeakKeyDictionary

from file_agent import structural_safety
from file_agent.application import history, managed_roots, queries
from file_agent.application.destination_setup import (
    DestinationPreparationOutcome,
    DestinationPreparationStatus,
    DestinationSetupReasonCode,
    DestinationSetupResult,
    destination_setup_completed_event,
    destination_setup_item_result_event,
    destination_setup_started_event,
)
from file_agent.application.dto import (
    AnalysisFailure,
    AnalyzedItem,
    AnalyzedScanResult,
    ApplicationOutcomeStatus,
    ApplicationRejectionReason,
    ApplyResult,
    BatchApplyItemResult,
    BatchApplyItemStatus,
    BatchApplyResult,
    BatchApplySummary,
    BatchStatus,
    RestoreResult,
    ReviewActionResult,
    UndoResult,
)
from file_agent.application.errors import (
    EmptyBatchSelectionError,
    MixedManagedRootsError,
    TerminalPersistenceError,
    reject_duplicate_policy_decision_ids,
)
from file_agent.application.history import (
    BatchHistoryEntry,
    UnavailableBatchHistoryRow,
)
from file_agent.application.managed_roots import (
    ManagedRootLookupStatus,
    ManagedRootPathFailure,
    ManagedRootUnavailable,
    ManagedRootView,
    RemoveManagedRootResult,
)
from file_agent.application.organization_plan import (
    OrganizationPlan,
    missing_destination_categories,
)
from file_agent.application.planner import build_organization_plan
from file_agent.classifier import FileClassifier, classification_event
from file_agent.destination import resolve_destination, resolve_destination_directory
from file_agent.destination_engine import prepare_destination_directory
from file_agent.domain import (
    CompletedMoveEvidence,
    DestinationCategory,
    DiscoveredFile,
    ExecutionAuthorization,
    HumanReviewOutcome,
    PolicyOutcome,
    RecoveryRejectionCode,
    RecoveryResult,
    RecoveryStatus,
    RejectionCode,
    RestoreFromVaultRequest,
    ReverseMoveRequest,
    TransactionRequest,
    TransactionResult,
    TransactionStatus,
    VaultCaptureEvidence,
    VaultCaptureStatus,
)
from file_agent.hasher import FileHasher, HashFailure
from file_agent.human_review_engine import (
    HumanReviewEngine,
    InvalidHumanReviewError,
    human_review_recorded_event,
)
from file_agent.persistence import AppPaths, FileAgentStore
from file_agent.persistence.errors import (
    DatabaseUnavailableError,
    IntegrityConstraintError,
)
from file_agent.policy_engine import PolicyEngine, policy_decision_event
from file_agent.proposal_engine import ProposalEngine, proposal_event
from file_agent.recovery_engine import (
    RecoveryEngine,
    recovery_requested_event,
    recovery_result_event,
)
from file_agent.scanner import DirectoryScanner, SandboxRoot
from file_agent.transaction_engine import (
    TransactionEngine,
    transaction_requested_event,
    transaction_result_event,
    verify_source_identity,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


# Review-write serialization, scoped to the shared FileAgentStore rather than
# to any one FileAgentApplicationService instance (round-3 correction): two
# service objects wrapping the SAME store must serialize through the SAME
# lock, or a check-then-record-then-persist race between them can still
# persist two conflicting reviews for one PolicyDecision. Lives here, not in
# persistence/ or human_review_engine/ -- purely an application/-internal
# coordination detail; it does not change what either package can enforce on
# its own. Provides zero protection across OS processes -- see
# FileAgentApplicationService's module docstring for the full v1 contract.
_review_locks: "WeakKeyDictionary[FileAgentStore, threading.Lock]" = WeakKeyDictionary()
_review_locks_guard = threading.Lock()


def _review_lock_for(store: FileAgentStore) -> threading.Lock:
    with _review_locks_guard:
        if store not in _review_locks:
            _review_locks[store] = threading.Lock()
        return _review_locks[store]


# FA-015: a second, separate store-scoped lock for add_managed_root's
# check-then-insert sequence -- mirrors _review_lock_for exactly, kept
# distinct rather than shared since registration and review writes are
# unrelated operations (sharing one lock would add contention between them
# for no benefit). The partial unique index on managed_roots(path) (orm.py)
# is the last-resort backstop against a race across OS processes; this lock
# is the primary, race-free mechanism within one process.
_registration_locks: "WeakKeyDictionary[FileAgentStore, threading.Lock]" = (
    WeakKeyDictionary()
)
_registration_locks_guard = threading.Lock()


def _registration_lock_for(store: FileAgentStore) -> threading.Lock:
    with _registration_locks_guard:
        if store not in _registration_locks:
            _registration_locks[store] = threading.Lock()
        return _registration_locks[store]


def _not_found_or_malformed(
    failure: "queries.LookupFailure", not_found_reason: ApplicationRejectionReason
) -> tuple[str, str]:
    """find_proposal/find_policy_decision only ever return NOT_FOUND or
    MALFORMED -- never AMBIGUOUS/INCOMPLETE -- so this mapping is total for
    those two lookups specifically."""
    if failure.status is queries.LookupStatus.NOT_FOUND:
        return not_found_reason.value, failure.detail
    return ApplicationRejectionReason.MALFORMED_EVENT_PAYLOAD.value, failure.detail


def _transaction_lookup_reason(
    status: "queries.LookupStatus",
) -> ApplicationRejectionReason:
    return {
        queries.LookupStatus.NOT_FOUND: ApplicationRejectionReason.TRANSACTION_NOT_FOUND,
        queries.LookupStatus.MALFORMED: ApplicationRejectionReason.MALFORMED_EVENT_PAYLOAD,
        queries.LookupStatus.AMBIGUOUS: ApplicationRejectionReason.AMBIGUOUS_TRANSACTION_HISTORY,
        queries.LookupStatus.INCOMPLETE: ApplicationRejectionReason.REQUESTED_WITHOUT_TERMINAL,
    }[status]


def _capture_lookup_reason(
    status: "queries.LookupStatus",
) -> ApplicationRejectionReason:
    return {
        queries.LookupStatus.NOT_FOUND: ApplicationRejectionReason.CAPTURE_NOT_FOUND,
        queries.LookupStatus.MALFORMED: ApplicationRejectionReason.MALFORMED_EVENT_PAYLOAD,
        queries.LookupStatus.AMBIGUOUS: ApplicationRejectionReason.AMBIGUOUS_CAPTURE_HISTORY,
        queries.LookupStatus.INCOMPLETE: ApplicationRejectionReason.REQUESTED_WITHOUT_TERMINAL,
    }[status]


def _structural_detail(
    outcome: "structural_safety.StructuralProtection | structural_safety.StructuralInspectionFailure",
) -> str:
    """FA-016: renders a find_structural_protection outcome into the free-
    text `reason`/`detail` field every rejection DTO already carries
    alongside its reason_code -- English/technical, audit-only, never shown
    verbatim in Spanish (matches ManagedRootPathFailure.detail's own
    precedent). The three causes (Protected Tree, hard exclusion, inconclusive
    inspection) are deliberately NOT distinguished by reason_code -- only
    here, for anyone reading raw history/logs."""
    if isinstance(outcome, structural_safety.StructuralInspectionFailure):
        return outcome.detail
    if outcome.kind is structural_safety.StructuralProtectionKind.HARD_EXCLUSION:
        return f"path is beneath a hard-excluded directory: {outcome.excluded_name}"
    return f"path is inside a protected project tree rooted at {outcome.root_path}"


def _outcome_for_leaf_state(
    category: DestinationCategory, leaf_state: "structural_safety.LeafState"
) -> DestinationPreparationOutcome:
    """FA-017.2: the one shared mapping from a structural_safety.LeafState
    to a DestinationPreparationOutcome, used identically by
    _prepare_one_destination's pre-mkdir check and its post-
    FileExistsError re-inspection -- see structural_safety.inspect_leaf's
    own docstring for the fail-closed classification this maps."""
    if leaf_state is structural_safety.LeafState.NORMAL_DIRECTORY:
        return DestinationPreparationOutcome(
            category, DestinationPreparationStatus.ALREADY_AVAILABLE, None
        )
    if leaf_state is structural_safety.LeafState.NORMAL_FILE:
        reason = DestinationSetupReasonCode.FILE_AT_DESTINATION
    elif leaf_state is structural_safety.LeafState.REPARSE_POINT:
        reason = DestinationSetupReasonCode.UNSAFE_REPARSE_POINT
    else:  # INSPECTION_FAILED (or, defensively, ABSENT reached via this path)
        reason = DestinationSetupReasonCode.OBSERVATION_FAILED
    return DestinationPreparationOutcome(
        category, DestinationPreparationStatus.NOT_PREPARED, reason
    )


@dataclass(frozen=True, slots=True)
class _ApplyOutcome:
    """Private, richer sibling of the public ApplyResult -- the single
    trusted result shape _apply_one returns. apply_item projects it down to
    ApplyResult (unchanged public contract); apply_items projects it up to
    the richer BatchApplyItemResult, which additionally needs proposal_id/
    file_id/filename for display. Never exported outside this module."""

    policy_decision_id: UUID
    proposal_id: UUID | None
    file_id: UUID | None
    filename: str | None
    status: ApplicationOutcomeStatus
    transaction_id: UUID | None
    source_path: Path | None
    destination_path: Path | None
    reason_code: str | None
    reason: str | None
    source_unchanged_confirmed: bool
    """FA-017.3. See BatchApplyItemResult's field of the same name for full
    semantics -- ephemeral, computed fresh in _apply_one, never persisted."""

    def to_apply_result(self) -> ApplyResult:
        return ApplyResult(
            self.policy_decision_id,
            self.transaction_id,
            self.status,
            self.source_path,
            self.destination_path,
            self.reason_code,
            self.reason,
            self.source_unchanged_confirmed,
        )


# reason_code -> BatchApplyItemStatus for the non-SUCCEEDED, non-default
# cases (mirrors PlanStatus.INVALID's own scope: downstream state is
# ambiguous, not identity). Every other REJECTED/FAILED reason_code falls
# through to NOT_APPLIED.
_BATCH_ITEM_STATUS_FOR_REASON: dict[str, BatchApplyItemStatus] = {
    ApplicationRejectionReason.REVIEW_OUTCOME_IS_SKIP.value: BatchApplyItemStatus.SKIPPED,
    ApplicationRejectionReason.AMBIGUOUS_REVIEW_HISTORY.value: BatchApplyItemStatus.INVALID,
    ApplicationRejectionReason.MALFORMED_EVENT_PAYLOAD.value: BatchApplyItemStatus.INVALID,
}


def _batch_item_status(
    status: ApplicationOutcomeStatus, reason_code: str | None
) -> BatchApplyItemStatus:
    if status is ApplicationOutcomeStatus.SUCCEEDED:
        return BatchApplyItemStatus.APPLIED
    if reason_code is not None and reason_code in _BATCH_ITEM_STATUS_FOR_REASON:
        return _BATCH_ITEM_STATUS_FOR_REASON[reason_code]
    return BatchApplyItemStatus.NOT_APPLIED


def _batch_item_result_from_outcome(
    input_index: int, outcome: _ApplyOutcome
) -> BatchApplyItemResult:
    return BatchApplyItemResult(
        policy_decision_id=outcome.policy_decision_id,
        input_index=input_index,
        proposal_id=outcome.proposal_id,
        file_id=outcome.file_id,
        filename=outcome.filename,
        status=_batch_item_status(outcome.status, outcome.reason_code),
        transaction_id=outcome.transaction_id,
        source_path=outcome.source_path,
        destination_path=outcome.destination_path,
        reason_code=outcome.reason_code,
        reason=outcome.reason,
        source_unchanged_confirmed=outcome.source_unchanged_confirmed,
    )


def _batch_item_result_from_apply_result(
    input_index: int, result: ApplyResult
) -> BatchApplyItemResult:
    """§6's documented, accepted display gap: TerminalPersistenceError only
    carries the public ApplyResult, not the richer _ApplyOutcome -- this
    item's proposal_id/file_id/filename are unavailable even though
    status/transaction_id/destination_path (the fields that actually matter
    for follow-up action, e.g. undo_transaction) are always present."""
    return BatchApplyItemResult(
        policy_decision_id=result.policy_decision_id,
        input_index=input_index,
        proposal_id=None,
        file_id=None,
        filename=None,
        status=_batch_item_status(result.status, result.reason_code),
        transaction_id=result.transaction_id,
        source_path=result.source_path,
        destination_path=result.destination_path,
        reason_code=result.reason_code,
        reason=result.reason,
        source_unchanged_confirmed=result.source_unchanged_confirmed,
    )


def _summarize_batch_items(
    requested_policy_decision_ids: Sequence[UUID],
    items: Sequence[BatchApplyItemResult],
) -> BatchApplySummary:
    applied = sum(1 for i in items if i.status is BatchApplyItemStatus.APPLIED)
    not_applied = sum(1 for i in items if i.status is BatchApplyItemStatus.NOT_APPLIED)
    skipped = sum(1 for i in items if i.status is BatchApplyItemStatus.SKIPPED)
    invalid = sum(1 for i in items if i.status is BatchApplyItemStatus.INVALID)
    return BatchApplySummary(
        selected=len(requested_policy_decision_ids),
        processed=len(items),
        applied=applied,
        not_applied=not_applied,
        skipped=skipped,
        invalid=invalid,
    )


def _verify_source_unchanged_after_failure(
    request: TransactionRequest, sandbox_root: SandboxRoot
) -> bool:
    """FA-017.3. Read-only, best-effort, observational only -- grants no
    authorization and performs no mutation. Reuses TransactionEngine's own
    existing verify_source_identity (transaction_engine/preconditions.py)
    -- the identical full FileHasher-based three-checkpoint identity
    reverification prepare() already performs (pre-open metadata match,
    open-vs-pre-open identity, post-read-vs-post-open identity) -- to
    POSITIVELY confirm the original file's identity, not merely its
    existence. A freshly-verified sha256 match (a `str` return) is the
    only True outcome. Any RejectionCode (SOURCE_NOT_FOUND,
    SOURCE_IDENTITY_CHANGED, SOURCE_HASH_MISMATCH) or any unexpected
    exception from the check itself yields False. False is never
    interpreted or rendered as "FileAgent moved/modified it" or "a partial
    move occurred" -- it means only that the positive claim cannot be
    made. verify_source_identity's own FileHasher.hash_file is documented
    as never raising -- "every problem becomes a HashFailure" -- so this
    try/except exists narrowly for the one remaining, unlikely surface:
    reconstructing the synthetic DiscoveredFile from the request's own
    already-once-validated snapshot fields. The catch is scoped to this
    single call only -- nothing else in _apply_one is affected -- so it
    cannot mask an unrelated defect elsewhere."""
    try:
        outcome = verify_source_identity(request, sandbox_root)
    except Exception:  # noqa: BLE001 -- narrowly scoped to this one
        # read-only, best-effort call; converts any surprise failure to
        # the conservative False, never lets it escape and replace the
        # already-computed, truthful FAILED apply result.
        return False
    # RejectionCode is itself a `str, Enum` subclass -- `isinstance(outcome,
    # str)` would be True for BOTH outcomes and can never distinguish them.
    # The only reliable check is the inverse: a RejectionCode member means
    # verification failed; anything else is the freshly verified sha256.
    return not isinstance(outcome, RejectionCode)


class FileAgentApplicationService:
    """Product-facing orchestration boundary. Every mutating method accepts
    only a stable, previously-persisted identifier -- never a path, hash,
    evidence object, prepared capability, or a caller-constructed
    TransactionRequest/HumanReviewDecision/PolicyDecision. See the package
    __init__.py docstring for the complete trust-boundary contract.

    FA-015: no constructor-level SandboxRoot -- FileAgent may only analyze/
    organize files inside an explicitly registered, currently-active
    ManagedRoot (add_managed_root/list_managed_roots/remove_managed_root).
    Every method that needs a live SandboxRoot resolves it fresh, per call,
    from a persisted ManagedRoot via managed_roots._resolve_safe_managed_root
    -- never cached, never assumed still valid from a prior call. See
    application/managed_roots.py's module docstring for the full rationale
    and the residual TOCTOU window this does not close.

    v1 concurrency contract for approve_review/skip_review: same process,
    same FileAgentStore instance -> serialized, race-free (via a store-scoped
    lock, shared by every FileAgentApplicationService built against that
    store). Different processes -> not guaranteed; a resulting duplicate/
    conflicting review history is always detected and fails closed
    (AMBIGUOUS_REVIEW_HISTORY), never resolved by timestamp or UUID
    ordering. add_managed_root has the identical v1 concurrency contract via
    its own separate store-scoped lock.
    """

    def __init__(
        self,
        app_paths: AppPaths,
        store: FileAgentStore,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._app_paths = app_paths
        self._store = store
        self._clock = clock
        self._review_lock = _review_lock_for(store)
        self._registration_lock = _registration_lock_for(store)

    # --- Managed roots -------------------------------------------------------

    def add_managed_root(self, path: Path) -> ManagedRootView:
        """The only public method anywhere that accepts a raw filesystem
        path. Raises a ManagedRootRegistrationError subclass on any
        validation failure -- see managed_roots.register_managed_root for
        the full ordered rule set."""
        with self._registration_lock:
            return managed_roots.register_managed_root(
                self._store, self._app_paths, path, clock=self._clock
            )

    def remove_managed_root(self, managed_root_id: UUID) -> RemoveManagedRootResult:
        """Soft-delete only -- no filesystem mutation, does not undo
        transactions/history/Vault objects. Idempotent-safe."""
        return managed_roots.remove_managed_root(
            self._store, managed_root_id, clock=self._clock
        )

    def list_managed_roots(self) -> tuple[ManagedRootView, ...]:
        """Active roots only, each with freshly-computed AVAILABLE/
        UNAVAILABLE status -- no caching, no continuous health monitoring."""
        return managed_roots.list_managed_root_views(self._store, self._app_paths)

    def _resolve_active_managed_root(
        self, managed_root_id: UUID
    ) -> SandboxRoot | ManagedRootUnavailable:
        """Shared by analyze_managed_root, apply_items' structural gate, and
        _apply_one's per-item layer-2 re-check: look up the ManagedRootRow,
        require it to be currently active (not removed), then re-derive
        live safety fresh via managed_roots._resolve_safe_managed_root --
        never a cached/assumed result. Historical fact ("this file was
        analyzed under root R") and current authority ("R is still managed
        now, and its lexical path chain is still safe") stay two distinct
        questions -- this method answers only the second."""
        managed_root = self._store.get_managed_root(managed_root_id)
        if managed_root is None or not managed_root.is_active:
            return ManagedRootUnavailable(
                managed_root_id,
                ManagedRootLookupStatus.NOT_FOUND,
                f"no active managed root with id={managed_root_id}",
            )
        outcome = managed_roots._resolve_safe_managed_root(
            managed_root.path, self._app_paths
        )
        if isinstance(outcome, ManagedRootPathFailure):
            return ManagedRootUnavailable(
                managed_root_id, ManagedRootLookupStatus.UNAVAILABLE, outcome.detail
            )
        return outcome

    def _resolve_historical_root(self, file_id: UUID) -> SandboxRoot | None:
        """The ONE trusted lineage chain for undo_transaction/restore_capture,
        never anything else: file_id -> FileObservationRow.managed_root_id ->
        ManagedRootRow.path -> live managed_roots._resolve_safe_managed_root.
        Returns None -- never raises, never guesses, never infers from
        current filesystem state or current ManagedRoot registrations by
        path-matching -- whenever any link in that chain is unavailable: no
        DiscoveredFile at all, managed_root_id is None (a pre-FA-015 legacy
        observation, permanently and expectedly so), the ManagedRootRow
        itself is missing (structurally shouldn't happen, since rows are
        never hard-deleted -- fail closed rather than assume), or the live
        primitive fails (folder gone/renamed/unsafe, including a
        since-hijacked ancestor). Deliberately does NOT require the root to
        still be actively registered (unlike _resolve_active_managed_root)
        -- undo/restore are historically-authorized recovery actions,
        independent of current registration status; RecoveryEngine's own
        live re-verification remains the actual safety boundary."""
        discovered = self._store.get_discovered_file(file_id)
        if discovered is None or discovered.managed_root_id is None:
            return None
        managed_root = self._store.get_managed_root(discovered.managed_root_id)
        if managed_root is None:
            return None
        outcome = managed_roots._resolve_safe_managed_root(
            managed_root.path, self._app_paths
        )
        if isinstance(outcome, ManagedRootPathFailure):
            return None
        return outcome

    # --- Analysis ----------------------------------------------------------

    def analyze_managed_root(
        self, managed_root_id: UUID
    ) -> AnalyzedScanResult | ManagedRootUnavailable:
        root_outcome = self._resolve_active_managed_root(managed_root_id)
        if isinstance(root_outcome, ManagedRootUnavailable):
            return root_outcome
        sandbox_root = root_outcome

        scan_result = DirectoryScanner(
            sandbox_root, managed_root_id=managed_root_id, clock=self._clock
        ).run()
        self._store.record_scan(scan_result)

        items: list[AnalyzedItem] = []
        failures: list[AnalysisFailure] = []
        for discovered in scan_result.files:
            outcome = self._analyze_discovered(discovered, sandbox_root)
            if isinstance(outcome, AnalysisFailure):
                failures.append(outcome)
            else:
                items.append(outcome)

        return AnalyzedScanResult(
            scan_id=scan_result.scan_run.id,
            items=tuple(items),
            failures=tuple(failures),
            files_discovered=len(scan_result.files),
            protected_trees=scan_result.protected_trees,
        )

    def analyze_file(self, file_id: UUID) -> AnalyzedItem | AnalysisFailure:
        discovered = self._store.get_discovered_file(file_id)
        if discovered is None:
            return AnalysisFailure(
                file_id=file_id, path=None, reason_code="file_not_found"
            )
        if discovered.managed_root_id is None:
            return AnalysisFailure(
                file_id=file_id,
                path=discovered.path,
                reason_code=ApplicationRejectionReason.MANAGED_ROOT_NOT_ACTIVE.value,
            )
        root_outcome = self._resolve_active_managed_root(discovered.managed_root_id)
        if isinstance(root_outcome, ManagedRootUnavailable):
            # FA-015: re-analyzing a file under a since-removed/unavailable
            # root would otherwise silently produce a new PolicyDecision
            # that could never be applied (always rejected later by
            # _apply_one's own layer-2 check) -- wasted, confusing work
            # rather than a security gap, but still worth rejecting here.
            return AnalysisFailure(
                file_id=file_id,
                path=discovered.path,
                reason_code=ApplicationRejectionReason.MANAGED_ROOT_NOT_ACTIVE.value,
            )
        sandbox_root = root_outcome

        # FA-016: structural safety checked BEFORE the re-stat below --
        # re-stat only reports whether *something* currently exists at this
        # path, which is a strictly weaker question than "is this path
        # itself, or one of its ancestors, a reparse point/protected tree/
        # hard exclusion." A hijacked ancestor redirecting to an external
        # location that happens to have nothing at the equivalent leaf path
        # would otherwise surface as a misleading "not_found" here, never
        # reaching the structural check inside _analyze_discovered at all.
        structural_outcome = structural_safety.find_structural_protection(
            discovered.path, sandbox_root.path, inspect_candidate_reference=True
        )
        if structural_outcome is not None:
            return AnalysisFailure(
                file_id=file_id,
                path=discovered.path,
                reason_code=ApplicationRejectionReason.STRUCTURALLY_PROTECTED.value,
            )

        try:
            st = discovered.path.stat()
        except OSError:
            return AnalysisFailure(
                file_id=file_id, path=discovered.path, reason_code="not_found"
            )
        # Re-stat fresh before hashing: the persisted DiscoveredFile row can
        # be stale relative to the file's current content -- analyze_file is
        # explicitly re-callable to create a new analysis generation from
        # whatever the file currently contains. Without this, FileHasher's
        # own pre-open metadata check would reject a genuinely changed file
        # as if it had been tampered with mid-scan.
        fresh = discovered.model_copy(
            update={
                "size_bytes": st.st_size,
                "created_at": datetime.fromtimestamp(st.st_ctime, tz=UTC),
                "modified_at": datetime.fromtimestamp(st.st_mtime, tz=UTC),
            }
        )
        return self._analyze_discovered(fresh, sandbox_root)

    def _analyze_discovered(
        self, discovered: DiscoveredFile, sandbox_root: SandboxRoot
    ) -> AnalyzedItem | AnalysisFailure:
        # FA-016: structural safety runs before classification -- the ONE
        # gate closing both "newly protected" and "historical/pre-FA-016
        # DiscoveredFile row now sitting under a Protected Tree or hard
        # exclusion" (no new scan required either way, since this is a live,
        # filesystem-based re-check, never dependent on when/how `discovered`
        # was originally persisted). inspect_candidate_reference=True: this
        # is an EXISTING source object, so the candidate itself -- not just
        # its ancestors -- must be conclusively proven not to have been
        # individually replaced by a symlink/junction/reparse object since
        # discovery.
        structural_outcome = structural_safety.find_structural_protection(
            discovered.path, sandbox_root.path, inspect_candidate_reference=True
        )
        if structural_outcome is not None:
            return AnalysisFailure(
                file_id=discovered.id,
                path=discovered.path,
                reason_code=ApplicationRejectionReason.STRUCTURALLY_PROTECTED.value,
            )

        hash_outcome = FileHasher(sandbox_root, clock=self._clock).hash_file(discovered)
        if isinstance(hash_outcome, HashFailure):
            return AnalysisFailure(
                file_id=discovered.id,
                path=discovered.path,
                reason_code=hash_outcome.issue.issue_type.value,
            )
        self._store.record_hash_success(hash_outcome)

        classification = FileClassifier(clock=self._clock).classify(hash_outcome.hashed)
        self._store.record_event(classification_event(classification))

        proposal = ProposalEngine(clock=self._clock).propose(classification)
        self._store.record_event(proposal_event(proposal))

        policy_decision = PolicyEngine(clock=self._clock).evaluate(proposal)
        self._store.record_event(policy_decision_event(policy_decision))

        return AnalyzedItem(
            file_id=discovered.id,
            path=discovered.path,
            filename=discovered.filename,
            category=classification.category,
            proposed_destination_category=proposal.proposed_destination_category,
            proposal_id=proposal.id,
            policy_decision_id=policy_decision.id,
            policy_outcome=policy_decision.decision,
            requires_review=policy_decision.decision is PolicyOutcome.REVIEW,
            confidence=proposal.confidence,
            reason=policy_decision.reasons[0] if policy_decision.reasons else "",
        )

    # --- Human review --------------------------------------------------------

    def approve_review(
        self, policy_decision_id: UUID, *, note: str | None = None
    ) -> ReviewActionResult:
        return self._record_review(policy_decision_id, HumanReviewOutcome.APPROVE, note)

    def skip_review(
        self, policy_decision_id: UUID, *, note: str | None = None
    ) -> ReviewActionResult:
        return self._record_review(policy_decision_id, HumanReviewOutcome.SKIP, note)

    def _record_review(
        self, policy_decision_id: UUID, outcome: HumanReviewOutcome, note: str | None
    ) -> ReviewActionResult:
        with self._review_lock:
            policy_decision = queries.find_policy_decision(
                self._store, policy_decision_id
            )
            if isinstance(policy_decision, queries.LookupFailure):
                code, detail = _not_found_or_malformed(
                    policy_decision,
                    ApplicationRejectionReason.POLICY_DECISION_NOT_FOUND,
                )
                return ReviewActionResult(
                    policy_decision_id, ApplicationOutcomeStatus.REJECTED, code, detail
                )

            proposal = queries.find_proposal(self._store, policy_decision.proposal_id)
            if isinstance(proposal, queries.LookupFailure):
                code, detail = _not_found_or_malformed(
                    proposal, ApplicationRejectionReason.PROPOSAL_NOT_FOUND
                )
                return ReviewActionResult(
                    policy_decision_id, ApplicationOutcomeStatus.REJECTED, code, detail
                )

            existing = queries.find_effective_human_review(
                self._store, policy_decision_id
            )
            if isinstance(existing, queries.LookupFailure):
                return ReviewActionResult(
                    policy_decision_id,
                    ApplicationOutcomeStatus.REJECTED,
                    ApplicationRejectionReason.AMBIGUOUS_REVIEW_HISTORY.value,
                    existing.detail,
                )
            if existing is not None:
                return ReviewActionResult(
                    policy_decision_id,
                    ApplicationOutcomeStatus.REJECTED,
                    ApplicationRejectionReason.ALREADY_REVIEWED.value,
                    f"policy_decision_id={policy_decision_id} already has an effective review",
                )

            try:
                review = HumanReviewEngine(clock=self._clock).record(
                    policy_decision, proposal, outcome, note=note
                )
            except InvalidHumanReviewError as exc:
                return ReviewActionResult(
                    policy_decision_id,
                    ApplicationOutcomeStatus.REJECTED,
                    ApplicationRejectionReason.NOT_ELIGIBLE_FOR_REVIEW.value,
                    str(exc),
                )

            self._store.record_event(human_review_recorded_event(review))
            return ReviewActionResult(
                policy_decision_id, ApplicationOutcomeStatus.SUCCEEDED, None, None
            )

    # --- Apply -----------------------------------------------------------------

    def apply_item(self, policy_decision_id: UUID) -> ApplyResult:
        return self._apply_one(policy_decision_id, batch_id=None).to_apply_result()

    def _resolve_managed_root_id_for_policy_decision(
        self, policy_decision_id: UUID
    ) -> UUID | None:
        """Best-effort lineage resolution for Mixed-root detection only --
        None if any step fails to resolve; never raises. Deliberately a
        strict subset of _apply_one's own resolution (policy_decision ->
        proposal -> discovered_file.managed_root_id only -- no destination
        resolution, no ExecutionAuthorization, no TransactionEngine call),
        so this costs only three cheap point-lookups, not the expensive
        parts of a real apply."""
        policy_decision = queries.find_policy_decision(self._store, policy_decision_id)
        if isinstance(policy_decision, queries.LookupFailure):
            return None
        proposal = queries.find_proposal(self._store, policy_decision.proposal_id)
        if isinstance(proposal, queries.LookupFailure):
            return None
        discovered = self._store.get_discovered_file(policy_decision.file_id)
        if discovered is None:
            return None
        return discovered.managed_root_id

    def apply_items(
        self, policy_decision_ids: Sequence[UUID]
    ) -> BatchApplyResult | ManagedRootUnavailable:
        """Batch intent is NOT batch authorization: every id below walks the
        exact same trusted per-item path _apply_one already walks for
        apply_item -- this method only orchestrates that path N times, in
        caller order, with best-effort/per-item atomicity (a normal business
        rejection continues the batch; only an unreliable audit trail stops
        it early). See the FA-014 design doc §5/§9/§10 for the full
        rationale this sequencing implements verbatim.

        FA-015: one batch = one Managed Root. A lightweight pre-pass
        resolves each selected id's managed_root_id far enough to detect a
        Mixed-root selection (raises MixedManagedRootsError -- a structural,
        cross-item consistency problem, before any I/O beyond the pre-pass
        itself) and to identify the single shared root, whose current
        liveness is then verified ONCE, structurally, before
        BATCH_APPLY_STARTED is ever written (the audit-noise-avoiding
        "layer 1" gate -- _apply_one's own per-item "layer 2" re-check
        remains the actual, unconditionally load-bearing enforcement, since
        apply_item bypasses this gate entirely)."""
        frozen = tuple(policy_decision_ids)
        if not frozen:
            raise EmptyBatchSelectionError
        reject_duplicate_policy_decision_ids(frozen)

        roots_seen: set[UUID] = set()
        for policy_decision_id in frozen:
            root_id = self._resolve_managed_root_id_for_policy_decision(
                policy_decision_id
            )
            if root_id is not None:
                roots_seen.add(root_id)
        if len(roots_seen) > 1:
            raise MixedManagedRootsError(frozen, roots_seen)
        shared_managed_root_id = next(iter(roots_seen), None)

        if shared_managed_root_id is not None:
            root_outcome = self._resolve_active_managed_root(shared_managed_root_id)
            if isinstance(root_outcome, ManagedRootUnavailable):
                return root_outcome
        # else: every id failed lineage resolution entirely -- proceed with
        # managed_root_id=None; each item will independently fail inside
        # _apply_one (its own NOT_FOUND/MALFORMED lookups), exactly mirroring
        # create_organization_plan's identical zero-resolvable-ids handling.

        batch_id = uuid4()
        started_at = self._clock()
        # If this itself raises, it propagates unwrapped -- zero mutation has
        # happened yet, exactly like apply_item's own REQUESTED-persist-
        # failure rule.
        self._store.record_event(
            history.batch_apply_started_event(
                batch_id, frozen, started_at, shared_managed_root_id
            )
        )

        items: list[BatchApplyItemResult] = []
        for input_index, policy_decision_id in enumerate(frozen):
            try:
                outcome = self._apply_one(policy_decision_id, batch_id=batch_id)
            except TerminalPersistenceError as exc:
                # Real mutation happened, but its own authoritative terminal
                # event did not persist -- do NOT persist BATCH_ITEM_RECORDED
                # for it (durable history must not manufacture certainty the
                # audit trail doesn't have). This call's own in-process
                # result still reports the real outcome via exc.result.
                # _apply_one only ever raises TerminalPersistenceError
                # carrying an ApplyResult (never UndoResult/RestoreResult --
                # those belong to undo_transaction/restore_capture).
                assert isinstance(exc.result, ApplyResult)
                items.append(
                    _batch_item_result_from_apply_result(input_index, exc.result)
                )
                return self._incomplete_batch_result(
                    batch_id, started_at, frozen, items, shared_managed_root_id
                )
            except (DatabaseUnavailableError, IntegrityConstraintError):
                # _apply_one's own pre-mutation persist failed -- nothing
                # happened for this id, no BatchApplyItemResult to append.
                return self._incomplete_batch_result(
                    batch_id, started_at, frozen, items, shared_managed_root_id
                )

            # outcome's authoritative facts are already durably persisted by
            # _apply_one itself -- durably trustworthy independent of
            # whether the checkpoint below succeeds.
            item_result = _batch_item_result_from_outcome(input_index, outcome)

            try:
                self._store.record_event(
                    history.batch_item_recorded_event(
                        batch_id, item_result, self._clock()
                    )
                )
            except (DatabaseUnavailableError, IntegrityConstraintError):
                # _apply_one completed normally and item_result is genuinely
                # known in-process -- only the durable checkpoint failed.
                # This call's own result still includes it; durable history
                # will not have this checkpoint. Stop -- no further ids.
                items.append(item_result)
                return self._incomplete_batch_result(
                    batch_id, started_at, frozen, items, shared_managed_root_id
                )

            items.append(item_result)
            # Normal business REJECTED/SUCCEEDED/FAILED, checkpoint durably
            # recorded -> continue to the next id (best-effort atomicity).

        completed_at = self._clock()
        summary = _summarize_batch_items(frozen, items)
        try:
            self._store.record_event(
                history.batch_apply_completed_event(batch_id, completed_at, summary)
            )
        except (DatabaseUnavailableError, IntegrityConstraintError):
            # Every item checkpoint already durably recorded; only the final
            # terminal marker failed to persist.
            return self._incomplete_batch_result(
                batch_id, started_at, frozen, items, shared_managed_root_id
            )

        return BatchApplyResult(
            batch_id=batch_id,
            status=BatchStatus.COMPLETED,
            started_at=started_at,
            completed_at=completed_at,
            requested_policy_decision_ids=frozen,
            items=tuple(items),
            summary=summary,
            managed_root_id=shared_managed_root_id,
        )

    def _incomplete_batch_result(
        self,
        batch_id: UUID,
        started_at: datetime,
        requested_policy_decision_ids: tuple[UUID, ...],
        items: list[BatchApplyItemResult],
        managed_root_id: UUID | None,
    ) -> BatchApplyResult:
        return BatchApplyResult(
            batch_id=batch_id,
            status=BatchStatus.INCOMPLETE,
            started_at=started_at,
            completed_at=None,
            requested_policy_decision_ids=requested_policy_decision_ids,
            items=tuple(items),
            summary=_summarize_batch_items(requested_policy_decision_ids, items),
            managed_root_id=managed_root_id,
        )

    def get_batch_history(
        self, batch_id: UUID, *, include_items: bool = False
    ) -> BatchHistoryEntry | queries.LookupFailure:
        return history.get_batch_history(
            self._store, batch_id, include_items=include_items
        )

    def list_recent_batch_history(
        self, *, limit: int = 20
    ) -> tuple[BatchHistoryEntry | UnavailableBatchHistoryRow, ...]:
        return history.list_recent_batch_history(self._store, limit=limit)

    def _apply_one(
        self, policy_decision_id: UUID, *, batch_id: UUID | None
    ) -> "_ApplyOutcome":
        policy_decision = queries.find_policy_decision(self._store, policy_decision_id)
        if isinstance(policy_decision, queries.LookupFailure):
            code, detail = _not_found_or_malformed(
                policy_decision, ApplicationRejectionReason.POLICY_DECISION_NOT_FOUND
            )
            return _ApplyOutcome(
                policy_decision_id,
                None,
                None,
                None,
                ApplicationOutcomeStatus.REJECTED,
                None,
                None,
                None,
                code,
                detail,
                True,
            )

        proposal = queries.find_proposal(self._store, policy_decision.proposal_id)
        if isinstance(proposal, queries.LookupFailure):
            code, detail = _not_found_or_malformed(
                proposal, ApplicationRejectionReason.PROPOSAL_NOT_FOUND
            )
            return _ApplyOutcome(
                policy_decision_id,
                None,
                policy_decision.file_id,
                None,
                ApplicationOutcomeStatus.REJECTED,
                None,
                None,
                None,
                code,
                detail,
                True,
            )

        if policy_decision.decision is PolicyOutcome.BLOCK:
            return _ApplyOutcome(
                policy_decision_id,
                proposal.id,
                policy_decision.file_id,
                None,
                ApplicationOutcomeStatus.REJECTED,
                None,
                None,
                None,
                ApplicationRejectionReason.POLICY_BLOCK.value,
                "BLOCK cannot be overridden",
                True,
            )

        if policy_decision.decision is PolicyOutcome.AUTO:
            authorization = ExecutionAuthorization.from_policy_auto(policy_decision)
        else:
            # policy_decision.decision is REVIEW (BLOCK already returned above)
            review = queries.find_effective_human_review(
                self._store, policy_decision_id
            )
            if isinstance(review, queries.LookupFailure):
                return _ApplyOutcome(
                    policy_decision_id,
                    proposal.id,
                    policy_decision.file_id,
                    None,
                    ApplicationOutcomeStatus.REJECTED,
                    None,
                    None,
                    None,
                    ApplicationRejectionReason.AMBIGUOUS_REVIEW_HISTORY.value,
                    review.detail,
                    True,
                )
            if review is None:
                return _ApplyOutcome(
                    policy_decision_id,
                    proposal.id,
                    policy_decision.file_id,
                    None,
                    ApplicationOutcomeStatus.REJECTED,
                    None,
                    None,
                    None,
                    ApplicationRejectionReason.POLICY_REVIEW_WITHOUT_APPROVAL.value,
                    "no effective review recorded for this policy decision",
                    True,
                )
            if review.outcome is HumanReviewOutcome.SKIP:
                return _ApplyOutcome(
                    policy_decision_id,
                    proposal.id,
                    policy_decision.file_id,
                    None,
                    ApplicationOutcomeStatus.REJECTED,
                    None,
                    None,
                    None,
                    ApplicationRejectionReason.REVIEW_OUTCOME_IS_SKIP.value,
                    "effective review outcome is SKIP",
                    True,
                )
            # outcome is APPROVE -> authorized. This is a SEPARATE
            # authorization fact layered on top of the persisted
            # PolicyDecision, never a rewrite of it -- the persisted
            # PolicyDecision keeps decision=REVIEW forever. from_human_approval
            # independently reverifies the genuine, persisted REVIEW decision
            # and APPROVE review before constructing this authorization --
            # this method (not ExecutionAuthorization itself) is where that
            # persisted-authenticity check actually happens; see
            # file_agent.domain.authorization's module docstring for the
            # full trust-boundary statement.
            authorization = ExecutionAuthorization.from_human_approval(
                policy_decision, review
            )

        discovered = self._store.get_discovered_file(policy_decision.file_id)
        if discovered is None:
            return _ApplyOutcome(
                policy_decision_id,
                proposal.id,
                policy_decision.file_id,
                None,
                ApplicationOutcomeStatus.REJECTED,
                None,
                None,
                None,
                ApplicationRejectionReason.DISCOVERED_FILE_NOT_FOUND.value,
                f"no DiscoveredFile with id={policy_decision.file_id}",
                True,
            )

        # FA-015 layer 2 (round-1/round-4 design): the actual,
        # unconditionally load-bearing active-root check -- apply_item is
        # still-public and bypasses apply_items' own structural gate
        # entirely, so this re-check must live here to be load-bearing at
        # all. Re-derives full live safety fresh via
        # managed_roots._resolve_safe_managed_root every single call --
        # never assumes a root that was safe a moment ago still is.
        if discovered.managed_root_id is None:
            return _ApplyOutcome(
                policy_decision_id,
                proposal.id,
                discovered.id,
                discovered.filename,
                ApplicationOutcomeStatus.REJECTED,
                None,
                discovered.path,
                None,
                ApplicationRejectionReason.MANAGED_ROOT_NOT_ACTIVE.value,
                "file has no managed root lineage (pre-FA-015 legacy data)",
                True,
            )
        root_outcome = self._resolve_active_managed_root(discovered.managed_root_id)
        if isinstance(root_outcome, ManagedRootUnavailable):
            return _ApplyOutcome(
                policy_decision_id,
                proposal.id,
                discovered.id,
                discovered.filename,
                ApplicationOutcomeStatus.REJECTED,
                None,
                discovered.path,
                None,
                ApplicationRejectionReason.MANAGED_ROOT_NOT_ACTIVE.value,
                root_outcome.detail,
                True,
            )
        sandbox_root = root_outcome

        # FA-016 source live structural check -- the actual, unconditionally
        # load-bearing check for source-side structural safety, exactly
        # mirroring FA-015 layer 2's rationale above: apply_item bypasses
        # any batch-level gate entirely, so this must be re-derived fresh
        # here to be load-bearing at all. inspect_candidate_reference=True:
        # discovered.path is an existing source object -- verified itself,
        # not just its ancestors, before anything downstream proceeds.
        source_structural_outcome = structural_safety.find_structural_protection(
            discovered.path, sandbox_root.path, inspect_candidate_reference=True
        )
        if source_structural_outcome is not None:
            return _ApplyOutcome(
                policy_decision_id,
                proposal.id,
                discovered.id,
                discovered.filename,
                ApplicationOutcomeStatus.REJECTED,
                None,
                discovered.path,
                None,
                ApplicationRejectionReason.STRUCTURALLY_PROTECTED.value,
                _structural_detail(source_structural_outcome),
                True,
            )

        assert proposal.proposed_destination_category is not None, (
            "AUTO and REVIEW+APPROVE both structurally guarantee a proposed "
            "destination -- PolicyEngine never produces AUTO without one, "
            "and HumanReviewEngine.record() refuses APPROVE without one"
        )

        destination_path = resolve_destination(
            sandbox_root,
            proposal.proposed_destination_category,
            discovered.filename,
        )

        # FA-016 destination live structural check -- symmetric with the
        # source check above: a file must never be moved INTO a destination
        # that is itself structurally protected, re-derived fresh on every
        # call, independent of whatever a prior preview found.
        # inspect_candidate_reference=False: destination_path normally does
        # not exist yet -- only its ancestor chain (from .parent up to
        # sandbox_root.path) is inspected; its own nonexistence is never
        # itself a failure. An existing-but-unsafe destination leaf remains
        # TransactionEngine's own, separate, unmodified responsibility.
        destination_structural_outcome = structural_safety.find_structural_protection(
            destination_path, sandbox_root.path, inspect_candidate_reference=False
        )
        if destination_structural_outcome is not None:
            return _ApplyOutcome(
                policy_decision_id,
                proposal.id,
                discovered.id,
                discovered.filename,
                ApplicationOutcomeStatus.REJECTED,
                None,
                discovered.path,
                destination_path,
                ApplicationRejectionReason.STRUCTURALLY_PROTECTED.value,
                _structural_detail(destination_structural_outcome),
                True,
            )

        request = TransactionRequest(
            file_id=discovered.id,
            proposal_id=proposal.id,
            policy_decision_id=policy_decision.id,
            source_path=discovered.path,
            destination_path=destination_path,
            destination_category=proposal.proposed_destination_category,
            # Identity fields come from THIS proposal's own frozen snapshot,
            # never from the shared, mutable DiscoveredFile row -- this is
            # what binds the request unambiguously to the exact analysis
            # generation policy_decision was evaluated against.
            # TransactionEngine's own FileHasher-based reverification remains
            # defense-in-depth against a live filesystem change since that
            # snapshot was taken; it does not substitute for having the
            # historically-correct snapshot in the first place.
            expected_size=proposal.expected_size,
            expected_created_at=proposal.expected_created_at,
            expected_modified_at=proposal.expected_modified_at,
            expected_sha256=proposal.sha256,
            # Pure correlation metadata (None for a direct apply_item call) --
            # never read by any precondition/authorization check in this
            # engine; see TransactionRequest.batch_id's own docstring.
            batch_id=batch_id,
        )

        engine = TransactionEngine(sandbox_root, clock=self._clock)
        outcome = engine.prepare(request, authorization)
        if isinstance(
            outcome, TransactionResult
        ):  # REJECTED -- prepare() never mutates
            self._store.record_event(transaction_result_event(outcome))
            return self._apply_outcome_from_transaction(
                policy_decision_id,
                proposal.id,
                discovered.id,
                discovered.filename,
                outcome,
                # prepare() structurally never mutates -- a static
                # architectural guarantee, not a per-instance observation,
                # so no live check is needed here (§Round-2 §11.1).
                source_unchanged_confirmed=True,
            )

        self._store.record_event(transaction_requested_event(request))  # checkpoint
        result = engine.commit(outcome)  # the mutation happens here
        # FAILED is the one status with no static unchanged-guarantee --
        # commit()'s own OSError catch performs no post-failure re-check
        # of its own, so this is the only place that positively verifies
        # (or honestly fails to verify) source identity for that case.
        # SUCCEEDED's value is never rendered (product-irrelevant) --
        # False is used as an inert filler, not a claim.
        source_unchanged_confirmed = (
            _verify_source_unchanged_after_failure(request, sandbox_root)
            if result.status is TransactionStatus.FAILED
            else False
        )
        apply_outcome = self._apply_outcome_from_transaction(
            policy_decision_id,
            proposal.id,
            discovered.id,
            discovered.filename,
            result,
            source_unchanged_confirmed=source_unchanged_confirmed,
        )
        try:
            self._store.record_event(transaction_result_event(result))  # terminal
        except (DatabaseUnavailableError, IntegrityConstraintError) as exc:
            raise TerminalPersistenceError(
                apply_outcome.to_apply_result(), exc
            ) from exc
        return apply_outcome

    def _apply_outcome_from_transaction(
        self,
        policy_decision_id: UUID,
        proposal_id: UUID,
        file_id: UUID,
        filename: str,
        result: TransactionResult,
        *,
        source_unchanged_confirmed: bool,
    ) -> "_ApplyOutcome":
        if result.status is TransactionStatus.SUCCEEDED:
            return _ApplyOutcome(
                policy_decision_id,
                proposal_id,
                file_id,
                filename,
                ApplicationOutcomeStatus.SUCCEEDED,
                result.request_id,
                result.source_path,
                result.destination_path,
                None,
                None,
                source_unchanged_confirmed,
            )
        if result.status is TransactionStatus.REJECTED:
            return _ApplyOutcome(
                policy_decision_id,
                proposal_id,
                file_id,
                filename,
                ApplicationOutcomeStatus.REJECTED,
                result.request_id,
                result.source_path,
                # FA-017.3 fix: TransactionResult.destination_path is
                # always populated, even for REJECTED (it's a required
                # field on the domain model) -- previously discarded here
                # even though the backend had already resolved it.
                result.destination_path,
                result.rejection_code.value
                if result.rejection_code is not None
                else None,
                result.failure_reason,
                source_unchanged_confirmed,
            )
        return _ApplyOutcome(
            policy_decision_id,
            proposal_id,
            file_id,
            filename,
            ApplicationOutcomeStatus.FAILED,
            result.request_id,
            result.source_path,
            None,
            None,
            result.failure_reason,
            source_unchanged_confirmed,
        )

    # --- Undo --------------------------------------------------------------------

    def undo_transaction(self, transaction_id: UUID) -> UndoResult:
        lookup = queries.find_transaction_result(self._store, transaction_id)
        if isinstance(lookup, queries.LookupFailure):
            return UndoResult(
                transaction_id,
                None,
                ApplicationOutcomeStatus.REJECTED,
                None,
                _transaction_lookup_reason(lookup.status).value,
                lookup.detail,
            )

        if lookup.status is not TransactionStatus.SUCCEEDED:
            return UndoResult(
                transaction_id,
                None,
                ApplicationOutcomeStatus.REJECTED,
                None,
                ApplicationRejectionReason.ORIGINAL_TRANSACTION_NOT_SUCCEEDED.value,
                f"original transaction status={lookup.status.value}",
            )

        # FA-015: undo is historically-authorized recovery, independent of
        # CURRENT root registration status (RecoveryEngine's own live
        # re-verification remains the actual safety boundary) -- but a live,
        # safe root must still be resolvable to construct RecoveryEngine at
        # all. Fails closed, never crashes on legacy managed_root_id=None
        # data, never infers a root from current filesystem/path state.
        sandbox_root = self._resolve_historical_root(lookup.file_id)
        if sandbox_root is None:
            return UndoResult(
                transaction_id,
                None,
                ApplicationOutcomeStatus.REJECTED,
                None,
                ApplicationRejectionReason.HISTORICAL_ROOT_UNAVAILABLE.value,
                "no resolvable historical root for this transaction's file",
            )

        evidence = CompletedMoveEvidence.from_transaction_result(
            lookup
        )  # internal-only construction

        try:
            st = lookup.destination_path.stat()  # fresh, right now
        except OSError:
            # Short-circuit: ReverseMoveRequest's expected_* fields have no
            # sensible value if the file isn't there at all -- NOT a bypass
            # of RecoveryEngine's own reverification, which still runs for
            # every case where the file DOES exist but has since changed.
            return UndoResult(
                transaction_id,
                None,
                ApplicationOutcomeStatus.REJECTED,
                None,
                RecoveryRejectionCode.CURRENT_FILE_MISSING.value,
                "destination file is missing",
            )

        request = ReverseMoveRequest(
            evidence=evidence,
            expected_size=st.st_size,
            expected_created_at=datetime.fromtimestamp(st.st_ctime, tz=UTC),
            expected_modified_at=datetime.fromtimestamp(st.st_mtime, tz=UTC),
        )

        engine = RecoveryEngine(sandbox_root, self._app_paths, clock=self._clock)
        outcome = engine.prepare(request)
        if isinstance(outcome, RecoveryResult):
            self._store.record_event(recovery_result_event(outcome))
            return self._undo_result_from_recovery(transaction_id, outcome)

        self._store.record_event(recovery_requested_event(request))  # checkpoint
        result = engine.commit(outcome)  # the mutation happens here
        undo_result = self._undo_result_from_recovery(transaction_id, result)
        try:
            self._store.record_event(recovery_result_event(result))  # terminal
        except (DatabaseUnavailableError, IntegrityConstraintError) as exc:
            raise TerminalPersistenceError(undo_result, exc) from exc
        return undo_result

    def _undo_result_from_recovery(
        self, transaction_id: UUID, result: RecoveryResult
    ) -> UndoResult:
        if result.status is RecoveryStatus.SUCCEEDED:
            return UndoResult(
                transaction_id,
                result.request_id,
                ApplicationOutcomeStatus.SUCCEEDED,
                result.destination_path,
                None,
                None,
            )
        if result.status is RecoveryStatus.REJECTED:
            return UndoResult(
                transaction_id,
                result.request_id,
                ApplicationOutcomeStatus.REJECTED,
                None,
                result.rejection_code.value
                if result.rejection_code is not None
                else None,
                result.failure_reason,
            )
        return UndoResult(
            transaction_id,
            result.request_id,
            ApplicationOutcomeStatus.FAILED,
            None,
            None,
            result.failure_reason,
        )

    # --- Restore ---------------------------------------------------------------

    def restore_capture(self, capture_id: UUID) -> RestoreResult:
        lookup = queries.find_capture_result(self._store, capture_id)
        if isinstance(lookup, queries.LookupFailure):
            return RestoreResult(
                capture_id,
                None,
                ApplicationOutcomeStatus.REJECTED,
                None,
                _capture_lookup_reason(lookup.status).value,
                lookup.detail,
            )

        if lookup.status not in (
            VaultCaptureStatus.CAPTURED,
            VaultCaptureStatus.ALREADY_PRESENT,
        ):
            return RestoreResult(
                capture_id,
                None,
                ApplicationOutcomeStatus.REJECTED,
                None,
                ApplicationRejectionReason.CAPTURE_NOT_SUCCESSFUL.value,
                f"capture status={lookup.status.value}",
            )

        # FA-015: restore is historically-authorized recovery, independent
        # of CURRENT root registration status -- same reasoning and
        # mechanism as undo_transaction (see there for the full rationale).
        sandbox_root = self._resolve_historical_root(lookup.file_id)
        if sandbox_root is None:
            return RestoreResult(
                capture_id,
                None,
                ApplicationOutcomeStatus.REJECTED,
                None,
                ApplicationRejectionReason.HISTORICAL_ROOT_UNAVAILABLE.value,
                "no resolvable historical root for this file",
            )

        evidence = VaultCaptureEvidence.from_capture_result(
            lookup
        )  # internal-only construction
        request = RestoreFromVaultRequest(evidence=evidence)
        # No fresh-stat step needed here -- unlike ReverseMoveRequest, this
        # model has no live-file metadata fields at all. "Restore target
        # derives only from the original captured source_path" is already
        # structurally guaranteed by evidence.source_path -- no independent
        # field exists here to override it.

        engine = RecoveryEngine(sandbox_root, self._app_paths, clock=self._clock)
        outcome = engine.prepare(request)
        if isinstance(outcome, RecoveryResult):
            self._store.record_event(recovery_result_event(outcome))
            return self._restore_result_from_recovery(capture_id, outcome)

        self._store.record_event(recovery_requested_event(request))  # checkpoint
        result = engine.commit(outcome)  # the mutation happens here
        restore_result = self._restore_result_from_recovery(capture_id, result)
        try:
            self._store.record_event(recovery_result_event(result))  # terminal
        except (DatabaseUnavailableError, IntegrityConstraintError) as exc:
            raise TerminalPersistenceError(restore_result, exc) from exc
        return restore_result

    def _restore_result_from_recovery(
        self, capture_id: UUID, result: RecoveryResult
    ) -> RestoreResult:
        if result.status is RecoveryStatus.SUCCEEDED:
            return RestoreResult(
                capture_id,
                result.request_id,
                ApplicationOutcomeStatus.SUCCEEDED,
                result.destination_path,
                None,
                None,
            )
        if result.status is RecoveryStatus.REJECTED:
            return RestoreResult(
                capture_id,
                result.request_id,
                ApplicationOutcomeStatus.REJECTED,
                None,
                result.rejection_code.value
                if result.rejection_code is not None
                else None,
                result.failure_reason,
            )
        return RestoreResult(
            capture_id,
            result.request_id,
            ApplicationOutcomeStatus.FAILED,
            None,
            None,
            result.failure_reason,
        )

    # --- Organization plan (preview) ----------------------------------------

    def create_organization_plan(
        self, policy_decision_ids: Sequence[UUID]
    ) -> OrganizationPlan | ManagedRootUnavailable:
        """Read-only preview: never mutates, never records a review, never
        constructs an ExecutionAuthorization, never calls TransactionEngine/
        RecoveryEngine. See application/planner.py::build_organization_plan
        and application/organization_plan.py for the full contract. Preview
        is not authorization -- TransactionEngine independently reverifies
        live state before any mutation apply_item performs.

        FA-015: one plan = one Managed Root, resolved from the input ids'
        own lineage -- never a caller-supplied root. Raises
        MixedManagedRootsError if the ids disagree on root; returns
        ManagedRootUnavailable if the single agreed root is not currently
        active/live-safe."""
        return build_organization_plan(
            self._store, self._app_paths, policy_decision_ids, clock=self._clock
        )

    # --- Destination setup (FA-017.2) -----------------------------------------

    def prepare_destinations(
        self,
        managed_root_id: UUID,
        destination_categories: Sequence[DestinationCategory],
    ) -> DestinationSetupResult | ManagedRootUnavailable:
        """DESTINATION NEED != DIRECTORY CREATION AUTHORIZATION. A category
        the caller requests is never trusted on its own -- current
        organization need is reconstructed fresh, internally, via the exact
        same analyze_managed_root/create_organization_plan machinery
        analysis.run/plan.create already use (never exposed to the caller
        as a new plan), and only a requested category that is ALSO in that
        fresh result's missing_destination_categories() proceeds to any
        filesystem interaction at all. A category outside current need is
        rejected with zero find_structural_protection/inspect_leaf/mkdir
        calls -- not merely a rejection, a complete absence of filesystem
        probing for that category.

        Correctness over efficiency: this pays for a second, internal
        analysis pass (on top of whatever led the user to attempt this),
        deliberately, rather than trusting any client-supplied or
        previously-computed fact about what's currently missing."""
        root_outcome = self._resolve_active_managed_root(managed_root_id)
        if isinstance(root_outcome, ManagedRootUnavailable):
            return root_outcome
        sandbox_root = root_outcome

        analysis_outcome = self.analyze_managed_root(managed_root_id)
        if isinstance(analysis_outcome, ManagedRootUnavailable):
            return analysis_outcome
        fresh_plan_outcome = self.create_organization_plan(
            [item.policy_decision_id for item in analysis_outcome.items]
        )
        if isinstance(fresh_plan_outcome, ManagedRootUnavailable):
            return fresh_plan_outcome
        fresh_plan = fresh_plan_outcome

        required_categories = missing_destination_categories(fresh_plan.items)

        deduped: list[DestinationCategory] = []
        seen: set[DestinationCategory] = set()
        for category in destination_categories:
            if category not in seen:
                seen.add(category)
                deduped.append(category)

        setup_id = uuid4()
        started_at = self._clock()
        # If this itself raises, it propagates unwrapped -- zero mutation
        # has happened yet, exactly like apply_items' own STARTED-persist-
        # failure rule (the wire protocol's own unconditional `started`
        # frame, already sent by this point, is a separate mechanism from
        # this audit event; the worker loop's existing generic exception
        # handling renders this a normal kind="fatal" terminal frame, never
        # a crash, never unknown_mutation_outcome).
        self._store.record_event(
            destination_setup_started_event(
                setup_id, managed_root_id, tuple(deduped), started_at
            )
        )

        outcomes: list[DestinationPreparationOutcome] = []
        for category in deduped:
            if category in required_categories:
                outcome = self._prepare_one_destination(sandbox_root, category)
            else:
                outcome = DestinationPreparationOutcome(
                    category,
                    DestinationPreparationStatus.NOT_PREPARED,
                    DestinationSetupReasonCode.NOT_CURRENTLY_REQUIRED,
                )
            outcomes.append(outcome)
            try:
                self._store.record_event(
                    destination_setup_item_result_event(
                        setup_id, outcome, self._clock()
                    )
                )
            except (DatabaseUnavailableError, IntegrityConstraintError):
                # The real filesystem outcome (if any mutation happened) is
                # already captured, truthfully, in `outcome` above -- only
                # the durable audit checkpoint failed. Never reinterpreted
                # as a failed/unknown outcome; the batch continues to the
                # next requested category (best-effort, no rollback,
                # matching §10's batch semantics).
                pass

        try:
            self._store.record_event(
                destination_setup_completed_event(setup_id, self._clock())
            )
        except (DatabaseUnavailableError, IntegrityConstraintError):
            # Every per-category outcome is already captured in `outcomes`
            # above -- only the batch-level completion marker failed to
            # persist. No effect on the returned result.
            pass

        return DestinationSetupResult(
            setup_id=setup_id,
            managed_root_id=managed_root_id,
            outcomes=tuple(outcomes),
        )

    def _prepare_one_destination(
        self, sandbox_root: SandboxRoot, category: DestinationCategory
    ) -> DestinationPreparationOutcome:
        """Runs only for a category already proven currently-required by
        prepare_destinations. Every check here is re-derived fresh, live --
        never trusts the fresh_plan rebuild above for anything beyond
        "this category is currently needed"; structural safety in
        particular is independently re-verified, exactly mirroring
        _apply_one's own "re-derive fresh, never trust a prior finding"
        discipline for the destination side of a real move."""
        parent_path = resolve_destination_directory(sandbox_root, category)

        structural_outcome = structural_safety.find_structural_protection(
            parent_path, sandbox_root.path, inspect_candidate_reference=False
        )
        if structural_outcome is not None:
            return DestinationPreparationOutcome(
                category,
                DestinationPreparationStatus.NOT_PREPARED,
                DestinationSetupReasonCode.STRUCTURALLY_PROTECTED,
            )

        leaf_state = structural_safety.inspect_leaf(parent_path)
        if leaf_state is not structural_safety.LeafState.ABSENT:
            return _outcome_for_leaf_state(category, leaf_state)

        try:
            prepare_destination_directory(parent_path)
        except FileExistsError:
            # TOCTOU: something appeared between the pre-check above and
            # this call. A FRESH inspect_leaf() call decides the outcome --
            # FileExistsError alone is never, by itself, evidence of
            # ALREADY_AVAILABLE. mkdir is never attempted a second time for
            # this category, under any circumstance.
            fresh_state = structural_safety.inspect_leaf(parent_path)
            if fresh_state is structural_safety.LeafState.ABSENT:
                # Raced away a second time -- a pathological, extremely
                # narrow window. Fail closed rather than retry.
                return DestinationPreparationOutcome(
                    category,
                    DestinationPreparationStatus.NOT_PREPARED,
                    DestinationSetupReasonCode.OBSERVATION_FAILED,
                )
            return _outcome_for_leaf_state(category, fresh_state)
        except OSError:
            return DestinationPreparationOutcome(
                category,
                DestinationPreparationStatus.NOT_PREPARED,
                DestinationSetupReasonCode.OBSERVATION_FAILED,
            )

        return DestinationPreparationOutcome(
            category, DestinationPreparationStatus.PREPARED, None
        )
