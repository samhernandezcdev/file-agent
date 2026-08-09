"""Tests for FileHasher's core hashing correctness."""

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

from file_agent.domain import DiscoveredFile
from file_agent.hasher import FileHasher, HashSuccess
from file_agent.scanner import SandboxRoot


@pytest.mark.parametrize(
    ("content", "expected_sha256"),
    [
        (b"", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
        (b"abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
    ],
)
def test_known_sha256_vectors(
    sandbox_dir: Path,
    sandbox_root: SandboxRoot,
    discovered_file_factory: Callable[[Path], DiscoveredFile],
    content: bytes,
    expected_sha256: str,
) -> None:
    path = sandbox_dir / "vector.bin"
    path.write_bytes(content)
    discovered = discovered_file_factory(path)

    outcome = FileHasher(sandbox_root).hash_file(discovered)

    assert isinstance(outcome, HashSuccess)
    assert outcome.hashed.sha256 == expected_sha256


def test_empty_file(
    sandbox_dir: Path,
    sandbox_root: SandboxRoot,
    discovered_file_factory: Callable[[Path], DiscoveredFile],
) -> None:
    path = sandbox_dir / "empty.txt"
    path.write_bytes(b"")
    discovered = discovered_file_factory(path)

    outcome = FileHasher(sandbox_root).hash_file(discovered)

    assert isinstance(outcome, HashSuccess)
    assert outcome.hashed.sha256 == hashlib.sha256(b"").hexdigest()


def test_large_streamed_file(
    sandbox_dir: Path,
    sandbox_root: SandboxRoot,
    discovered_file_factory: Callable[[Path], DiscoveredFile],
) -> None:
    path = sandbox_dir / "large.bin"
    chunk = b"0123456789abcdef" * 64 * 1024  # 1 MiB
    with path.open("wb") as f:
        for _ in range(8):  # ~8 MiB
            f.write(chunk)
    discovered = discovered_file_factory(path)

    outcome = FileHasher(sandbox_root).hash_file(discovered)

    assert isinstance(outcome, HashSuccess)
    expected = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            expected.update(block)
    assert outcome.hashed.sha256 == expected.hexdigest()
