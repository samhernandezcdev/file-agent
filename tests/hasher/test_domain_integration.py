"""Tests for FileHasher's use of DiscoveredFile.with_sha256() and immutability."""

from collections.abc import Callable
from pathlib import Path

from file_agent.domain import DiscoveredFile
from file_agent.hasher import FileHasher, HashFailure, HashSuccess
from file_agent.scanner import SandboxRoot


def test_hashed_preserves_id_and_fields(
    sandbox_dir: Path,
    sandbox_root: SandboxRoot,
    discovered_file_factory: Callable[[Path], DiscoveredFile],
) -> None:
    path = sandbox_dir / "a.txt"
    path.write_bytes(b"content")
    discovered = discovered_file_factory(path)

    outcome = FileHasher(sandbox_root).hash_file(discovered)

    assert isinstance(outcome, HashSuccess)
    assert outcome.hashed.id == discovered.id
    assert outcome.hashed.path == discovered.path
    assert outcome.hashed.size_bytes == discovered.size_bytes
    assert outcome.hashed.created_at == discovered.created_at
    assert outcome.hashed.modified_at == discovered.modified_at
    assert outcome.hashed.sha256 is not None


def test_original_unchanged_on_success(
    sandbox_dir: Path,
    sandbox_root: SandboxRoot,
    discovered_file_factory: Callable[[Path], DiscoveredFile],
) -> None:
    path = sandbox_dir / "a.txt"
    path.write_bytes(b"content")
    discovered = discovered_file_factory(path)

    outcome = FileHasher(sandbox_root).hash_file(discovered)

    assert isinstance(outcome, HashSuccess)
    assert discovered.sha256 is None  # original instance untouched
    assert outcome.original is discovered


def test_original_unchanged_on_failure(
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
    assert outcome.original is discovered
    assert discovered.sha256 is None
