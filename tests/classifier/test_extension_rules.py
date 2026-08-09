"""Tests for the extension lookup rule."""

from collections.abc import Callable

import pytest

from file_agent.classifier import classify_file
from file_agent.domain import DiscoveredFile, FileCategory


@pytest.mark.parametrize(
    ("path", "expected_category"),
    [
        ("C:/sandbox/report.pdf", FileCategory.DOCUMENT),
        ("C:/sandbox/notes.txt", FileCategory.DOCUMENT),
        ("C:/sandbox/sheet.xlsx", FileCategory.DOCUMENT),
        ("C:/sandbox/photo.jpg", FileCategory.IMAGE),
        ("C:/sandbox/icon.svg", FileCategory.IMAGE),
        ("C:/sandbox/song.mp3", FileCategory.AUDIO),
        ("C:/sandbox/song.flac", FileCategory.AUDIO),
        ("C:/sandbox/movie.mp4", FileCategory.VIDEO),
        ("C:/sandbox/movie.mkv", FileCategory.VIDEO),
        ("C:/sandbox/bundle.zip", FileCategory.ARCHIVE),
        ("C:/sandbox/archive.tar.gz", FileCategory.ARCHIVE),  # extension -> "gz"
        ("C:/sandbox/main.py", FileCategory.CODE),
        ("C:/sandbox/script.sh", FileCategory.CODE),
        ("C:/sandbox/deploy.ps1", FileCategory.CODE),
        ("C:/sandbox/setup.exe", FileCategory.EXECUTABLE),
        ("C:/sandbox/installer.msi", FileCategory.EXECUTABLE),
        ("C:/sandbox/library.dll", FileCategory.EXECUTABLE),
        ("C:/sandbox/setup.bat", FileCategory.EXECUTABLE),
        ("C:/sandbox/run.cmd", FileCategory.EXECUTABLE),
    ],
)
def test_extension_resolves_expected_category(
    make_discovered_file: Callable[..., DiscoveredFile],
    path: str,
    expected_category: FileCategory,
) -> None:
    result = classify_file(make_discovered_file(path))
    assert result.category is expected_category
    assert result.confidence == 1.0
    assert any("extension" in reason for reason in result.reasons)


def test_bat_and_cmd_are_executable_not_code(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    for name in ("script.bat", "script.cmd"):
        result = classify_file(make_discovered_file(f"C:/sandbox/{name}"))
        assert result.category is FileCategory.EXECUTABLE


def test_ps1_and_sh_are_code_not_executable(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    for name in ("script.ps1", "script.sh"):
        result = classify_file(make_discovered_file(f"C:/sandbox/{name}"))
        assert result.category is FileCategory.CODE


def test_unrecognized_extension_does_not_match_this_rule(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    result = classify_file(make_discovered_file("C:/sandbox/mystery.xyz123"))
    assert result.category is FileCategory.UNKNOWN
