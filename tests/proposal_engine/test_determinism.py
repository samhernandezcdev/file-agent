"""Tests proving proposal generation is deterministic — same input, same output.

Mirrors the FA-005.1-hardened pattern: a fixed_clock and full-FileProposal
equality assertion (including created_at), not just the clock-independent
fields.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from file_agent.classifier import ClassificationResult
from file_agent.domain import DiscoveredFile, FileCategory
from file_agent.proposal_engine import ProposalEngine, propose_for


def test_repeated_calls_produce_identical_results(
    make_discovered_file: Callable[..., DiscoveredFile],
    fixed_clock: Callable[[], datetime],
) -> None:
    classification = ClassificationResult(
        discovered_file=make_discovered_file("C:/sandbox/report.pdf"),
        category=FileCategory.DOCUMENT,
        confidence=1.0,
        reasons=("extension 'pdf' matched category document",),
        classified_at=fixed_clock(),
        classifier_id="rules-v1",
    )

    first = propose_for(classification)
    second = propose_for(classification)

    assert first.category == second.category
    assert first.proposed_destination_category == second.proposed_destination_category
    assert first.confidence == second.confidence
    assert first.reasons == second.reasons


def test_full_result_is_deterministic_with_fixed_clock(
    make_discovered_file: Callable[..., DiscoveredFile],
    fixed_clock: Callable[[], datetime],
) -> None:
    """Same ClassificationResult + same rule table + same clock -> identical
    FileProposal, compared field-by-field including created_at and id
    excluded (a fresh identity is expected/correct per FA-006 §11-12) --
    every OTHER field must match exactly."""
    classification = ClassificationResult(
        discovered_file=make_discovered_file("C:/sandbox/report.pdf"),
        category=FileCategory.DOCUMENT,
        confidence=1.0,
        reasons=("extension 'pdf' matched category document",),
        classified_at=fixed_clock(),
        classifier_id="rules-v1",
    )

    first = ProposalEngine(clock=fixed_clock).propose(classification)
    second = ProposalEngine(clock=fixed_clock).propose(classification)

    assert first.created_at == second.created_at == fixed_clock()
    assert first.model_dump(exclude={"id"}) == second.model_dump(exclude={"id"})
    assert first.id != second.id


def test_fresh_engine_instances_agree(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    classification = ClassificationResult(
        discovered_file=make_discovered_file("C:/sandbox/notes.txt"),
        category=FileCategory.DOCUMENT,
        confidence=1.0,
        reasons=("extension 'txt' matched category document",),
        classified_at=datetime.now(UTC),
        classifier_id="rules-v1",
    )
    results = [ProposalEngine().propose(classification) for _ in range(5)]
    destinations = {r.proposed_destination_category for r in results}
    confidences = {r.confidence for r in results}
    reasons = {r.reasons for r in results}
    assert len(destinations) == 1
    assert len(confidences) == 1
    assert len(reasons) == 1
