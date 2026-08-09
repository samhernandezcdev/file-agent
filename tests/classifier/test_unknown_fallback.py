"""Tests for the UNKNOWN fallback — a normal result, never an exception."""

from collections.abc import Callable

from file_agent.classifier import classify_file
from file_agent.domain import DiscoveredFile, FileCategory


def test_unrecognized_file_classified_as_unknown(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    result = classify_file(make_discovered_file("C:/sandbox/randomfile123.xyz789"))
    assert result.category is FileCategory.UNKNOWN
    assert result.confidence == 0.0


def test_unknown_result_has_non_empty_explanatory_reasons(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    result = classify_file(make_discovered_file("C:/sandbox/randomfile123.xyz789"))
    assert len(result.reasons) == 3  # one per rule in RULES, each explaining its miss
    for reason in result.reasons:
        assert "no match" in reason


def test_unknown_is_a_valid_classification_result_not_an_exception(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    # classify_file() must not raise for an unrecognized file
    result = classify_file(make_discovered_file("C:/sandbox/whatever.unknownext"))
    assert result.discovered_file is not None
    assert result.classifier_id
