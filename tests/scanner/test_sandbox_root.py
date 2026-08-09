"""Tests for SandboxRoot validation."""

import subprocess
from pathlib import Path

import pytest

from file_agent.scanner import SandboxRoot, SandboxRootError


def test_accepts_absolute_existing_directory(tmp_path: Path) -> None:
    root = SandboxRoot.from_path(tmp_path)
    assert root.path == tmp_path.resolve()


def test_case_insensitive_root_equivalent(tmp_path: Path) -> None:
    root_lower = SandboxRoot.from_path(Path(str(tmp_path).lower()))
    root_upper = SandboxRoot.from_path(Path(str(tmp_path).upper()))
    assert root_lower.path == root_upper.path


def test_rejects_relative_path() -> None:
    with pytest.raises(SandboxRootError):
        SandboxRoot.from_path(Path("relative/dir"))


def test_rejects_nonexistent_path(tmp_path: Path) -> None:
    with pytest.raises(SandboxRootError):
        SandboxRoot.from_path(tmp_path / "does-not-exist")


def test_rejects_file_not_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "afile.txt"
    file_path.write_text("x")
    with pytest.raises(SandboxRootError):
        SandboxRoot.from_path(file_path)


def test_rejects_drive_relative_path() -> None:
    with pytest.raises(SandboxRootError):
        SandboxRoot.from_path(Path("C:foo"))


def test_rejects_unc_path() -> None:
    with pytest.raises(SandboxRootError):
        SandboxRoot.from_path(Path(r"\\localhost\share\folder"))


def test_rejects_symlink_root(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip(
            "symlink creation requires elevated privilege or Developer Mode on this host"
        )
    with pytest.raises(SandboxRootError):
        SandboxRoot.from_path(link)


def test_rejects_junction_root(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "junction"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
    )
    with pytest.raises(SandboxRootError):
        SandboxRoot.from_path(link)
