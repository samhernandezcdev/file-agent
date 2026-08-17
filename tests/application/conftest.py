"""Shared fixtures for application tests.

Uses real files under a real sandbox, a real disjoint app-data root, and a
real SQLite-backed FileAgentStore (tmp_path) -- mocks are avoided entirely,
matching this codebase's established convention.
"""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from file_agent.application import FileAgentApplicationService
from file_agent.destination import PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY
from file_agent.domain import DomainEvent, EventType
from file_agent.persistence import (
    AppPaths,
    FileAgentStore,
    create_engine_and_session_factory,
)
from file_agent.persistence.errors import DatabaseUnavailableError
from file_agent.persistence.orm import Base
from file_agent.scanner import SandboxRoot


class FailOnEventType:
    """Wraps a real FileAgentStore, forwarding everything except
    record_event -- which raises DatabaseUnavailableError for any event
    whose event_type is in `fail_on`. Used to force the REQUESTED-persist-
    failure and terminal-persist-failure (TerminalPersistenceError) crash
    windows deterministically in tests."""

    def __init__(self, store: FileAgentStore, fail_on: set[EventType]) -> None:
        self._store = store
        self._fail_on = fail_on

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    def record_event(self, event: DomainEvent) -> bool:
        if event.event_type in self._fail_on:
            raise DatabaseUnavailableError(
                f"simulated failure persisting {event.event_type}"
            )
        return self._store.record_event(event)


@pytest.fixture
def sandbox_root(tmp_path: Path) -> SandboxRoot:
    root = tmp_path / "sandbox"
    root.mkdir()
    for directory in PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY.values():
        (root / directory).mkdir()
    return SandboxRoot.from_path(root)


@pytest.fixture
def app_paths(tmp_path: Path) -> AppPaths:
    return AppPaths.from_root(tmp_path / "appdata")


@pytest.fixture
def store(tmp_path: Path) -> Iterator[FileAgentStore]:
    config = AppPaths.from_root(tmp_path / "store_appdata")
    engine, session_factory = create_engine_and_session_factory(config)
    Base.metadata.create_all(engine)
    try:
        yield FileAgentStore(session_factory)
    finally:
        engine.dispose()


@pytest.fixture
def service(app_paths: AppPaths, store: FileAgentStore) -> FileAgentApplicationService:
    return FileAgentApplicationService(app_paths, store)


@pytest.fixture
def managed_root_id(
    service: FileAgentApplicationService, sandbox_root: SandboxRoot
) -> UUID:
    """Registers `sandbox_root` as this test's one active ManagedRoot --
    the FA-015 drop-in replacement for the old bare `analyze_scan()`
    convenience: tests call `service.analyze_managed_root(managed_root_id)`
    instead. A separate, dedicated fixture (not folded into `service`
    itself) so trust-boundary/registration-specific tests can still get a
    bare `service` with zero pre-registered roots."""
    return service.add_managed_root(sandbox_root.path).id


@pytest.fixture
def make_source_file(sandbox_root: SandboxRoot) -> Callable[..., Path]:
    def _make(name: str = "report.txt", content: bytes = b"hello world") -> Path:
        path = sandbox_root.path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    return _make
