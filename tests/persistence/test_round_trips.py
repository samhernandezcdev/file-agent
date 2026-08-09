"""Basic round-trip tests for each domain type FA-004 persists."""

from collections.abc import Callable

from file_agent.domain import DomainEvent, EntityType, EventType
from file_agent.hasher import HashSuccess
from file_agent.persistence import FileAgentStore
from file_agent.scanner import ScanResult


def test_scan_run_round_trip(
    store: FileAgentStore, make_scan_result: Callable[..., ScanResult]
) -> None:
    result = make_scan_result(file_count=0)
    store.record_scan(result)
    fetched = store.get_scan(result.scan_run.id)
    assert fetched == result.scan_run


def test_discovered_file_round_trip_before_hashing(
    store: FileAgentStore, make_scan_result: Callable[..., ScanResult]
) -> None:
    result = make_scan_result(file_count=1)
    store.record_scan(result)
    original = result.files[0]
    fetched = store.get_discovered_file(original.id)
    assert fetched == original
    assert fetched is not None
    assert fetched.sha256 is None


def test_discovered_file_round_trip_after_hashing(
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
    store.record_hash_success(
        HashSuccess(original=original, hashed=hashed, event=event)
    )

    fetched = store.get_discovered_file(original.id)
    assert fetched == hashed
    assert fetched is not None
    assert fetched.sha256 == "a" * 64


def test_domain_event_round_trip(
    store: FileAgentStore, make_event: Callable[..., DomainEvent]
) -> None:
    event = make_event(payload={"a": 1, "tags": ["x", "y"]})
    store.record_event(event)
    events = store.list_events(event.entity_type, event.entity_id)
    assert events == (event,)
