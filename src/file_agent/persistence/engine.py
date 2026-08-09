"""Engine/session-factory construction, SQLite PRAGMA wiring, and schema-version checking.

The one filesystem-mutation call in this whole package lives here
(config.root.mkdir) — see the AST guardrail in tests/persistence.
"""

from pathlib import Path
from typing import Any

from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from file_agent.persistence.config import AppPaths
from file_agent.persistence.errors import (
    DatabaseUnavailableError,
    SchemaVersionMismatchError,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"


def _set_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA busy_timeout = 5000")
    cursor.close()


def create_engine_and_session_factory(
    config: AppPaths,
) -> tuple[Engine, sessionmaker[Session]]:
    """Bootstraps the app-data root and returns a shared Engine + sessionmaker.

    Only ever creates directories at ``config.root`` — never anywhere else.
    """
    try:
        config.root.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{config.database_path}")
        event.listen(engine, "connect", _set_sqlite_pragmas)
        with engine.connect():
            pass  # fail fast if the database genuinely can't be opened
    except (OSError, OperationalError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc
    session_factory = sessionmaker(bind=engine)
    return engine, session_factory


def assert_schema_up_to_date(
    engine: Engine, alembic_ini_path: Path = DEFAULT_ALEMBIC_INI
) -> None:
    """Raises SchemaVersionMismatchError if the database's Alembic head differs
    from the code's expected head — including if migrations were never run at
    all. Never runs a migration itself.
    """
    cfg = AlembicConfig(str(alembic_ini_path))
    script = ScriptDirectory.from_config(cfg)
    expected_head = script.get_current_head()

    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        actual_revision = context.get_current_revision()

    if actual_revision != expected_head:
        raise SchemaVersionMismatchError(
            f"database schema revision {actual_revision!r} does not match "
            f"expected revision {expected_head!r}; run `alembic upgrade head`"
        )
