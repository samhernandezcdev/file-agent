"""FA-017.2: structural_safety.inspect_leaf -- fail-closed leaf
classification used by destination-setup's TOCTOU-safe create sequence.
One test per LeafState, plus fault-injection for INSPECTION_FAILED
(mirrors test_primitives.py's own established technique)."""

import subprocess
from pathlib import Path

import pytest

from file_agent.structural_safety import LeafState, inspect_leaf


def _make_junction(link: Path, target: Path) -> None:
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(
            f"mklink /J failed (not on Windows or no permission): {result.stderr}"
        )


def test_absent_path_is_absent(tmp_path: Path) -> None:
    assert inspect_leaf(tmp_path / "does_not_exist") is LeafState.ABSENT


def test_existing_directory_is_normal_directory(tmp_path: Path) -> None:
    target = tmp_path / "Documents"
    target.mkdir()
    assert inspect_leaf(target) is LeafState.NORMAL_DIRECTORY


def test_existing_regular_file_is_normal_file(tmp_path: Path) -> None:
    target = tmp_path / "Documents"
    target.write_bytes(b"a regular file")
    assert inspect_leaf(target) is LeafState.NORMAL_FILE


def test_symlink_is_reparse_point(tmp_path: Path) -> None:
    real_target = tmp_path / "real_dir"
    real_target.mkdir()
    link = tmp_path / "Documents"
    try:
        link.symlink_to(real_target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation requires elevated privilege or Developer Mode")

    assert inspect_leaf(link) is LeafState.REPARSE_POINT


def test_junction_is_reparse_point(tmp_path: Path) -> None:
    real_target = tmp_path / "real_dir"
    real_target.mkdir()
    link = tmp_path / "Documents"
    _make_junction(link, real_target)

    assert inspect_leaf(link) is LeafState.REPARSE_POINT


def test_stat_failure_is_inspection_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "Documents"
    target.mkdir()
    original_stat = __import__("os").stat

    def _raise_stat(path, *, follow_symlinks=True):  # type: ignore[no-untyped-def]
        if Path(path) == target:
            raise OSError("simulated inspection failure")
        return original_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr("file_agent.structural_safety.os.stat", _raise_stat)

    assert inspect_leaf(target) is LeafState.INSPECTION_FAILED


def test_is_symlink_failure_is_inspection_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "Documents"
    target.mkdir()
    original_is_symlink = Path.is_symlink

    def _raise_is_symlink(self: Path) -> bool:
        if self == target:
            raise OSError("simulated symlink-check failure")
        return original_is_symlink(self)

    monkeypatch.setattr(Path, "is_symlink", _raise_is_symlink)

    assert inspect_leaf(target) is LeafState.INSPECTION_FAILED
