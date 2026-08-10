"""EXECUTABLE + destination EXECUTABLES + confidence 1.0 -> REVIEW.

The central confidence != permission proof (docs/SAFETY.md rule 6): maximum
confidence and a resolved destination still do not grant AUTO eligibility.
"""

from collections.abc import Callable

from file_agent.domain import (
    DestinationCategory,
    FileCategory,
    FileProposal,
    PolicyOutcome,
)
from file_agent.policy_engine import evaluate_for


def test_executable_at_full_confidence_is_review(
    make_proposal: Callable[..., FileProposal],
) -> None:
    proposal = make_proposal(
        category=FileCategory.EXECUTABLE,
        proposed_destination_category=DestinationCategory.EXECUTABLES,
        confidence=1.0,
        source_classification_confidence=1.0,
    )

    decision = evaluate_for(proposal)

    assert decision.decision is PolicyOutcome.REVIEW
    assert any("executable" in reason for reason in decision.reasons)
    assert any("confidence does not override" in reason for reason in decision.reasons)
