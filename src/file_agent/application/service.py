"""FileAgentApplicationService -- the sole product-facing orchestration
boundary between UI/CLI and every engine below it. See package __init__.py
for the trust-boundary contract.
"""

import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import UUID
from weakref import WeakKeyDictionary

from file_agent.application import queries
from file_agent.application.dto import (
    AnalysisFailure,
    AnalyzedItem,
    AnalyzedScanResult,
    ApplicationOutcomeStatus,
    ApplicationRejectionReason,
    ApplyResult,
    RestoreResult,
    ReviewActionResult,
    UndoResult,
)
from file_agent.application.errors import TerminalPersistenceError
from file_agent.application.organization_plan import OrganizationPlan
from file_agent.application.planner import build_organization_plan
from file_agent.classifier import FileClassifier, classification_event
from file_agent.destination import resolve_destination
from file_agent.domain import (
    CompletedMoveEvidence,
    DiscoveredFile,
    ExecutionAuthorization,
    HumanReviewOutcome,
    PolicyOutcome,
    RecoveryRejectionCode,
    RecoveryResult,
    RecoveryStatus,
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


class FileAgentApplicationService:
    """Product-facing orchestration boundary. Every mutating method accepts
    only a stable, previously-persisted identifier -- never a path, hash,
    evidence object, prepared capability, or a caller-constructed
    TransactionRequest/HumanReviewDecision/PolicyDecision. See the package
    __init__.py docstring for the complete trust-boundary contract.

    v1 concurrency contract for approve_review/skip_review: same process,
    same FileAgentStore instance -> serialized, race-free (via a store-scoped
    lock, shared by every FileAgentApplicationService built against that
    store). Different processes -> not guaranteed; a resulting duplicate/
    conflicting review history is always detected and fails closed
    (AMBIGUOUS_REVIEW_HISTORY), never resolved by timestamp or UUID
    ordering.
    """

    def __init__(
        self,
        sandbox_root: SandboxRoot,
        app_paths: AppPaths,
        store: FileAgentStore,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._sandbox_root = sandbox_root
        self._app_paths = app_paths
        self._store = store
        self._clock = clock
        self._review_lock = _review_lock_for(store)

    # --- Analysis ----------------------------------------------------------

    def analyze_scan(self) -> AnalyzedScanResult:
        scan_result = DirectoryScanner(self._sandbox_root, clock=self._clock).run()
        self._store.record_scan(scan_result)

        items: list[AnalyzedItem] = []
        failures: list[AnalysisFailure] = []
        for discovered in scan_result.files:
            outcome = self._analyze_discovered(discovered)
            if isinstance(outcome, AnalysisFailure):
                failures.append(outcome)
            else:
                items.append(outcome)

        return AnalyzedScanResult(
            scan_id=scan_result.scan_run.id,
            items=tuple(items),
            failures=tuple(failures),
            files_discovered=len(scan_result.files),
        )

    def analyze_file(self, file_id: UUID) -> AnalyzedItem | AnalysisFailure:
        discovered = self._store.get_discovered_file(file_id)
        if discovered is None:
            return AnalysisFailure(
                file_id=file_id, path=None, reason_code="file_not_found"
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
        return self._analyze_discovered(fresh)

    def _analyze_discovered(
        self, discovered: DiscoveredFile
    ) -> AnalyzedItem | AnalysisFailure:
        hash_outcome = FileHasher(self._sandbox_root, clock=self._clock).hash_file(
            discovered
        )
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
        policy_decision = queries.find_policy_decision(self._store, policy_decision_id)
        if isinstance(policy_decision, queries.LookupFailure):
            code, detail = _not_found_or_malformed(
                policy_decision, ApplicationRejectionReason.POLICY_DECISION_NOT_FOUND
            )
            return ApplyResult(
                policy_decision_id,
                None,
                ApplicationOutcomeStatus.REJECTED,
                None,
                code,
                detail,
            )

        proposal = queries.find_proposal(self._store, policy_decision.proposal_id)
        if isinstance(proposal, queries.LookupFailure):
            code, detail = _not_found_or_malformed(
                proposal, ApplicationRejectionReason.PROPOSAL_NOT_FOUND
            )
            return ApplyResult(
                policy_decision_id,
                None,
                ApplicationOutcomeStatus.REJECTED,
                None,
                code,
                detail,
            )

        if policy_decision.decision is PolicyOutcome.BLOCK:
            return ApplyResult(
                policy_decision_id,
                None,
                ApplicationOutcomeStatus.REJECTED,
                None,
                ApplicationRejectionReason.POLICY_BLOCK.value,
                "BLOCK cannot be overridden",
            )

        if policy_decision.decision is PolicyOutcome.AUTO:
            authorization = ExecutionAuthorization.from_policy_auto(policy_decision)
        else:
            # policy_decision.decision is REVIEW (BLOCK already returned above)
            review = queries.find_effective_human_review(
                self._store, policy_decision_id
            )
            if isinstance(review, queries.LookupFailure):
                return ApplyResult(
                    policy_decision_id,
                    None,
                    ApplicationOutcomeStatus.REJECTED,
                    None,
                    ApplicationRejectionReason.AMBIGUOUS_REVIEW_HISTORY.value,
                    review.detail,
                )
            if review is None:
                return ApplyResult(
                    policy_decision_id,
                    None,
                    ApplicationOutcomeStatus.REJECTED,
                    None,
                    ApplicationRejectionReason.POLICY_REVIEW_WITHOUT_APPROVAL.value,
                    "no effective review recorded for this policy decision",
                )
            if review.outcome is HumanReviewOutcome.SKIP:
                return ApplyResult(
                    policy_decision_id,
                    None,
                    ApplicationOutcomeStatus.REJECTED,
                    None,
                    ApplicationRejectionReason.REVIEW_OUTCOME_IS_SKIP.value,
                    "effective review outcome is SKIP",
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
            return ApplyResult(
                policy_decision_id,
                None,
                ApplicationOutcomeStatus.REJECTED,
                None,
                ApplicationRejectionReason.DISCOVERED_FILE_NOT_FOUND.value,
                f"no DiscoveredFile with id={policy_decision.file_id}",
            )
        assert proposal.proposed_destination_category is not None, (
            "AUTO and REVIEW+APPROVE both structurally guarantee a proposed "
            "destination -- PolicyEngine never produces AUTO without one, "
            "and HumanReviewEngine.record() refuses APPROVE without one"
        )

        destination_path = resolve_destination(
            self._sandbox_root,
            proposal.proposed_destination_category,
            discovered.filename,
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
        )

        engine = TransactionEngine(self._sandbox_root, clock=self._clock)
        outcome = engine.prepare(request, authorization)
        if isinstance(
            outcome, TransactionResult
        ):  # REJECTED -- prepare() never mutates
            self._store.record_event(transaction_result_event(outcome))
            return self._apply_result_from_transaction(policy_decision_id, outcome)

        self._store.record_event(transaction_requested_event(request))  # checkpoint
        result = engine.commit(outcome)  # the mutation happens here
        apply_result = self._apply_result_from_transaction(policy_decision_id, result)
        try:
            self._store.record_event(transaction_result_event(result))  # terminal
        except (DatabaseUnavailableError, IntegrityConstraintError) as exc:
            raise TerminalPersistenceError(apply_result, exc) from exc
        return apply_result

    def _apply_result_from_transaction(
        self, policy_decision_id: UUID, result: TransactionResult
    ) -> ApplyResult:
        if result.status is TransactionStatus.SUCCEEDED:
            return ApplyResult(
                policy_decision_id,
                result.request_id,
                ApplicationOutcomeStatus.SUCCEEDED,
                result.destination_path,
                None,
                None,
            )
        if result.status is TransactionStatus.REJECTED:
            return ApplyResult(
                policy_decision_id,
                result.request_id,
                ApplicationOutcomeStatus.REJECTED,
                None,
                result.rejection_code.value
                if result.rejection_code is not None
                else None,
                result.failure_reason,
            )
        return ApplyResult(
            policy_decision_id,
            result.request_id,
            ApplicationOutcomeStatus.FAILED,
            None,
            None,
            result.failure_reason,
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

        engine = RecoveryEngine(self._sandbox_root, self._app_paths, clock=self._clock)
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

        evidence = VaultCaptureEvidence.from_capture_result(
            lookup
        )  # internal-only construction
        request = RestoreFromVaultRequest(evidence=evidence)
        # No fresh-stat step needed here -- unlike ReverseMoveRequest, this
        # model has no live-file metadata fields at all. "Restore target
        # derives only from the original captured source_path" is already
        # structurally guaranteed by evidence.source_path -- no independent
        # field exists here to override it.

        engine = RecoveryEngine(self._sandbox_root, self._app_paths, clock=self._clock)
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
    ) -> OrganizationPlan:
        """Read-only preview: never mutates, never records a review, never
        constructs an ExecutionAuthorization, never calls TransactionEngine/
        RecoveryEngine. See application/planner.py::build_organization_plan
        and application/organization_plan.py for the full contract. Preview
        is not authorization -- TransactionEngine independently reverifies
        live state before any mutation apply_item performs."""
        return build_organization_plan(
            self._store, self._sandbox_root, policy_decision_ids, clock=self._clock
        )
