"""Tests proving repeated scans/observations never silently overwrite history."""

from collections.abc import Callable
from pathlib import Path

from file_agent.domain import (
    DiscoveredFile,
    DomainEvent,
    EntityType,
    EventType,
    ScanRun,
)
from file_agent.hasher import HashSuccess
from file_agent.persistence import FileAgentStore
from file_agent.scanner import ScanResult


def test_repeated_scans_of_same_path_do_not_overwrite_unrelated_observations(
    store: FileAgentStore,
    make_completed_scan: Callable[..., ScanRun],
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    shared_path = Path("C:/sandbox/report.pdf")

    scan1 = make_completed_scan(files_discovered=1)
    file1 = make_discovered_file(scan_id=scan1.id, path=shared_path)
    store.record_scan(ScanResult(scan_run=scan1, files=(file1,), events=(), issues=()))

    scan2 = make_completed_scan(files_discovered=1)
    file2 = make_discovered_file(scan_id=scan2.id, path=shared_path)
    store.record_scan(ScanResult(scan_run=scan2, files=(file2,), events=(), issues=()))

    assert file1.id != file2.id
    fetched1 = store.get_discovered_file(file1.id)
    fetched2 = store.get_discovered_file(file2.id)
    assert fetched1 == file1
    assert fetched2 == file2
    assert fetched1 is not None and fetched2 is not None
    assert fetched1.path == fetched2.path == shared_path


def test_two_different_ids_can_share_identical_sha256(
    store: FileAgentStore,
    make_scan_result: Callable[..., ScanResult],
    make_event: Callable[..., DomainEvent],
) -> None:
    result = make_scan_result(file_count=2)
    store.record_scan(result)
    same_hash = "b" * 64
    for original in result.files:
        hashed = original.with_sha256(same_hash)
        event = make_event(
            event_type=EventType.FILE_HASHED,
            entity_type=EntityType.FILE,
            entity_id=hashed.id,
            payload={"sha256": same_hash, "path": str(hashed.path)},
        )
        store.record_hash_success(
            HashSuccess(original=original, hashed=hashed, event=event)
        )

    fetched = [store.get_discovered_file(f.id) for f in result.files]
    assert all(f is not None and f.sha256 == same_hash for f in fetched)
    assert len({f.id for f in fetched if f is not None}) == 2


def test_rehash_lifecycle_appends_events_and_updates_materialized_hash(
    store: FileAgentStore,
    make_scan_result: Callable[..., ScanResult],
    make_event: Callable[..., DomainEvent],
) -> None:
    result = make_scan_result(file_count=1)
    store.record_scan(result)
    original = result.files[0]

    hash_a = "a" * 64
    hashed_a = original.with_sha256(hash_a)
    event_a = make_event(
        event_type=EventType.FILE_HASHED,
        entity_type=EntityType.FILE,
        entity_id=hashed_a.id,
        payload={"sha256": hash_a, "path": str(hashed_a.path)},
    )
    store.record_hash_success(
        HashSuccess(original=original, hashed=hashed_a, event=event_a)
    )

    hash_b = "b" * 64
    hashed_b = hashed_a.with_sha256(hash_b)
    event_b = make_event(
        event_type=EventType.FILE_HASHED,
        entity_type=EntityType.FILE,
        entity_id=hashed_b.id,
        payload={"sha256": hash_b, "path": str(hashed_b.path)},
    )
    store.record_hash_success(
        HashSuccess(original=hashed_a, hashed=hashed_b, event=event_b)
    )

    fetched = store.get_discovered_file(original.id)
    assert fetched is not None
    assert fetched.sha256 == hash_b

    events = store.list_events(EntityType.FILE, original.id)
    event_types = [e.event_type for e in events]
    assert event_types == [
        EventType.FILE_DISCOVERED,
        EventType.FILE_HASHED,
        EventType.FILE_HASHED,
    ]
    assert events[1].payload["sha256"] == hash_a
    assert events[2].payload["sha256"] == hash_b


def test_same_hash_reverification_still_appends_new_event(
    store: FileAgentStore,
    make_scan_result: Callable[..., ScanResult],
    make_event: Callable[..., DomainEvent],
) -> None:
    result = make_scan_result(file_count=1)
    store.record_scan(result)
    original = result.files[0]
    same_hash = "c" * 64

    hashed = original.with_sha256(same_hash)
    event1 = make_event(
        event_type=EventType.FILE_HASHED,
        entity_type=EntityType.FILE,
        entity_id=hashed.id,
        payload={"sha256": same_hash, "path": str(hashed.path)},
    )
    store.record_hash_success(
        HashSuccess(original=original, hashed=hashed, event=event1)
    )

    # re-verification: same hash, but a fresh event (FileHasher always constructs a new
    # DomainEvent with its own id/timestamp per hashing attempt)
    event2 = make_event(
        event_type=EventType.FILE_HASHED,
        entity_type=EntityType.FILE,
        entity_id=hashed.id,
        payload={"sha256": same_hash, "path": str(hashed.path)},
    )
    store.record_hash_success(HashSuccess(original=hashed, hashed=hashed, event=event2))

    events = store.list_events(EntityType.FILE, original.id)
    hashed_events = [e for e in events if e.event_type is EventType.FILE_HASHED]
    assert len(hashed_events) == 2
    assert hashed_events[0].id != hashed_events[1].id
