"""SQLAlchemy 2.x typed-declarative schema for File Agent's audit store.

Not part of the public API of file_agent.persistence — callers interact
through FileAgentStore (store.py), never these row classes directly.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON as SA_JSON
from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


class GUIDText(TypeDecorator[UUID]):
    """UUID stored as canonical 36-char hyphenated TEXT.

    Chosen over SQLAlchemy's native Uuid type (which stores a 32-char
    no-hyphen hex string on non-native backends like SQLite) because this is
    meant to be an inspectable audit store: an operator should be able to
    paste a UUID straight out of a log line into a `sqlite3` query.
    """

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value: UUID | None, dialect: Any) -> str | None:
        return None if value is None else str(value)

    def process_result_value(self, value: str | None, dialect: Any) -> UUID | None:
        return None if value is None else UUID(value)


class UTCDateTimeText(TypeDecorator[datetime]):
    """Aware UTC datetime stored as ISO-8601 TEXT.

    SQLite has no timezone concept; reconstruction always produces an aware,
    explicitly-UTC datetime rather than relying on SQLite to preserve one.
    """

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(f"naive datetime cannot be persisted: {value!r}")
        return value.astimezone(UTC).isoformat()

    def process_result_value(self, value: str | None, dialect: Any) -> datetime | None:
        return None if value is None else datetime.fromisoformat(value).astimezone(UTC)


class ScanRow(Base):
    __tablename__ = "scans"

    id: Mapped[UUID] = mapped_column(GUIDText, primary_key=True)
    root_path: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTimeText, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTimeText, nullable=True
    )
    files_discovered: Mapped[int] = mapped_column(nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "files_discovered >= 0", name="ck_scans_files_discovered_nonneg"
        ),
        CheckConstraint(
            "status IN ('pending','running','completed','failed')",
            name="ck_scans_status_valid",
        ),
    )


class FileObservationRow(Base):
    __tablename__ = "file_observations"

    id: Mapped[UUID] = mapped_column(GUIDText, primary_key=True)
    path: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTimeText, nullable=False)
    modified_at: Mapped[datetime] = mapped_column(UTCDateTimeText, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(UTCDateTimeText, nullable=False)
    discovered_by_scan_id: Mapped[UUID | None] = mapped_column(
        GUIDText, ForeignKey("scans.id"), nullable=True
    )
    managed_root_id: Mapped[UUID | None] = mapped_column(
        GUIDText, ForeignKey("managed_roots.id"), nullable=True
    )
    """FA-015: nullable because every row created before the FA-015 migration
    permanently has no ManagedRoot lineage -- never retroactively backfilled
    (see application/managed_roots.py's module docstring). Set exactly once,
    at insert time, by DirectoryScanner's caller -- never mutated afterward
    (the codebase's only UPDATE against this table touches sha256 alone)."""

    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="ck_file_observations_size_nonneg"),
        CheckConstraint(
            "sha256 IS NULL OR length(sha256) = 64",
            name="ck_file_observations_sha256_len",
        ),
        Index("ix_file_observations_scan_id", "discovered_by_scan_id"),
        Index("ix_file_observations_path", "path"),
        Index("ix_file_observations_managed_root_id", "managed_root_id"),
    )


class ManagedRootRow(Base):
    """FA-015. Dedicated table, not event-sourced -- durable current
    configuration, queried on nearly every application/ call
    (analyze/plan/apply/list), which the generic event log would serve
    strictly worse. Soft-delete only (`removed_at`) -- a row is never
    hard-deleted and an id is never reused, so historical `managed_root_id`
    lineage in file_observations always resolves to something even for a
    long-removed root. See application/managed_roots.py for the full
    validation/resolution logic this table backs.
    """

    __tablename__ = "managed_roots"

    id: Mapped[UUID] = mapped_column(GUIDText, primary_key=True)
    path: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTimeText, nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(UTCDateTimeText, nullable=True)

    __table_args__ = (
        # Partial unique index: defense-in-depth against a race between two
        # concurrent add_managed_root calls (the primary mechanism is a
        # store-scoped lock, mirroring _review_lock_for). Deliberately scoped
        # to active rows only (removed_at IS NULL) so a removed root's path
        # can coexist with a new active registration of the same path --
        # application-level validation (see managed_roots.py) is the actual,
        # richer enforcement (this index alone cannot express Windows
        # canonical-path equivalence, overlap, or breadth-policy rules).
        Index(
            "ux_managed_roots_active_path",
            "path",
            unique=True,
            sqlite_where=text("removed_at IS NULL"),
        ),
    )


class DomainEventRow(Base):
    __tablename__ = "domain_events"

    id: Mapped[UUID] = mapped_column(GUIDText, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTimeText, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(GUIDText, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(SA_JSON, nullable=False)

    __table_args__ = (
        Index("ix_domain_events_entity", "entity_type", "entity_id"),
        Index("ix_domain_events_timestamp", "timestamp"),
    )
