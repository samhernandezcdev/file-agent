"""Tests for the special-filename (extensionless well-known name) rule."""

from collections.abc import Callable

import pytest

from file_agent.classifier import classify_file
from file_agent.domain import DiscoveredFile, FileCategory


@pytest.mark.parametrize(
    ("name", "expected_category"),
    [
        ("Dockerfile", FileCategory.CODE),
        ("dockerfile", FileCategory.CODE),
        ("Makefile", FileCategory.CODE),
        ("README", FileCategory.DOCUMENT),
        ("readme", FileCategory.DOCUMENT),
        ("ReadMe", FileCategory.DOCUMENT),
        ("LICENSE", FileCategory.DOCUMENT),
        ("CHANGELOG", FileCategory.DOCUMENT),
        ("AUTHORS", FileCategory.DOCUMENT),
        ("CONTRIBUTING", FileCategory.DOCUMENT),
        ("NOTICE", FileCategory.DOCUMENT),
    ],
)
def test_well_known_extensionless_names_resolve(
    make_discovered_file: Callable[..., DiscoveredFile],
    name: str,
    expected_category: FileCategory,
) -> None:
    result = classify_file(make_discovered_file(f"C:/sandbox/{name}"))
    assert result.category is expected_category
    assert result.confidence == 1.0
    assert any("well-known name" in reason for reason in result.reasons)


def test_special_name_with_extension_resolved_by_extension_rule_first(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    result = classify_file(make_discovered_file("C:/sandbox/README.md"))
    assert result.category is FileCategory.DOCUMENT
    # resolved via the extension rule, not the special-filename rule
    assert any("extension" in reason for reason in result.reasons)
    assert not any("well-known name" in reason for reason in result.reasons)


def test_unrecognized_extensionless_name_does_not_match_this_rule(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    result = classify_file(make_discovered_file("C:/sandbox/randomfile123"))
    assert result.category is FileCategory.UNKNOWN
