"""Tests for FILE_HASHED event emission."""

import json
from collections.abc import Callable
from pathlib import Path

from file_agent.domain import DiscoveredFile, EntityType, EventType
from file_agent.hasher import FileHasher, HashFailure, HashSuccess
from file_agent.scanner import SandboxRoot


def test_file_hashed_event_on_success(
    sandbox_dir: Path,
    sandbox_root: SandboxRoot,
    discovered_file_factory: Callable[[Path], DiscoveredFile],
) -> None:
    path = sandbox_dir / "a.txt"
    path.write_bytes(b"content")
    discovered = discovered_file_factory(path)

    outcome = FileHasher(sandbox_root).hash_file(discovered)

    assert isinstance(outcome, HashSuccess)
    assert outcome.event.event_type is EventType.FILE_HASHED
    assert outcome.event.entity_type is EntityType.FILE
    assert outcome.event.entity_id == outcome.hashed.id
    json.dumps(dict(outcome.event.payload))
    assert set(outcome.event.payload.keys()) == {"sha256", "path"}
    assert outcome.event.payload["sha256"] == outcome.hashed.sha256
    assert outcome.event.payload["path"] == str(discovered.path)


def test_no_event_on_failure(
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
    assert not hasattr(outcome, "event")
