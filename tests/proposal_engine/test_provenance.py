"""Structured classification provenance -- FA-006 review round-2 requirement.

source_classification_confidence/source_classifier_id/category on the
resulting FileProposal must exactly match the input ClassificationResult's
fields, so a caller can recover proposal lineage without parsing `reasons`
text. proposal_engine_id is always the fixed PROPOSAL_ENGINE_ID.
"""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from file_agent.classifier import ClassificationResult
from file_agent.domain import DiscoveredFile, FileCategory
from file_agent.proposal_engine import PROPOSAL_ENGINE_ID, propose_for


@pytest.mark.parametrize(
    ("category", "confidence"),
    [
        (FileCategory.DOCUMENT, 1.0),
        (FileCategory.UNKNOWN, 0.0),
        (FileCategory.OTHER, 0.6),
    ],
)
def test_provenance_fields_match_source_classification(
    make_discovered_file: Callable[..., DiscoveredFile],
    category: FileCategory,
    confidence: float,
) -> None:
    classification = ClassificationResult(
        discovered_file=make_discovered_file("C:/sandbox/thing.ext"),
        category=category,
        confidence=confidence,
        reasons=("stub reason",),
        classified_at=datetime.now(UTC),
        classifier_id="rules-v1",
    )

    proposal = propose_for(classification)

    assert proposal.category is classification.category
    assert proposal.source_classification_confidence == classification.confidence
    assert proposal.source_classifier_id == classification.classifier_id
    assert proposal.proposal_engine_id == PROPOSAL_ENGINE_ID


def test_source_classifier_id_is_not_hardcoded_to_the_default(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    """Proves the engine actually reads classifier_id from the input rather
    than always writing its own PROPOSAL_ENGINE_ID -- a differently-labeled
    classifier_id must survive unchanged onto the proposal."""
    classification = ClassificationResult(
        discovered_file=make_discovered_file("C:/sandbox/thing.pdf"),
        category=FileCategory.DOCUMENT,
        confidence=1.0,
        reasons=("stub reason",),
        classified_at=datetime.now(UTC),
        classifier_id="rules-v2-experimental",
    )

    proposal = propose_for(classification)

    assert proposal.source_classifier_id == "rules-v2-experimental"
    assert proposal.proposal_engine_id == "rules-v1"
