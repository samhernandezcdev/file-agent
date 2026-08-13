"""Valid review recordings across the required scenarios."""

from collections.abc import Callable

from file_agent.domain import (
    DestinationCategory,
    FileCategory,
    FileProposal,
    HumanReviewOutcome,
    PolicyDecision,
)
from file_agent.human_review_engine import HUMAN_REVIEW_ENGINE_ID, record_human_review


def test_executable_proposal_approve_is_valid(
    make_proposal: Callable[..., FileProposal],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    proposal = make_proposal(
        category=FileCategory.EXECUTABLE,
        proposed_destination_category=DestinationCategory.EXECUTABLES,
    )
    policy_decision = make_policy_decision(proposal)

    review = record_human_review(policy_decision, proposal, HumanReviewOutcome.APPROVE)

    assert review.outcome is HumanReviewOutcome.APPROVE
    assert review.destination_category is DestinationCategory.EXECUTABLES
    assert review.policy_decision_id == policy_decision.id
    assert review.proposal_id == proposal.id
    assert review.file_id == proposal.file_id
    assert review.policy_engine_id == policy_decision.policy_engine_id
    assert review.proposal_engine_id == proposal.proposal_engine_id
    assert review.human_review_engine_id == HUMAN_REVIEW_ENGINE_ID


def test_executable_proposal_skip_is_valid(
    make_proposal: Callable[..., FileProposal],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    proposal = make_proposal(
        category=FileCategory.EXECUTABLE,
        proposed_destination_category=DestinationCategory.EXECUTABLES,
    )
    policy_decision = make_policy_decision(proposal)

    review = record_human_review(policy_decision, proposal, HumanReviewOutcome.SKIP)

    assert review.outcome is HumanReviewOutcome.SKIP
    assert review.destination_category is DestinationCategory.EXECUTABLES


def test_no_destination_proposal_skip_is_valid(
    make_proposal: Callable[..., FileProposal],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    proposal = make_proposal(
        category=FileCategory.UNKNOWN,
        proposed_destination_category=None,
        confidence=0.0,
        source_classification_confidence=0.0,
    )
    policy_decision = make_policy_decision(proposal, destination_category=None)

    review = record_human_review(policy_decision, proposal, HumanReviewOutcome.SKIP)

    assert review.outcome is HumanReviewOutcome.SKIP
    assert review.destination_category is None
