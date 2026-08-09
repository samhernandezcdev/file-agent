"""Proves classification composes with the existing FA-004 persistence API
with zero changes to file_agent.persistence."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from file_agent.classifier import classification_event, classify_file
from file_agent.domain import DiscoveredFile, EntityType, EventType
from file_agent.persistence import (
    AppPaths,
    FileAgentStore,
    create_engine_and_session_factory,
)
from file_agent.persistence.orm import Base


@pytest.fixture
def store(tmp_path: Path) -> Iterator[FileAgentStore]:
    config = AppPaths.from_root(tmp_path / "appdata")
    engine, session_factory = create_engine_and_session_factory(config)
    Base.metadata.create_all(engine)
    try:
        yield FileAgentStore(session_factory)
    finally:
        engine.dispose()


@pytest.fixture
def make_discovered_file() -> Callable[..., DiscoveredFile]:
    def _make(path: str, **overrides: object) -> DiscoveredFile:
        now = datetime.now(UTC)
        defaults: dict[str, object] = {
            "path": Path(path),
            "size_bytes": 10,
            "created_at": now,
            "modified_at": now,
        }
        defaults.update(overrides)
        return DiscoveredFile(**defaults)

    return _make


def test_classification_event_round_trips_through_record_event(
    store: FileAgentStore, make_discovered_file: Callable[..., DiscoveredFile]
) -> None:
    discovered = make_discovered_file("C:/sandbox/report.pdf")
    result = classify_file(discovered)
    event = classification_event(result)

    inserted = store.record_event(event)

    assert inserted is True
    events = store.list_events(EntityType.FILE, discovered.id)
    assert events == (event,)
    assert events[0].event_type is EventType.FILE_CLASSIFIED


def test_persisted_event_payload_includes_classifier_id(
    store: FileAgentStore, make_discovered_file: Callable[..., DiscoveredFile]
) -> None:
    discovered = make_discovered_file("C:/sandbox/Dockerfile")
    result = classify_file(discovered)
    event = classification_event(result)
    store.record_event(event)

    fetched = store.list_events(EntityType.FILE, discovered.id)[0]
    assert fetched.payload["classifier_id"] == result.classifier_id
    assert fetched.payload["category"] == result.category.value
    assert tuple(fetched.payload["reasons"]) == result.reasons


def test_repeated_classification_appends_history_not_overwrite(
    store: FileAgentStore, make_discovered_file: Callable[..., DiscoveredFile]
) -> None:
    discovered = make_discovered_file("C:/sandbox/mystery.unknownext")

    first_result = classify_file(discovered)
    first_event = classification_event(first_result)
    store.record_event(first_event)

    # simulate a later re-classification (e.g. after a rule-table update) --
    # a fresh DomainEvent.id makes this a genuinely new historical fact
    second_result = classify_file(discovered)
    second_event = classification_event(second_result)
    store.record_event(second_event)

    events = store.list_events(EntityType.FILE, discovered.id)
    assert len(events) == 2
    assert events[0].id != events[1].id
    assert all(e.event_type is EventType.FILE_CLASSIFIED for e in events)
