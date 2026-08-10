"""FA-007.1 (review m3): rules-v1 regression -- BLOCK is reserved in the
PolicyOutcome vocabulary but no v1 rule produces it.

Parametrized across a representative input from each precedence branch:
eligible mapped AUTO, EXECUTABLE override, UNKNOWN/no destination,
OTHER/no destination, low-confidence eligible pair, and a mismatched/
unapproved pair. Every resulting decision must be AUTO or REVIEW, never
BLOCK.
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

_REPRESENTATIVE_CASES = {
    "eligible_auto": {
        "category": FileCategory.DOCUMENT,
        "proposed_destination_category": DestinationCategory.DOCUMENTS,
        "confidence": 1.0,
    },
    "executable_override": {
        "category": FileCategory.EXECUTABLE,
        "proposed_destination_category": DestinationCategory.EXECUTABLES,
        "confidence": 1.0,
    },
    "unknown_no_destination": {
        "category": FileCategory.UNKNOWN,
        "proposed_destination_category": None,
        "confidence": 0.0,
    },
    "other_no_destination": {
        "category": FileCategory.OTHER,
        "proposed_destination_category": None,
        "confidence": 0.0,
    },
    "low_confidence_eligible_pair": {
        "category": FileCategory.DOCUMENT,
        "proposed_destination_category": DestinationCategory.DOCUMENTS,
        "confidence": 0.5,
    },
    "mismatched_unapproved_pair": {
        "category": FileCategory.OTHER,
        "proposed_destination_category": DestinationCategory.DOCUMENTS,
        "confidence": 1.0,
    },
}


@pytest.mark.parametrize(
    "overrides", _REPRESENTATIVE_CASES.values(), ids=_REPRESENTATIVE_CASES.keys()
)
def test_rules_v1_never_produces_block(
    make_proposal: Callable[..., FileProposal],
    overrides: dict[str, object],
) -> None:
    proposal = make_proposal(
        **overrides, source_classification_confidence=overrides["confidence"]
    )

    decision = evaluate_for(proposal)

    assert decision.decision in (PolicyOutcome.AUTO, PolicyOutcome.REVIEW)
    assert decision.decision is not PolicyOutcome.BLOCK
