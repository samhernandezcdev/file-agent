"""Low-level per-table persistence operations.

Pure mechanical transaction participants: take an open Session, never call
commit()/begin(), and never catch/translate SQLAlchemy exceptions — that
translation happens in store.py only. The one deliberate exception:
insert_event raises IntegrityConstraintError directly if it detects an
internal invariant violation (a conflicting row reported by INSERT but
unfetchable by a subsequent SELECT). That isn't "translating" a SQLAlchemy
failure — it's this function refusing to silently return a nonsensical
outcome for a state that should be structurally impossible under correct
SQLite behavior. See FA-004 review M1.
"""

from collections.abc import Sequence
from enum import Enum, auto
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from file_agent.persistence.errors import IntegrityConstraintError
from file_agent.persistence.orm import DomainEventRow, FileObservationRow, ScanRow


def insert_scan(session: Session, row: ScanRow) -> None:
    session.add(row)
    session.flush()


def insert_file_observation(session: Session, row: FileObservationRow) -> None:
    session.add(row)
    session.flush()


def update_observation_hash(session: Session, id: UUID, sha256: str) -> int:
    """Unconditional update — sha256 is allowed to change more than once for the
    same id (re-hashing/re-verification). Returns the raw rowcount; the caller
    (FileAgentStore) decides what a 0 rowcount means."""
    result = cast(
        "CursorResult[Any]",
        session.execute(
            update(FileObservationRow)
            .where(FileObservationRow.id == id)
            .values(sha256=sha256)
        ),
    )
    return result.rowcount


class EventInsertOutcome(Enum):
    NEW = auto()
    DUPLICATE_IDENTICAL = auto()
    DUPLICATE_CONFLICTING = auto()


_EVENT_COMPARISON_FIELDS = (
    "event_type",
    "timestamp",
    "entity_type",
    "entity_id",
    "payload",
)


def insert_event(session: Session, row: DomainEventRow) -> EventInsertOutcome:
    """Race-free duplicate handling.

    Attempts INSERT ... ON CONFLICT(id) DO NOTHING first. If it actually
    inserted (rowcount == 1), the outcome is NEW. If it didn't (rowcount ==
    0), a row with this id already exists — inserted by us previously, or by
    a concurrent writer just now — so only THEN is the existing row fetched
    and compared. Ordering the insert attempt before the compare (rather
    than SELECT-then-INSERT) closes the race where a concurrent writer could
    insert the same id with different content between a naive
    check-then-act pair's two steps.

    Never raises for either duplicate-content case itself — returning an
    outcome and letting FileAgentStore decide keeps that exception-raising
    decision at the store boundary. The one exception: raises
    IntegrityConstraintError if the conflicting row cannot be fetched at
    all — see the module docstring.
    """
    stmt = (
        sqlite_insert(DomainEventRow)
        .values(
            id=row.id,
            event_type=row.event_type,
            timestamp=row.timestamp,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            payload=row.payload,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    result = cast("CursorResult[Any]", session.execute(stmt))
    if result.rowcount == 1:
        return EventInsertOutcome.NEW

    existing = session.get(DomainEventRow, row.id, populate_existing=True)
    if existing is None:
        raise IntegrityConstraintError(
            f"event id={row.id} vanished between INSERT and SELECT"
        )
    for field in _EVENT_COMPARISON_FIELDS:
        if getattr(existing, field) != getattr(row, field):
            return EventInsertOutcome.DUPLICATE_CONFLICTING
    return EventInsertOutcome.DUPLICATE_IDENTICAL


def select_scan(session: Session, id: UUID) -> ScanRow | None:
    return session.get(ScanRow, id)


def select_file_observation(session: Session, id: UUID) -> FileObservationRow | None:
    return session.get(FileObservationRow, id)


def select_file_observations_for_scan(
    session: Session, scan_id: UUID
) -> Sequence[FileObservationRow]:
    stmt = select(FileObservationRow).where(
        FileObservationRow.discovered_by_scan_id == scan_id
    )
    return session.execute(stmt).scalars().all()


def select_events_for_entity(
    session: Session, entity_type: str, entity_id: UUID
) -> Sequence[DomainEventRow]:
    stmt = (
        select(DomainEventRow)
        .where(
            DomainEventRow.entity_type == entity_type,
            DomainEventRow.entity_id == entity_id,
        )
        .order_by(DomainEventRow.timestamp.asc(), DomainEventRow.id.asc())
    )
    return session.execute(stmt).scalars().all()


def select_events_by_type(
    session: Session, event_type: str
) -> Sequence[DomainEventRow]:
    """SQL-level filter by event_type alone, across all entities -- added for
    FA-012: HUMAN_REVIEW_RECORDED events are keyed by the review's own id,
    never by policy_decision_id, so finding "the review(s) for this
    PolicyDecision" requires scanning by type and filtering payload
    client-side (see application/queries.py); there is no entity_id to look
    up directly the way select_events_for_entity assumes."""
    stmt = (
        select(DomainEventRow)
        .where(DomainEventRow.event_type == event_type)
        .order_by(DomainEventRow.timestamp.asc(), DomainEventRow.id.asc())
    )
    return session.execute(stmt).scalars().all()
