"""OrganizationPlanner -- build_organization_plan(), the pure, read-only
assembly function behind FileAgentApplicationService.create_organization_plan.

Never mutates the filesystem, never imports managed_fs, never calls
TransactionEngine/RecoveryEngine, never builds ExecutionAuthorization, never
calls HumanReviewEngine.record. Zero engine calls -- the same "zero engine
calls, zero mutation" profile application/queries.py already has, just
producing a richer DTO. Reconstructs genuine persisted facts exclusively via
application/queries.py, and consumes (never re-derives) the shared,
read-only destination.inspect_destination -- the same function
TransactionEngine's own preconditions call -- so preview and execution-time
destination safety can never silently drift apart.

policy_decision_ids identifies the plan's lineage -- the exact analyzed set
requested -- never "latest scan"/"latest for this file_id". Each id is
resolved independently: policy_decision_id -> PolicyDecision.proposal_id ->
FileProposal. Every generation-sensitive OrganizationPlanItem field
(proposal_id, category, destination_category, policy_outcome,
human_review_outcome) comes from that exact policy_decision_id's own
lineage -- never from a "latest for this file_id" lookup, which does not
exist anywhere in this module.

The one lookup that IS keyed by file_id -- store.get_discovered_file(),
used for source_path/filename -- is safe despite being nominally "shared"
across generations: those two fields are read off FileObservationRow.path,
which is structurally immutable after a file's first scan (see the comment
at its call site in _build_item for the proof). Only FileObservationRow's
sha256 column is ever updated post-insert.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from file_agent.application import queries
from file_agent.application.dto import ApplicationRejectionReason
from file_agent.application.errors import DuplicatePolicyDecisionIdError
from file_agent.application.organization_plan import (
    OrganizationPlan,
    OrganizationPlanItem,
    OrganizationPlanSummary,
    PlanIssue,
    PlanReasonCode,
    PlanStatus,
)
from file_agent.destination import (
    DestinationConflict,
    inspect_destination,
    resolve_destination,
)
from file_agent.domain import HumanReviewOutcome, PolicyOutcome
from file_agent.persistence import FileAgentStore
from file_agent.scanner import SandboxRoot


def _utc_now() -> datetime:
    return datetime.now(UTC)


_DESTINATION_CONFLICT_REASON: dict[DestinationConflict, PlanReasonCode] = {
    DestinationConflict.OUTSIDE_SANDBOX: PlanReasonCode.DESTINATION_UNSAFE,
    DestinationConflict.UNSAFE_REPARSE_POINT: PlanReasonCode.DESTINATION_UNSAFE,
    DestinationConflict.BASENAME_MISMATCH: PlanReasonCode.DESTINATION_UNSAFE,
    DestinationConflict.PARENT_MISSING: PlanReasonCode.DESTINATION_PARENT_MISSING,
    DestinationConflict.ALREADY_OCCUPIED: PlanReasonCode.DESTINATION_OCCUPIED,
    DestinationConflict.OBSERVATION_FAILED: PlanReasonCode.FILESYSTEM_STATE_UNCERTAIN,
}


def build_organization_plan(
    store: FileAgentStore,
    sandbox_root: SandboxRoot,
    policy_decision_ids: Sequence[UUID],
    *,
    clock: Callable[[], datetime] = _utc_now,
) -> OrganizationPlan:
    """Sequence[UUID], not Iterable[UUID]: caller order is meaningful and
    preserved exactly. Frozen to a tuple immediately, then validated for
    duplicates BEFORE any persistence query or filesystem observation --
    duplicate ids are invalid caller input (DuplicatePolicyDecisionIdError),
    never silently deduplicated, never sorted, never represented as a
    PlanIssue."""
    frozen = tuple(policy_decision_ids)
    _reject_duplicates(frozen)

    items: list[OrganizationPlanItem] = []
    issues: list[PlanIssue] = []
    for policy_decision_id in frozen:
        outcome = _build_item(store, sandbox_root, policy_decision_id)
        if isinstance(outcome, PlanIssue):
            issues.append(outcome)
        else:
            items.append(outcome)

    return OrganizationPlan(
        id=uuid4(),
        created_at=clock(),
        root_path=sandbox_root.path,
        source_policy_decision_ids=frozen,
        items=tuple(items),
        issues=tuple(issues),
        summary=_summarize(items, issues),
    )


def _reject_duplicates(frozen: tuple[UUID, ...]) -> None:
    seen: set[UUID] = set()
    duplicates: list[UUID] = []
    for policy_decision_id in frozen:
        if policy_decision_id in seen:
            duplicates.append(policy_decision_id)
        seen.add(policy_decision_id)
    if duplicates:
        raise DuplicatePolicyDecisionIdError(tuple(duplicates))


def _issue_reason(
    failure: "queries.LookupFailure", not_found_reason: ApplicationRejectionReason
) -> tuple[str, str]:
    """find_policy_decision/find_proposal only ever return NOT_FOUND or
    MALFORMED -- mirrors service.py's own _not_found_or_malformed."""
    if failure.status is queries.LookupStatus.NOT_FOUND:
        return not_found_reason.value, failure.detail
    return ApplicationRejectionReason.MALFORMED_EVENT_PAYLOAD.value, failure.detail


