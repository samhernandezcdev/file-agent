"""Allowlisted category/destination pairs at confidence 1.0 -> AUTO."""

from collections.abc import Callable

import pytest

from file_agent.domain import (
    DestinationCategory,
    FileCategory,
    FileProposal,
    PolicyOutcome,
)
from file_agent.policy_engine import evaluate_for

_ALLOWLISTED_PAIRS = [
    (FileCategory.DOCUMENT, DestinationCategory.DOCUMENTS),
    (FileCategory.IMAGE, DestinationCategory.IMAGES),
    (FileCategory.AUDIO, DestinationCategory.AUDIO),
    (FileCategory.VIDEO, DestinationCategory.VIDEO),
    (FileCategory.ARCHIVE, DestinationCategory.ARCHIVES),
    (FileCategory.CODE, DestinationCategory.CODE),
]


@pytest.mark.parametrize(
    ("category", "destination"), sorted(_ALLOWLISTED_PAIRS, key=str)
)
def test_allowlisted_pair_at_full_confidence_is_auto(
    make_proposal: Callable[..., FileProposal],
    category: FileCategory,
    destination: DestinationCategory,
) -> None:
    proposal = make_proposal(
        category=category,
        proposed_destination_category=destination,
        confidence=1.0,
        source_classification_confidence=1.0,
    )

    decision = evaluate_for(proposal)

    assert decision.decision is PolicyOutcome.AUTO
