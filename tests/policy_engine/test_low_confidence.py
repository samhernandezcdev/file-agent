"""Intermediate confidence on an allowlisted pair -> REVIEW.

Today's classifier/proposal-engine can't naturally produce a confidence
strictly between 0.0 and 1.0, so the FileProposal is built directly.
"""

from collections.abc import Callable

import pytest

from file_agent.domain import (
    DestinationCategory,
    FileCategory,
    FileProposal,
    PolicyOutcome,
)
from file_agent.policy_engine import evaluate_for


@pytest.mark.parametrize("confidence", [0.0, 0.5, 0.99])
def test_intermediate_confidence_on_allowlisted_pair_is_review(
    make_proposal: Callable[..., FileProposal],
    confidence: float,
) -> None:
    proposal = make_proposal(
        category=FileCategory.DOCUMENT,
        proposed_destination_category=DestinationCategory.DOCUMENTS,
        confidence=confidence,
        source_classification_confidence=confidence,
    )

    decision = evaluate_for(proposal)

    assert decision.decision is PolicyOutcome.REVIEW
    assert any("does not satisfy" in reason for reason in decision.reasons)
