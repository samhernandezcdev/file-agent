"""The public persistence error taxonomy.

Raw SQLAlchemy/sqlite3 exceptions never cross the persistence package
boundary — only these five types do. See store.py for the exact translation
boundary (only inside FileAgentStore, never in repositories.py).
"""


class PersistenceError(Exception):
    """Base class for all persistence errors. Never raised directly."""


class DatabaseUnavailableError(PersistenceError):
    """The database could not be opened or connected to."""


class IntegrityConstraintError(PersistenceError):
    """A referential/uniqueness/check constraint was violated, or an
    application-level integrity rule was broken (e.g. hashing an observation
    that was never persisted, or an event id colliding with different
    content)."""


class MappingError(PersistenceError):
    """A domain<->row translation failure. Always a bug in this package, not
    a caller-input problem — e.g. a persisted enum value with no matching
    Python enum member, or a datetime string that fails to parse."""


class SchemaVersionMismatchError(PersistenceError):
    """The database's current Alembic revision does not match the revision
    this codebase expects. No automatic migration is ever run to resolve
    this from a production code path."""
