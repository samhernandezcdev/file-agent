"""Only REVIEW may receive a human decision -- AUTO is redundant, BLOCK is
not overridable, for both APPROVE and SKIP."""

from collections.abc import Callable

import pytest

from file_agent.domain import (
    FileProposal,
    HumanReviewOutcome,
    PolicyDecision,
    PolicyOutcome,
)
from file_agent.human_review_engine import InvalidHumanReviewError, record_human_review


@pytest.mark.parametrize("decision", [PolicyOutcome.AUTO, PolicyOutcome.BLOCK])
@pytest.mark.parametrize(
    "outcome", [HumanReviewOutcome.APPROVE, HumanReviewOutcome.SKIP]
)
def test_non_review_policy_outcome_is_rejected(
    make_proposal: Callable[..., FileProposal],
    make_policy_decision: Callable[..., PolicyDecision],
    decision: PolicyOutcome,
    outcome: HumanReviewOutcome,
) -> None:
    proposal = make_proposal()
    policy_decision = make_policy_decision(proposal, decision=decision)

    with pytest.raises(InvalidHumanReviewError):
        record_human_review(policy_decision, proposal, outcome)
