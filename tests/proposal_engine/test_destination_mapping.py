"""Every mapped FileCategory resolves to its expected DestinationCategory."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from file_agent.classifier import ClassificationResult
from file_agent.domain import DestinationCategory, DiscoveredFile, FileCategory
from file_agent.proposal_engine import propose_for

_EXPECTED = {
    FileCategory.DOCUMENT: DestinationCategory.DOCUMENTS,
    FileCategory.IMAGE: DestinationCategory.IMAGES,
    FileCategory.AUDIO: DestinationCategory.AUDIO,
    FileCategory.VIDEO: DestinationCategory.VIDEO,
    FileCategory.ARCHIVE: DestinationCategory.ARCHIVES,
    FileCategory.CODE: DestinationCategory.CODE,
    FileCategory.EXECUTABLE: DestinationCategory.EXECUTABLES,
}


@pytest.mark.parametrize(("category", "expected"), sorted(_EXPECTED.items(), key=str))
def test_mapped_category_resolves_expected_destination(
    make_discovered_file: Callable[..., DiscoveredFile],
    category: FileCategory,
    expected: DestinationCategory,
) -> None:
    classification = ClassificationResult(
        discovered_file=make_discovered_file("C:/sandbox/thing.ext"),
        category=category,
        confidence=0.83,
        reasons=("stub reason",),
        classified_at=datetime.now(UTC),
        classifier_id="rules-v1",
    )

    proposal = propose_for(classification)

    assert proposal.proposed_destination_category is expected
    assert proposal.confidence == 0.83
    assert proposal.source_classification_confidence == 0.83


@pytest.mark.parametrize(
    "category",
    [FileCategory.DOCUMENT, FileCategory.IMAGE, FileCategory.EXECUTABLE],
)
def test_confidence_equals_source_classification_confidence_for_mapped_categories(
    make_discovered_file: Callable[..., DiscoveredFile],
    category: FileCategory,
) -> None:
    """FA-006.1 (review m3): confidence == source_classification_confidence
    is true by construction (engine.py) for every mapped category -- pin it
    down as an executable regression invariant rather than an implicit side
    effect of the destination-mapping assertions above."""
    classification = ClassificationResult(
        discovered_file=make_discovered_file("C:/sandbox/thing.ext"),
        category=category,
        confidence=0.42,
        reasons=("stub reason",),
        classified_at=datetime.now(UTC),
        classifier_id="rules-v1",
    )

    proposal = propose_for(classification)

    assert proposal.confidence == proposal.source_classification_confidence
    assert proposal.confidence == classification.confidence


def test_reasons_cite_classification_evidence_and_mapping_rule(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    classification = ClassificationResult(
        discovered_file=make_discovered_file("C:/sandbox/report.pdf"),
        category=FileCategory.DOCUMENT,
        confidence=1.0,
        reasons=("extension 'pdf' matched category document",),
        classified_at=datetime.now(UTC),
        classifier_id="rules-v1",
    )

    proposal = propose_for(classification)

    assert any("classification:" in reason for reason in proposal.reasons)
    assert any("destination mapping:" in reason for reason in proposal.reasons)
