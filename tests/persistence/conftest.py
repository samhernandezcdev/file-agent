"""Shared fixtures for persistence tests."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from file_agent.domain import (
    DiscoveredFile,
    DomainEvent,
    EntityType,
    EventType,
    ScanRun,
    ScanStatus,
)
from file_agent.persistence import (
    AppPaths,
    FileAgentStore,
    create_engine_and_session_factory,
)
from file_agent.persistence.orm import Base
from file_agent.scanner import ScanResult


@pytest.fixture
def app_paths(tmp_path: Path) -> AppPaths:
    return AppPaths.from_root(tmp_path / "appdata")


@pytest.fixture
def engine_and_sessions(
    app_paths: AppPaths,
) -> Iterator[tuple[Engine, sessionmaker[Session]]]:
    engine, session_factory = create_engine_and_session_factory(app_paths)
    Base.metadata.create_all(engine)
    try:
        yield engine, session_factory
    finally:
        engine.dispose()


@pytest.fixture
def store(engine_and_sessions: tuple[Engine, sessionmaker[Session]]) -> FileAgentStore:
    _, session_factory = engine_and_sessions
    return FileAgentStore(session_factory)


@pytest.fixture
def make_scan() -> Callable[..., ScanRun]:
    def _make(**overrides: object) -> ScanRun:
        defaults: dict[str, object] = {
            "root_path": Path("C:/sandbox"),
            "started_at": datetime.now(UTC),
        }
        defaults.update(overrides)
        return ScanRun(**defaults)

    return _make


@pytest.fixture
def make_completed_scan(make_scan: Callable[..., ScanRun]) -> Callable[..., ScanRun]:
    def _make(files_discovered: int = 0, **overrides: object) -> ScanRun:
        scan = make_scan(**overrides)
        return scan.evolve(
            status=ScanStatus.COMPLETED,
            completed_at=scan.started_at + timedelta(seconds=1),
            files_discovered=files_discovered,
        )

    return _make


@pytest.fixture
def make_discovered_file() -> Callable[..., DiscoveredFile]:
    def _make(scan_id: UUID | None = None, **overrides: object) -> DiscoveredFile:
        now = datetime.now(UTC)
        defaults: dict[str, object] = {
            "path": Path(f"C:/sandbox/{uuid4().hex}.txt"),
            "size_bytes": 10,
            "created_at": now,
            "modified_at": now,
            "discovered_by_scan_id": scan_id,
        }
        defaults.update(overrides)
        return DiscoveredFile(**defaults)

    return _make


@pytest.fixture
def make_event() -> Callable[..., DomainEvent]:
    def _make(**overrides: object) -> DomainEvent:
        defaults: dict[str, object] = {
            "event_type": EventType.FILE_DISCOVERED,
            "entity_type": EntityType.FILE,
            "entity_id": uuid4(),
        }
        defaults.update(overrides)
        return DomainEvent(**defaults)

    return _make


@pytest.fixture
def make_scan_result(
    make_completed_scan: Callable[..., ScanRun],
    make_discovered_file: Callable[..., DiscoveredFile],
    make_event: Callable[..., DomainEvent],
) -> Callable[..., ScanResult]:
    def _make(file_count: int = 1) -> ScanResult:
        scan = make_completed_scan(files_discovered=file_count)
        files = tuple(make_discovered_file(scan_id=scan.id) for _ in range(file_count))
        events = tuple(
            make_event(
                event_type=EventType.FILE_DISCOVERED,
                entity_type=EntityType.FILE,
                entity_id=f.id,
                payload={"scan_id": str(scan.id), "path": str(f.path)},
            )
            for f in files
        )
        return ScanResult(scan_run=scan, files=files, events=events, issues=())

    return _make
