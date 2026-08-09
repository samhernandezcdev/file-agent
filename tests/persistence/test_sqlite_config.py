"""Tests proving SQLite PRAGMAs are actually applied, not just configured."""

from sqlalchemy import text

from file_agent.persistence import AppPaths, create_engine_and_session_factory


def test_foreign_keys_enabled_on_independently_checked_out_connections(
    app_paths: AppPaths,
) -> None:
    engine, _ = create_engine_and_session_factory(app_paths)
    try:
        for _ in range(2):
            with engine.connect() as conn:
                value = conn.execute(text("PRAGMA foreign_keys")).scalar()
                assert value == 1
    finally:
        engine.dispose()


def test_wal_mode_enabled_for_file_backed_engine(app_paths: AppPaths) -> None:
    engine, _ = create_engine_and_session_factory(app_paths)
    try:
        with engine.connect() as conn:
            mode = conn.execute(text("PRAGMA journal_mode")).scalar()
        assert mode is not None
        assert mode.lower() == "wal"
    finally:
        engine.dispose()


def test_busy_timeout_configured(app_paths: AppPaths) -> None:
    engine, _ = create_engine_and_session_factory(app_paths)
    try:
        with engine.connect() as conn:
            timeout = conn.execute(text("PRAGMA busy_timeout")).scalar()
        assert timeout == 5000
    finally:
        engine.dispose()
