"""Tests for FA-003's TOCTOU-adjacent error handling (design plan §5)."""

import builtins
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import file_agent.hasher.hasher as hasher_module
from file_agent.domain import DiscoveredFile
from file_agent.hasher import FileHasher, HashFailure
from file_agent.hasher.issues import HashIssueSeverity, HashIssueType
from file_agent.scanner import SandboxRoot


def test_file_disappeared_before_open(
    sandbox_dir: Path,
    sandbox_root: SandboxRoot,
    discovered_file_factory: Callable[[Path], DiscoveredFile],
) -> None:
    path = sandbox_dir / "gone.txt"
    path.write_bytes(b"x")
    discovered = discovered_file_factory(path)
    path.unlink()

    outcome = FileHasher(sandbox_root).hash_file(discovered)

    assert isinstance(outcome, HashFailure)
    assert outcome.issue.issue_type == HashIssueType.NOT_FOUND


def test_permission_denied_on_open(
    monkeypatch: pytest.MonkeyPatch,
    sandbox_dir: Path,
    sandbox_root: SandboxRoot,
    discovered_file_factory: Callable[[Path], DiscoveredFile],
) -> None:
    path = sandbox_dir / "locked.txt"
    path.write_bytes(b"x")
    discovered = discovered_file_factory(path)

    real_open = builtins.open

    def flaky_open(file: object, mode: str = "r", *args: Any, **kwargs: Any) -> object:
        if str(file) == str(path):
            raise PermissionError("denied")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(hasher_module, "open", flaky_open, raising=False)

    outcome = FileHasher(sandbox_root).hash_file(discovered)

    assert isinstance(outcome, HashFailure)
    assert outcome.issue.issue_type == HashIssueType.PERMISSION_DENIED


def test_modified_during_hash_detected(
    monkeypatch: pytest.MonkeyPatch,
    sandbox_dir: Path,
    sandbox_root: SandboxRoot,
    discovered_file_factory: Callable[[Path], DiscoveredFile],
) -> None:
    path = sandbox_dir / "a.txt"
    path.write_bytes(b"content")
    discovered = discovered_file_factory(path)

    real_fstat = hasher_module.os.fstat
    call_count = {"n": 0}

    class _ForgedStat:
        def __init__(self, real: Any) -> None:
            self.st_dev = real.st_dev
            self.st_ino = real.st_ino
            self.st_size = real.st_size + 1
            self.st_mtime = real.st_mtime + 1
            self.st_ctime = real.st_ctime

    def flaky_fstat(fd: int) -> Any:
        call_count["n"] += 1
        real = real_fstat(fd)
        # 1st call = Checkpoint 2 (opened handle) — must stay real so Check B passes.
        # 2nd call = Checkpoint 3 (post-read) — forged to simulate a change mid-read.
        if call_count["n"] >= 2:
            return _ForgedStat(real)
        return real

    monkeypatch.setattr(hasher_module.os, "fstat", flaky_fstat)

    outcome = FileHasher(sandbox_root).hash_file(discovered)

    assert isinstance(outcome, HashFailure)
    assert outcome.issue.issue_type == HashIssueType.MODIFIED_DURING_HASH


def test_path_outside_sandbox_rejected(
    tmp_path: Path,
    sandbox_root: SandboxRoot,
    discovered_file_factory: Callable[[Path], DiscoveredFile],
) -> None:
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_path = outside_dir / "a.txt"
    outside_path.write_bytes(b"x")
    discovered = discovered_file_factory(outside_path)

    outcome = FileHasher(sandbox_root).hash_file(discovered)

    assert isinstance(outcome, HashFailure)
    assert outcome.issue.issue_type == HashIssueType.PATH_OUTSIDE_SANDBOX
    assert outcome.issue.severity == HashIssueSeverity.CRITICAL


def test_intermediate_directory_replaced_by_escaping_junction_rejected(
    tmp_path: Path,
    sandbox_dir: Path,
    sandbox_root: SandboxRoot,
    discovered_file_factory: Callable[[Path], DiscoveredFile],
) -> None:
    sub = sandbox_dir / "sub"
    sub.mkdir()
    original = sub / "a.txt"
    original.write_bytes(b"original")
    discovered = discovered_file_factory(original)

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "a.txt").write_bytes(b"outside content")
    shutil.rmtree(sub)
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(sub), str(outside_dir)],
        check=True,
        capture_output=True,
    )

    outcome = FileHasher(sandbox_root).hash_file(discovered)

    assert isinstance(outcome, HashFailure)
    assert outcome.issue.issue_type == HashIssueType.PATH_OUTSIDE_SANDBOX


def test_file_replaced_by_symlink_rejected_without_opening(
    sandbox_dir: Path,
    sandbox_root: SandboxRoot,
    discovered_file_factory: Callable[[Path], DiscoveredFile],
) -> None:
    original = sandbox_dir / "a.txt"
    original.write_bytes(b"original")
    discovered = discovered_file_factory(original)

    other_target = sandbox_dir / "other.txt"
    other_target.write_bytes(b"other")
    original.unlink()
    try:
        original.symlink_to(other_target)
    except OSError:
        pytest.skip(
            "symlink creation requires elevated privilege or Developer Mode on this host"
        )

    outcome = FileHasher(sandbox_root).hash_file(discovered)

    assert isinstance(outcome, HashFailure)
    assert outcome.issue.issue_type == HashIssueType.REPARSE_POINT_ENCOUNTERED
