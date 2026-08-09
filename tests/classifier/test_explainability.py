"""Tests for explainability: evidence content and category/confidence consistency."""

from collections.abc import Callable

from file_agent.classifier import classify_file
from file_agent.domain import DiscoveredFile, FileCategory


def test_matched_result_cites_the_specific_extension(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    result = classify_file(make_discovered_file("C:/sandbox/report.pdf"))
    assert result.category is FileCategory.DOCUMENT
    assert len(result.reasons) == 1
    assert "pdf" in result.reasons[0]
    assert "document" in result.reasons[0]


def test_matched_result_cites_the_specific_filename(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    result = classify_file(make_discovered_file("C:/sandbox/Dockerfile"))
    assert "Dockerfile" in result.reasons[0]


def test_confidence_is_one_for_any_rule_match(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    for path in ("a.pdf", "Dockerfile", ".gitignore"):
        result = classify_file(make_discovered_file(f"C:/sandbox/{path}"))
        assert result.category is not FileCategory.UNKNOWN
        assert result.confidence == 1.0


def test_confidence_is_zero_for_unknown(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    result = classify_file(make_discovered_file("C:/sandbox/whatever.unknownext"))
    assert result.confidence == 0.0
