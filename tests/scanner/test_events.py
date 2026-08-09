"""Tests for FILE_DISCOVERED event emission."""

import json
from pathlib import Path

import pytest

from file_agent.domain import EntityType, EventType
from file_agent.scanner import DirectoryScanner, SandboxRoot


def test_one_event_per_discovered_file(sandbox_dir: Path) -> None:
    (sandbox_dir / "a.txt").write_text("a")
    (sandbox_dir / "b.txt").write_text("b")

    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root).run()

    assert len(result.events) == len(result.files) == 2
    for event in result.events:
        assert event.event_type is EventType.FILE_DISCOVERED
        assert event.entity_type is EntityType.FILE


def test_no_events_for_skipped_entries(sandbox_dir: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    link = sandbox_dir / "escape.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip(
            "symlink creation requires elevated privilege or Developer Mode on this host"
        )

    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root).run()

    assert result.events == ()


def test_event_entity_id_matches_discovered_file(sandbox_dir: Path) -> None:
    (sandbox_dir / "a.txt").write_text("a")
    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root).run()

    discovered = result.files[0]
    event = result.events[0]
    assert event.entity_id == discovered.id


def test_event_payload_is_minimal_and_json_serializable(sandbox_dir: Path) -> None:
    (sandbox_dir / "a.txt").write_text("a")
    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root).run()

    event = result.events[0]
    json.dumps(dict(event.payload))
    assert set(event.payload.keys()) == {"scan_id", "path"}
    assert event.payload["scan_id"] == str(result.scan_run.id)
    assert event.payload["path"] == str(result.files[0].path)
