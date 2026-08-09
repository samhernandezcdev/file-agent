"""reasons content for representative mapped/unmapped cases."""

from collections.abc import Callable
from datetime import UTC, datetime

from file_agent.classifier import ClassificationResult
from file_agent.domain import DiscoveredFile, FileCategory
from file_agent.proposal_engine import propose_for


def test_reasons_is_non_empty_tuple(
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

    assert isinstance(proposal.reasons, tuple)
    assert len(proposal.reasons) >= 2


def test_reasons_mention_classifier_id(
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

    assert any("classifier=rules-v1" in reason for reason in proposal.reasons)
