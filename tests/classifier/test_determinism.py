"""Tests proving classification is deterministic — same input, same output.

Regression coverage for FA-005 review m3: `classified_at` is part of the
durable FILE_CLASSIFIED event and must be included in the determinism
claim, not silently excluded from comparison because the default clock
advances between calls.
"""

from collections.abc import Callable
from datetime import datetime

from file_agent.classifier import FileClassifier, classify_file
from file_agent.domain import DiscoveredFile


def test_repeated_calls_produce_identical_results(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    discovered = make_discovered_file("C:/sandbox/report.pdf")
    first = classify_file(discovered)
    second = classify_file(discovered)
    assert first.category == second.category
    assert first.confidence == second.confidence
    assert first.reasons == second.reasons
    assert first.classifier_id == second.classifier_id


def test_full_result_is_deterministic_with_fixed_clock(
    make_discovered_file: Callable[..., DiscoveredFile],
    fixed_clock: Callable[[], datetime],
) -> None:
    """Same DiscoveredFile + same classifier/rules version + same clock ->
    identical ClassificationResult, compared field-by-field including
    classified_at (not just the fields that happen to be clock-independent)."""
    discovered = make_discovered_file("C:/sandbox/report.pdf")

    first = FileClassifier(clock=fixed_clock).classify(discovered)
    second = FileClassifier(clock=fixed_clock).classify(discovered)

    assert first == second
    assert first.classified_at == second.classified_at == fixed_clock()


def test_full_result_is_deterministic_for_unknown_with_fixed_clock(
    make_discovered_file: Callable[..., DiscoveredFile],
    fixed_clock: Callable[[], datetime],
) -> None:
    discovered = make_discovered_file("C:/sandbox/whatever.unknownext")

    first = FileClassifier(clock=fixed_clock).classify(discovered)
    second = FileClassifier(clock=fixed_clock).classify(discovered)

    assert first == second
    assert first.classified_at == second.classified_at


def test_fresh_classifier_instances_agree(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    discovered = make_discovered_file("C:/sandbox/notes.txt")
    results = [FileClassifier().classify(discovered) for _ in range(5)]
    categories = {r.category for r in results}
    confidences = {r.confidence for r in results}
    reasons = {r.reasons for r in results}
    assert len(categories) == 1
    assert len(confidences) == 1
    assert len(reasons) == 1


def test_unknown_results_are_also_deterministic(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    discovered = make_discovered_file("C:/sandbox/whatever.unknownext")
    first = classify_file(discovered)
    second = classify_file(discovered)
    assert first.category == second.category == first.category
    assert first.reasons == second.reasons
