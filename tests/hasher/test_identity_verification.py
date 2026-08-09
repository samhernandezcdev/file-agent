"""Tests for FileHasher's identity-verification chain (design plan §4)."""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

import file_agent.hasher.hasher as hasher_module
from file_agent.domain import DiscoveredFile
from file_agent.hasher import FileHasher, HashFailure
from file_agent.hasher.issues import HashIssueSeverity, HashIssueType
from file_agent.scanner import SandboxRoot


def test_size_mismatch_before_hash_rejected(
    sandbox_dir: Path,
    sandbox_root: SandboxRoot,
    discovered_file_factory: Callable[[Path], DiscoveredFile],
) -> None:
    path = sandbox_dir / "a.txt"
    path.write_bytes(b"original")
    discovered = discovered_file_factory(path)
    path.write_bytes(b"a different length now")

    outcome = FileHasher(sandbox_root).hash_file(discovered)

    assert isinstance(outcome, HashFailure)
    assert outcome.issue.issue_type == HashIssueType.METADATA_MISMATCH_BEFORE_HASH
    assert outcome.issue.severity == HashIssueSeverity.WARNING


def test_modified_at_mismatch_before_hash_rejected(
    sandbox_dir: Path,
    sandbox_root: SandboxRoot,
    discovered_file_factory: Callable[[Path], DiscoveredFile],
) -> None:
    path = sandbox_dir / "a.txt"
    path.write_bytes(b"content")
    discovered = discovered_file_factory(path)
    stale = discovered.model_copy(
        update={"modified_at": discovered.modified_at - timedelta(hours=1)}
    )

    outcome = FileHasher(sandbox_root).hash_file(stale)

    assert isinstance(outcome, HashFailure)
    assert outcome.issue.issue_type == HashIssueType.METADATA_MISMATCH_BEFORE_HASH


def test_created_at_mismatch_before_hash_rejected(
    sandbox_dir: Path,
    sandbox_root: SandboxRoot,
    discovered_file_factory: Callable[[Path], DiscoveredFile],
) -> None:
    path = sandbox_dir / "a.txt"
    path.write_bytes(b"content")
    discovered = discovered_file_factory(path)
    stale = discovered.model_copy(
        update={"created_at": discovered.created_at - timedelta(hours=1)}
    )

    outcome = FileHasher(sandbox_root).hash_file(stale)

    assert isinstance(outcome, HashFailure)
    assert outcome.issue.issue_type == HashIssueType.METADATA_MISMATCH_BEFORE_HASH


def test_identity_mismatch_on_open_is_warning_not_critical(
    monkeypatch: pytest.MonkeyPatch,
    sandbox_dir: Path,
    sandbox_root: SandboxRoot,
    discovered_file_factory: Callable[[Path], DiscoveredFile],
) -> None:
    path = sandbox_dir / "a.txt"
    path.write_bytes(b"content")
    discovered = discovered_file_factory(path)

    real_fstat = hasher_module.os.fstat

    class _ForgedStat:
        def __init__(self, real: Any) -> None:
            self.st_dev = real.st_dev
            self.st_ino = real.st_ino + 1  # forge a different identity
            self.st_size = real.st_size
            self.st_mtime = real.st_mtime
            self.st_ctime = real.st_ctime

    def forged_fstat(fd: int) -> Any:
        return _ForgedStat(real_fstat(fd))

    monkeypatch.setattr(hasher_module.os, "fstat", forged_fstat)

    outcome = FileHasher(sandbox_root).hash_file(discovered)

    assert isinstance(outcome, HashFailure)
    assert outcome.issue.issue_type == HashIssueType.IDENTITY_MISMATCH_ON_OPEN
    assert outcome.issue.severity == HashIssueSeverity.WARNING
    assert outcome.issue.issue_type != HashIssueType.PATH_OUTSIDE_SANDBOX
