"""The engine cross-validates ids/category in-memory rather than trusting
the caller's claims -- an unrelated PolicyDecision must never authorize a
review for a proposal it doesn't actually describe."""

from collections.abc import Callable
from uuid import uuid4

import pytest

from file_agent.domain import (
    DestinationCategory,
    FileProposal,
    HumanReviewOutcome,
    PolicyDecision,
)
from file_agent.human_review_engine import InvalidHumanReviewError, record_human_review


def test_mismatched_proposal_id_is_rejected(
    make_proposal: Callable[..., FileProposal],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    proposal = make_proposal()
    policy_decision = make_policy_decision(proposal, proposal_id=uuid4())

    with pytest.raises(InvalidHumanReviewError):
        record_human_review(policy_decision, proposal, HumanReviewOutcome.SKIP)


def test_mismatched_file_id_is_rejected(
    make_proposal: Callable[..., FileProposal],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    proposal = make_proposal()
    policy_decision = make_policy_decision(proposal, file_id=uuid4())

    with pytest.raises(InvalidHumanReviewError):
        record_human_review(policy_decision, proposal, HumanReviewOutcome.SKIP)


def test_mismatched_destination_category_is_rejected(
    make_proposal: Callable[..., FileProposal],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    proposal = make_proposal(
        proposed_destination_category=DestinationCategory.DOCUMENTS
    )
    policy_decision = make_policy_decision(
        proposal, destination_category=DestinationCategory.IMAGES
    )

    with pytest.raises(InvalidHumanReviewError):
        record_human_review(policy_decision, proposal, HumanReviewOutcome.SKIP)
