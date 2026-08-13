"""HumanReviewEngine — validates and records a human's APPROVE/SKIP decision
for one REVIEW PolicyDecision.

Performs no filesystem I/O of any kind and has no dependency on
file_agent.persistence -- recording is a pure, total function over two
already-in-memory objects (PolicyDecision, FileProposal). Never inspects,
moves, renames, creates, deletes, hashes, stats, or resolves a managed path.

Stateless and persistence-free by design: it cannot itself enforce "one
effective HumanReviewDecision per PolicyDecision" across separate calls,
because doing so would require querying prior review history. FA-009 v1
permits exactly one effective review per PolicyDecision as a hard rule, but
enforcing it is an explicit obligation of whatever application/orchestration
layer calls record_human_review() and persists the resulting event: before
persisting a new HUMAN_REVIEW_RECORDED event, that layer MUST check for an
existing effective review for the same policy_decision_id (a payload scan
over prior HUMAN_REVIEW_RECORDED events) and reject the new attempt if one
exists -- not resolve it by timestamp, not silently allow both to stand.
This package does not implement that orchestration layer. See
tests/human_review_engine/test_repeated_review.py for what IS proven here:
that this engine has no way to enforce the limit itself.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from file_agent.domain import (
    DomainEvent,
    EntityType,
    EventType,
    FileProposal,
    HumanReviewDecision,
    HumanReviewOutcome,
    PolicyDecision,
    PolicyOutcome,
    ReviewSource,
)
from file_agent.human_review_engine.rules import HUMAN_REVIEW_ENGINE_ID


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InvalidHumanReviewError(ValueError):
    """Raised by HumanReviewEngine.record() when the call itself is invalid
    -- mismatched proposal/file/policy-decision linkage, a policy outcome
    other than REVIEW (AUTO is redundant, BLOCK is not overridable), or an
    APPROVE for a proposal with no logical destination. Never persisted --
    an invalid call risks nothing and leaves no fact worth auditing, unlike
    a REJECTED TransactionResult.
    """


class HumanReviewEngine:
    """Validates linkage/outcome rules and records a human's decision.

    Never raises for a well-formed, valid combination -- always returns a
    HumanReviewDecision. Raises InvalidHumanReviewError for anything that
    should never be reachable through legitimate use (see module docstring
    for exactly which cases).
    """

    def __init__(self, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock

    def record(
        self,
        policy_decision: PolicyDecision,
        proposal: FileProposal,
        outcome: HumanReviewOutcome,
        *,
        review_source: ReviewSource = ReviewSource.USER,
        note: str | None = None,
    ) -> HumanReviewDecision:
        if policy_decision.proposal_id != proposal.id:
            raise InvalidHumanReviewError(
                "policy_decision.proposal_id does not match proposal.id"
            )
        if policy_decision.file_id != proposal.file_id:
            raise InvalidHumanReviewError(
                "policy_decision.file_id does not match proposal.file_id"
            )
        if (
            policy_decision.destination_category
            != proposal.proposed_destination_category
        ):
            raise InvalidHumanReviewError(
                "policy_decision.destination_category does not match "
                "proposal.proposed_destination_category"
            )
        if policy_decision.decision is PolicyOutcome.AUTO:
            raise InvalidHumanReviewError(
                "AUTO does not require human review -- creating a review is redundant"
            )
        if policy_decision.decision is PolicyOutcome.BLOCK:
            raise InvalidHumanReviewError(
                "BLOCK cannot be overridden by human review in FA-009"
            )
        # policy_decision.decision is REVIEW from here on.
        if (
            outcome is HumanReviewOutcome.APPROVE
            and proposal.proposed_destination_category is None
        ):
            raise InvalidHumanReviewError(
                "APPROVE requires a proposal with a logical destination"
            )

        return HumanReviewDecision(
            policy_decision_id=policy_decision.id,
            proposal_id=proposal.id,
            file_id=proposal.file_id,
            outcome=outcome,
            destination_category=proposal.proposed_destination_category,
            reviewed_at=self._clock(),
            review_source=review_source,
            note=note,
            policy_engine_id=policy_decision.policy_engine_id,
            proposal_engine_id=proposal.proposal_engine_id,
            human_review_engine_id=HUMAN_REVIEW_ENGINE_ID,
        )


def record_human_review(
    policy_decision: PolicyDecision,
    proposal: FileProposal,
    outcome: HumanReviewOutcome,
    *,
    review_source: ReviewSource = ReviewSource.USER,
    note: str | None = None,
) -> HumanReviewDecision:
    """Convenience entry point: ``HumanReviewEngine().record(...)``."""
    return HumanReviewEngine().record(
        policy_decision, proposal, outcome, review_source=review_source, note=note
    )


def human_review_recorded_event(review: HumanReviewDecision) -> DomainEvent:
    """Maps a HumanReviewDecision to a HUMAN_REVIEW_RECORDED DomainEvent.

    Takes ONLY the review -- every field the payload needs, including
    policy_engine_id/proposal_engine_id, already lives on the review itself,
    so this function cannot be called with a valid review paired against an
    unrelated PolicyDecision/FileProposal; there is no second/third
    parameter through which that could even be attempted. Does not persist
    anything itself -- no dependency on file_agent.persistence.
    """
    return DomainEvent(
        event_type=EventType.HUMAN_REVIEW_RECORDED,
        entity_type=EntityType.HUMAN_REVIEW,
        entity_id=review.id,
        timestamp=review.reviewed_at,
        payload={
            "review_id": str(review.id),
            "policy_decision_id": str(review.policy_decision_id),
            "proposal_id": str(review.proposal_id),
            "file_id": str(review.file_id),
            "outcome": review.outcome.value,
            "destination_category": (
                review.destination_category.value
                if review.destination_category is not None
                else None
            ),
            "policy_engine_id": review.policy_engine_id,
            "proposal_engine_id": review.proposal_engine_id,
            "reviewed_at": review.reviewed_at.isoformat(),
            "review_source": review.review_source.value,
            "note": review.note,
            "human_review_engine_id": review.human_review_engine_id,
        },
    )
