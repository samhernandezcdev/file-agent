"""Tests proving Alembic and the ORM metadata never drift, and that schema
version mismatches are actually detected."""

from collections.abc import Callable
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

from alembic import command
from file_agent.domain import DomainEvent, EntityType, EventType
from file_agent.hasher import HashSuccess
from file_agent.persistence import (
    AppPaths,
    FileAgentStore,
    create_engine_and_session_factory,
)
from file_agent.persistence.engine import assert_schema_up_to_date
from file_agent.persistence.errors import SchemaVersionMismatchError
from file_agent.persistence.orm import Base
from file_agent.scanner import ScanResult

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"


def test_alembic_head_matches_orm_metadata(tmp_path: Path) -> None:
    db_path = tmp_path / "migrated.sqlite3"
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            diff = compare_metadata(context, Base.metadata)
        assert diff == []
        assert_schema_up_to_date(engine, alembic_ini_path=_ALEMBIC_INI)
    finally:
        engine.dispose()


def test_schema_version_mismatch_detected(tmp_path: Path) -> None:
    db_path = tmp_path / "unmigrated.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect():
            pass  # creates the file but applies no migrations
        with pytest.raises(SchemaVersionMismatchError):
            assert_schema_up_to_date(engine, alembic_ini_path=_ALEMBIC_INI)
    finally:
        engine.dispose()


def test_migration_backed_database_is_operational_with_file_agent_store(
    tmp_path: Path,
    make_scan_result: Callable[..., ScanResult],
    make_event: Callable[..., DomainEvent],
) -> None:
    """End-to-end check for FA-004 review M2.

    A database initialized ONLY via `alembic upgrade head` — never
    Base.metadata.create_all() — is fully operational through the real
    FileAgentStore. The rest of the suite keeps using create_all() for
    speed; this is the single dedicated test proving the actual migration
    path produces a schema FileAgentStore can use.
    """
    config = AppPaths.from_root(tmp_path / "appdata")
    config.root.mkdir(parents=True, exist_ok=True)

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{config.database_path}")
    command.upgrade(cfg, "head")

    engine, session_factory = create_engine_and_session_factory(config)
    try:
        store = FileAgentStore(session_factory)

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

        fetched_scan = store.get_scan(result.scan_run.id)
        assert fetched_scan == result.scan_run

        fetched_file = store.get_discovered_file(original.id)
        assert fetched_file is not None
        assert fetched_file.sha256 == hashed.sha256

        events = store.list_events(EntityType.FILE, original.id)
        assert [e.event_type for e in events] == [
            EventType.FILE_DISCOVERED,
            EventType.FILE_HASHED,
        ]
    finally:
        engine.dispose()
