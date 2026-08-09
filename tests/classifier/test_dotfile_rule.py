"""Tests for the dotfile-convention rule.

Regression coverage for FA-005 review m1: a dot-prefixed filename must
classify as OTHER regardless of whether pathlib happens to assign it a
non-empty "extension" (e.g. ".env.local" -> extension "local"), as long as
that extension isn't itself a recognized type (extension rule always wins
first — see test_hidden_file_with_recognized_extension_is_not_a_dotfile).
"""

from collections.abc import Callable

import pytest

from file_agent.classifier import classify_file
from file_agent.domain import DiscoveredFile, FileCategory


@pytest.mark.parametrize(
    "name",
    [
        ".gitignore",
        ".env",
        ".editorconfig",
        ".npmrc",
        ".x",
        ".env.local",
        ".env.production",
        ".gitignore.bak",
        ".a.b",
    ],
)
def test_dotfiles_classified_as_other(
    make_discovered_file: Callable[..., DiscoveredFile], name: str
) -> None:
    result = classify_file(make_discovered_file(f"C:/sandbox/{name}"))
    assert result.category is FileCategory.OTHER
    assert result.confidence == 1.0
    assert any("naming convention" in reason for reason in result.reasons)


def test_hidden_file_with_recognized_extension_is_not_a_dotfile(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    # the extension rule runs first and wins outright -- the dotfile rule is
    # never even reached, regardless of the leading dot.
    result = classify_file(make_discovered_file("C:/sandbox/.hidden.jpg"))
    assert result.category is FileCategory.IMAGE
    assert any("extension" in reason for reason in result.reasons)
    assert not any("naming convention" in reason for reason in result.reasons)
