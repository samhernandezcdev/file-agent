"""APPROVE is invalid when the underlying proposal has no logical destination."""

from collections.abc import Callable

import pytest

from file_agent.domain import (
    FileCategory,
    FileProposal,
    HumanReviewOutcome,
    PolicyDecision,
)
from file_agent.human_review_engine import InvalidHumanReviewError, record_human_review


def test_approve_without_destination_is_rejected(
    make_proposal: Callable[..., FileProposal],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    proposal = make_proposal(
        category=FileCategory.OTHER,
        proposed_destination_category=None,
        confidence=0.0,
        source_classification_confidence=0.0,
    )
    policy_decision = make_policy_decision(proposal, destination_category=None)

    with pytest.raises(InvalidHumanReviewError):
        record_human_review(policy_decision, proposal, HumanReviewOutcome.APPROVE)
