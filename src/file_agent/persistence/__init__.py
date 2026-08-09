"""Persistent audit store for File Agent's observations and event history.

Persists facts that already exist in the domain (scan runs, file
observations, domain events) to SQLite so they survive process exit. No
classification, proposals, or filesystem organization — the database is
application-owned state; managed user files remain read-only. See
docs/SAFETY.md's "Application-owned state" section.
"""

from file_agent.persistence.config import AppPaths
from file_agent.persistence.engine import (
    assert_schema_up_to_date,
    create_engine_and_session_factory,
)
from file_agent.persistence.errors import (
    DatabaseUnavailableError,
    IntegrityConstraintError,
    MappingError,
    PersistenceError,
    SchemaVersionMismatchError,
)
from file_agent.persistence.store import FileAgentStore

__all__ = [
    "AppPaths",
    "DatabaseUnavailableError",
    "FileAgentStore",
    "IntegrityConstraintError",
    "MappingError",
    "PersistenceError",
    "SchemaVersionMismatchError",
    "assert_schema_up_to_date",
    "create_engine_and_session_factory",
]