def _build_item(
    store: FileAgentStore, sandbox_root: SandboxRoot, policy_decision_id: UUID
) -> OrganizationPlanItem | PlanIssue:
    policy_decision = queries.find_policy_decision(store, policy_decision_id)
    if isinstance(policy_decision, queries.LookupFailure):
        code, detail = _issue_reason(
            policy_decision, ApplicationRejectionReason.POLICY_DECISION_NOT_FOUND
        )
        return PlanIssue(policy_decision_id, code, detail)

    proposal = queries.find_proposal(store, policy_decision.proposal_id)
    if isinstance(proposal, queries.LookupFailure):
        code, detail = _issue_reason(
            proposal, ApplicationRejectionReason.PROPOSAL_NOT_FOUND
        )
        return PlanIssue(policy_decision_id, code, detail)

    # discovered is the one read in this function NOT keyed by
    # proposal_id/policy_decision_id -- it is looked up by file_id, off the
    # persisted FileObservationRow, which is nominally "shared" across every
    # analysis generation of this file. That is safe ONLY because the two
    # fields actually read from it below (.path, and the derived .filename)
    # are structurally immutable for the lifetime of that row: the entire
    # codebase contains exactly one UPDATE against FileObservationRow
    # (persistence.repositories.update_observation_hash), and it writes
    # ONLY the sha256 column -- never path, size_bytes, created_at, or
    # modified_at (see persistence.store.record_hash_success's own
    # docstring). Every OTHER generation-sensitive fact this function
    # exposes (category, destination_category, policy_outcome,
    # human_review_outcome, proposal_id) comes from `proposal`/
    # `policy_decision`/`review` above, each looked up by this exact
    # policy_decision_id's own lineage -- never from `discovered`.
    discovered = store.get_discovered_file(policy_decision.file_id)
    if discovered is None:
        return PlanIssue(
            policy_decision_id,
            ApplicationRejectionReason.DISCOVERED_FILE_NOT_FOUND.value,
            f"no DiscoveredFile with id={policy_decision.file_id}",
        )

    def make_item(
        *,
        destination_path: Path | None,
        human_review_outcome: HumanReviewOutcome | None,
        status: PlanStatus,
        reason_code: PlanReasonCode | None,
        reason: str | None,
    ) -> OrganizationPlanItem:
        return OrganizationPlanItem(
            file_id=policy_decision.file_id,
            proposal_id=proposal.id,
            policy_decision_id=policy_decision.id,
            source_path=discovered.path,
            filename=discovered.filename,
            category=proposal.category,
            destination_category=proposal.proposed_destination_category,
            destination_path=destination_path,
            policy_outcome=policy_decision.decision,
            human_review_outcome=human_review_outcome,
            status=status,
            reason_code=reason_code,
            reason=reason,
        )

    if policy_decision.decision is PolicyOutcome.BLOCK:
        return make_item(
            destination_path=None,
            human_review_outcome=None,
            status=PlanStatus.BLOCKED,
            reason_code=PlanReasonCode.POLICY_BLOCK,
            reason="BLOCK cannot be overridden",
        )

    if proposal.proposed_destination_category is None:
        return make_item(
            destination_path=None,
            human_review_outcome=None,
            status=PlanStatus.NO_ACTION,
            reason_code=PlanReasonCode.NO_DESTINATION_PROPOSED,
            reason="no destination proposed for this file",
        )

    destination_path = resolve_destination(
        sandbox_root, proposal.proposed_destination_category, discovered.filename
    )

    human_review_outcome: HumanReviewOutcome | None = None
    if policy_decision.decision is PolicyOutcome.REVIEW:
        review = queries.find_effective_human_review(store, policy_decision_id)
        if isinstance(review, queries.LookupFailure):
            reason_code = (
                PlanReasonCode.AMBIGUOUS_REVIEW_HISTORY
                if review.status is queries.LookupStatus.AMBIGUOUS
                else PlanReasonCode.MALFORMED_EVENT_PAYLOAD
            )
            return make_item(
                destination_path=destination_path,
                human_review_outcome=None,
                status=PlanStatus.INVALID,
                reason_code=reason_code,
                reason=review.detail,
            )
        if review is None:
            return make_item(
                destination_path=destination_path,
                human_review_outcome=None,
                status=PlanStatus.REVIEW_REQUIRED,
                reason_code=PlanReasonCode.REVIEW_REQUIRED,
                reason="no effective review recorded for this policy decision",
            )
        human_review_outcome = review.outcome
        if review.outcome is HumanReviewOutcome.SKIP:
            return make_item(
                destination_path=destination_path,
                human_review_outcome=human_review_outcome,
                status=PlanStatus.SKIPPED,
                reason_code=PlanReasonCode.HUMAN_SKIPPED,
                reason="effective review outcome is SKIP",
            )
        # outcome is APPROVE -> destination-eligible, continue below

    # policy_decision.decision is AUTO, or REVIEW+APPROVE -> destination-eligible
    inspection = inspect_destination(sandbox_root, discovered.path, destination_path)
    if inspection.conflict is DestinationConflict.SOURCE_EQUALS_DESTINATION:
        return make_item(
            destination_path=destination_path,
            human_review_outcome=human_review_outcome,
            status=PlanStatus.NO_ACTION,
            reason_code=PlanReasonCode.SOURCE_ALREADY_AT_DESTINATION,
            reason="source is already at the proposed destination",
        )
    if inspection.conflict is not DestinationConflict.NONE:
        return make_item(
            destination_path=destination_path,
            human_review_outcome=human_review_outcome,
            status=PlanStatus.CONFLICT,
            reason_code=_DESTINATION_CONFLICT_REASON[inspection.conflict],
            reason=f"destination inspection: {inspection.conflict.value}",
        )

    return make_item(
        destination_path=destination_path,
        human_review_outcome=human_review_outcome,
        status=PlanStatus.READY,
        reason_code=None,
        reason=None,
    )


def _summarize(
    items: list[OrganizationPlanItem], issues: list[PlanIssue]
) -> OrganizationPlanSummary:
    counts: dict[PlanStatus, int] = dict.fromkeys(PlanStatus, 0)
    for item in items:
        counts[item.status] += 1
    return OrganizationPlanSummary(
        files_total=len(items),
        ready=counts[PlanStatus.READY],
        review_required=counts[PlanStatus.REVIEW_REQUIRED],
        conflicts=counts[PlanStatus.CONFLICT],
        invalid=counts[PlanStatus.INVALID],
        blocked=counts[PlanStatus.BLOCKED],
        skipped=counts[PlanStatus.SKIPPED],
        no_action=counts[PlanStatus.NO_ACTION],
        issues=len(issues),
    )
