"""UNKNOWN and OTHER produce valid no-destination proposals, not exceptions."""

from collections.abc import Callable
from datetime import UTC, datetime

from file_agent.classifier import ClassificationResult
from file_agent.domain import DiscoveredFile, FileCategory
from file_agent.proposal_engine import propose_for


def test_unknown_produces_no_destination_and_zero_confidence(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    classification = ClassificationResult(
        discovered_file=make_discovered_file("C:/sandbox/whatever.unknownext"),
        category=FileCategory.UNKNOWN,
        confidence=0.0,
        reasons=("no rule matched",),
        classified_at=datetime.now(UTC),
        classifier_id="rules-v1",
    )

    proposal = propose_for(classification)

    assert proposal.proposed_destination_category is None
    assert proposal.confidence == 0.0
    assert proposal.source_classification_confidence == 0.0


def test_other_produces_no_destination_but_preserves_source_confidence(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    """A confident OTHER classification (e.g. a recognized dotfile) still has
    no destination mapping -- proposal.confidence is 0.0, but
    source_classification_confidence preserves what classification actually
    said, so that fact isn't lost just because no destination was proposed.
    """
    classification = ClassificationResult(
        discovered_file=make_discovered_file("C:/sandbox/.env"),
        category=FileCategory.OTHER,
        confidence=1.0,
        reasons=("filename '.env' follows dotfile/config naming convention",),
        classified_at=datetime.now(UTC),
        classifier_id="rules-v1",
    )

    proposal = propose_for(classification)

    assert proposal.proposed_destination_category is None
    assert proposal.confidence == 0.0
    assert proposal.source_classification_confidence == 1.0


def test_unknown_and_other_have_distinguishable_reasons(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    unknown = propose_for(
        ClassificationResult(
            discovered_file=make_discovered_file("C:/sandbox/a.unknownext"),
            category=FileCategory.UNKNOWN,
            confidence=0.0,
            reasons=("no rule matched",),
            classified_at=datetime.now(UTC),
            classifier_id="rules-v1",
        )
    )
    other = propose_for(
        ClassificationResult(
            discovered_file=make_discovered_file("C:/sandbox/.env"),
            category=FileCategory.OTHER,
            confidence=1.0,
            reasons=("dotfile convention",),
            classified_at=datetime.now(UTC),
            classifier_id="rules-v1",
        )
    )

    assert unknown.reasons != other.reasons
    assert any("unknown" in reason for reason in unknown.reasons)
    assert any("other" in reason for reason in other.reasons)
