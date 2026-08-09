"""EXECUTABLE is handled identically to any other mapped category — no
safety-policy special-casing in the proposal engine (that's FA-007's job)."""

from collections.abc import Callable
from datetime import UTC, datetime

from file_agent.classifier import ClassificationResult
from file_agent.domain import DestinationCategory, DiscoveredFile, FileCategory
from file_agent.proposal_engine import propose_for


def test_executable_maps_to_executables_destination(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    classification = ClassificationResult(
        discovered_file=make_discovered_file("C:/sandbox/setup.exe"),
        category=FileCategory.EXECUTABLE,
        confidence=1.0,
        reasons=("extension 'exe' matched category executable",),
        classified_at=datetime.now(UTC),
        classifier_id="rules-v1",
    )

    proposal = propose_for(classification)

    assert proposal.proposed_destination_category is DestinationCategory.EXECUTABLES
    assert proposal.confidence == 1.0
    assert proposal.proposed_name is None
    assert proposal.proposed_destination is None
