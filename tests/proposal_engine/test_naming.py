"""proposed_name is always None -- no renaming in this version."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from file_agent.classifier import ClassificationResult
from file_agent.domain import DiscoveredFile, FileCategory
from file_agent.proposal_engine import propose_for


@pytest.mark.parametrize("category", list(FileCategory))
def test_proposed_name_always_none(
    make_discovered_file: Callable[..., DiscoveredFile],
    category: FileCategory,
) -> None:
    classification = ClassificationResult(
        discovered_file=make_discovered_file("C:/sandbox/thing.ext"),
        category=category,
        confidence=0.5,
        reasons=("stub reason",),
        classified_at=datetime.now(UTC),
        classifier_id="rules-v1",
    )

    proposal = propose_for(classification)

    assert proposal.proposed_name is None
    assert proposal.proposed_destination is None
