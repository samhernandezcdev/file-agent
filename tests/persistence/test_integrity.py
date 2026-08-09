"""Tests for referential/uniqueness integrity and duplicate-event handling."""

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from file_agent.domain import (
    DiscoveredFile,
    DomainEvent,
    EntityType,
    EventType,
    ScanRun,
)
from file_agent.hasher import HashSuccess
from file_agent.persistence import FileAgentStore, mapping, repositories
from file_agent.persistence.errors import IntegrityConstraintError
from file_agent.persistence.repositories import EventInsertOutcome
from file_agent.scanner import ScanResult


def test_orphan_scan_id_rejected_by_foreign_key(
    store: FileAgentStore,
    make_completed_scan: Callable[..., ScanRun],
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    scan = make_completed_scan(files_discovered=1)
    orphan = make_discovered_file(
        scan_id=uuid4()
    )  # references a scan that never exists
    result = ScanResult(scan_run=scan, files=(orphan,), events=(), issues=())
    with pytest.raises(IntegrityConstraintError):
        store.record_scan(result)


def test_duplicate_scan_id_rejected(
    store: FileAgentStore, make_completed_scan: Callable[..., ScanRun]
) -> None:
    scan = make_completed_scan(files_discovered=0)
    store.record_scan(ScanResult(scan_run=scan, files=(), events=(), issues=()))
    with pytest.raises(IntegrityConstraintError):
        store.record_scan(ScanResult(scan_run=scan, files=(), events=(), issues=()))


def test_duplicate_event_identical_content_is_idempotent(
    store: FileAgentStore, make_event: Callable[..., DomainEvent]
) -> None:
    event = make_event()
    assert store.record_event(event) is True
    assert store.record_event(event) is False


def test_duplicate_event_different_content_raises(
    store: FileAgentStore, make_event: Callable[..., DomainEvent]
) -> None:
    event = make_event(payload={"a": 1})
    store.record_event(event)
    conflicting = make_event(id=event.id, payload={"a": 2})
    with pytest.raises(IntegrityConstraintError):
        store.record_event(conflicting)


def test_hash_success_for_never_persisted_observation_raises(
    store: FileAgentStore,
    make_discovered_file: Callable[..., DiscoveredFile],
    make_event: Callable[..., DomainEvent],
) -> None:
    orphan_original = make_discovered_file()
    hashed = orphan_original.with_sha256("a" * 64)
    event = make_event(
        event_type=EventType.FILE_HASHED,
        entity_type=EntityType.FILE,
        entity_id=hashed.id,
    )
    with pytest.raises(IntegrityConstraintError):
        store.record_hash_success(
            HashSuccess(original=orphan_original, hashed=hashed, event=event)
        )


def test_concurrent_duplicate_event_race_resolves_deterministically(
    store: FileAgentStore, make_event: Callable[..., DomainEvent]
) -> None:
    """Two threads race to insert the same event id with different content.

    Proves the INSERT-first algorithm (not a stale SELECT-then-INSERT
    pre-check) resolves correctly even under real concurrent execution:
    exactly one attempt succeeds, the other detects the conflict.
    """
    shared_id = uuid4()
    event_a = make_event(id=shared_id, payload={"which": "a"})
    event_b = make_event(id=shared_id, payload={"which": "b"})
    barrier = threading.Barrier(2)

    def attempt(event: DomainEvent) -> str:
        barrier.wait()
        try:
            store.record_event(event)
        except IntegrityConstraintError:
            return "conflicted"
        return "succeeded"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [event_a, event_b]))

    assert sorted(results) == ["conflicted", "succeeded"]


def test_insert_event_raises_when_conflicting_row_is_unfetchable(
    engine_and_sessions: tuple[Engine, sessionmaker[Session]],
    make_event: Callable[..., DomainEvent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test for FA-004 review M1.

    Simulates the "should never happen under correct SQLite behavior" state:
    INSERT ... ON CONFLICT DO NOTHING reports rowcount=0 (a conflicting row
    genuinely exists), but the subsequent fetch of that row returns None.
    Proves this raises IntegrityConstraintError rather than relying on an
    `assert`, which would silently no-op under `python -O`.
    """
    _, session_factory = engine_and_sessions
    event = make_event()
    session = session_factory()
    try:
        with session.begin():
            first_outcome = repositories.insert_event(
                session, mapping.event_to_row(event)
            )
        assert first_outcome is EventInsertOutcome.NEW

        # Force the real ON CONFLICT DO NOTHING path (rowcount=0) by reinserting
        # the same id, but make the row "vanish" for the follow-up fetch.
        monkeypatch.setattr(session, "get", lambda *args, **kwargs: None)
        with (
            pytest.raises(IntegrityConstraintError, match=str(event.id)),
            session.begin(),
        ):
            repositories.insert_event(session, mapping.event_to_row(event))
    finally:
        session.close()
