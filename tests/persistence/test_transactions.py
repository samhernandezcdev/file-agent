"""Tests proving atomicity: a failure partway through a use case leaves no partial state."""

from collections.abc import Callable
from unittest.mock import patch

import pytest

from file_agent.domain import DomainEvent, EntityType, EventType
from file_agent.hasher import HashSuccess
from file_agent.persistence import FileAgentStore
from file_agent.scanner import ScanResult


def test_hash_success_rollback_leaves_no_partial_state(
    store: FileAgentStore,
    make_scan_result: Callable[..., ScanResult],
    make_event: Callable[..., DomainEvent],
) -> None:
    result = make_scan_result(file_count=1)
    store.record_scan(result)
    original = result.files[0]
    hashed = original.with_sha256("a" * 64)
    event = make_event(
        event_type=EventType.FILE_HASHED,
        entity_type=EntityType.FILE,
        entity_id=hashed.id,
        payload={"sha256": hashed.sha256, "path": str(hashed.path)},
    )
    outcome = HashSuccess(original=original, hashed=hashed, event=event)

    def failing_insert_event(session: object, row: object) -> None:
        raise RuntimeError("simulated failure between the two writes")

    with (
        patch(
            "file_agent.persistence.repositories.insert_event",
            side_effect=failing_insert_event,
        ),
        pytest.raises(RuntimeError),
    ):
        store.record_hash_success(outcome)

    # rollback must have discarded the sha256 update too — the two writes are one transaction
    fetched = store.get_discovered_file(original.id)
    assert fetched is not None
    assert fetched.sha256 is None
    events = store.list_events(EntityType.FILE, original.id)
    assert not any(e.event_type is EventType.FILE_HASHED for e in events)


def test_record_scan_rollback_leaves_no_partial_state(
    store: FileAgentStore, make_scan_result: Callable[..., ScanResult]
) -> None:
    result = make_scan_result(file_count=2)

    def failing_insert_file_observation(session: object, row: object) -> None:
        raise RuntimeError("simulated failure partway through inserting observations")

    with (
        patch(
            "file_agent.persistence.repositories.insert_file_observation",
            side_effect=failing_insert_file_observation,
        ),
        pytest.raises(RuntimeError),
    ):
        store.record_scan(result)

    assert store.get_scan(result.scan_run.id) is None
    for discovered in result.files:
        assert store.get_discovered_file(discovered.id) is None
