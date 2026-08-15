"""FileAgentStore — the public, use-case-shaped persistence service.

Owns the Session, all transaction boundaries, and all exception translation
into the public error taxonomy (errors.py). repositories.py functions never
commit and never translate exceptions — see the module docstrings there.

Exception-translation shape, used by every write method below: application-
level integrity checks (a missing observation, a conflicting event) raise
IntegrityConstraintError directly from INSIDE the `with session.begin():`
block, because only an exception escaping that block triggers its rollback.
The `except IntegrityError`/`except OperationalError` clauses exist only to
translate raw SQLAlchemy exceptions that this code never explicitly raises
(e.g. a CHECK/FK violation firing during flush) — by the time execution
reaches any except clause, session.begin()'s rollback has already run, for
either kind of exception, guaranteed by `with`'s unwind order.
"""

from uuid import UUID

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from file_agent.domain import (
    DiscoveredFile,
    DomainEvent,
    EntityType,
    EventType,
    ScanRun,
)
from file_agent.hasher import HashSuccess
from file_agent.persistence import mapping, repositories
from file_agent.persistence.errors import (
    DatabaseUnavailableError,
    IntegrityConstraintError,
)
from file_agent.persistence.repositories import EventInsertOutcome
from file_agent.scanner import ScanResult


class FileAgentStore:
    """The public persistence API. Never exposes a raw SQLAlchemy Session."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record_scan(self, result: ScanResult) -> None:
        """Atomically persists result.scan_run, every DiscoveredFile in result.files,
        and every FILE_DISCOVERED event in result.events. result.issues is
        intentionally not persisted (design plan §13)."""
        session = self._session_factory()
        try:
            with session.begin():
                repositories.insert_scan(session, mapping.scan_to_row(result.scan_run))
                for discovered in result.files:
                    repositories.insert_file_observation(
                        session, mapping.discovered_file_to_row(discovered)
                    )
                for domain_event in result.events:
                    outcome = repositories.insert_event(
                        session, mapping.event_to_row(domain_event)
                    )
                    if outcome is EventInsertOutcome.DUPLICATE_CONFLICTING:
                        raise IntegrityConstraintError(
                            f"event id={domain_event.id} already exists with different content"
                        )
        except IntegrityError as exc:
            raise IntegrityConstraintError(str(exc)) from exc
        except OperationalError as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        finally:
            session.close()

    def record_hash_success(self, outcome: HashSuccess) -> None:
        """Atomically updates the existing observation's sha256 (allowed to change
        more than once — re-hashing/re-verification is legitimate, per FA-001.1)
        and appends outcome.event as a new FILE_HASHED row."""
        session = self._session_factory()
        sha256 = outcome.hashed.sha256
        assert sha256 is not None, "HashSuccess.hashed always carries a computed sha256"
        try:
            with session.begin():
                rowcount = repositories.update_observation_hash(
                    session, id=outcome.hashed.id, sha256=sha256
                )
                if rowcount == 0:
                    raise IntegrityConstraintError(
                        f"no persisted observation with id={outcome.hashed.id}; "
                        "record_scan must run before record_hash_success"
                    )
                event_outcome = repositories.insert_event(
                    session, mapping.event_to_row(outcome.event)
                )
                if event_outcome is EventInsertOutcome.DUPLICATE_CONFLICTING:
                    raise IntegrityConstraintError(
                        f"event id={outcome.event.id} already exists with different content"
                    )
        except IntegrityError as exc:
            raise IntegrityConstraintError(str(exc)) from exc
        except OperationalError as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        finally:
            session.close()

    def record_event(self, event: DomainEvent) -> bool:
        """Duplicate-aware append of a standalone event. True if newly inserted,
        False if an identical event with this id already existed. Raises
        IntegrityConstraintError if this id already exists with different content."""
        session = self._session_factory()
        try:
            with session.begin():
                outcome = repositories.insert_event(
                    session, mapping.event_to_row(event)
                )
                if outcome is EventInsertOutcome.DUPLICATE_CONFLICTING:
                    raise IntegrityConstraintError(
                        f"event id={event.id} already exists with different content"
                    )
                return outcome is EventInsertOutcome.NEW
        except IntegrityError as exc:
            raise IntegrityConstraintError(str(exc)) from exc
        except OperationalError as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        finally:
            session.close()

    def get_scan(self, scan_id: UUID) -> ScanRun | None:
        session = self._session_factory()
        try:
            row = repositories.select_scan(session, scan_id)
            return None if row is None else mapping.row_to_scan(row)
        except OperationalError as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        finally:
            session.close()

    def get_discovered_file(self, file_id: UUID) -> DiscoveredFile | None:
        session = self._session_factory()
        try:
            row = repositories.select_file_observation(session, file_id)
            return None if row is None else mapping.row_to_discovered_file(row)
        except OperationalError as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        finally:
            session.close()

    def list_discovered_files(self, scan_id: UUID) -> tuple[DiscoveredFile, ...]:
        session = self._session_factory()
        try:
            rows = repositories.select_file_observations_for_scan(session, scan_id)
            return tuple(mapping.row_to_discovered_file(row) for row in rows)
        except OperationalError as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        finally:
            session.close()

    def list_events(
        self, entity_type: EntityType, entity_id: UUID
    ) -> tuple[DomainEvent, ...]:
        """Ordered by (timestamp ASC, id ASC) — deterministic even for equal timestamps."""
        session = self._session_factory()
        try:
            rows = repositories.select_events_for_entity(
                session, entity_type.value, entity_id
            )
            return tuple(mapping.row_to_event(row) for row in rows)
        except OperationalError as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        finally:
            session.close()

    def list_events_by_type(self, event_type: EventType) -> tuple[DomainEvent, ...]:
        """Ordered by (timestamp ASC, id ASC), across all entities. See
        repositories.select_events_by_type for why this exists."""
        session = self._session_factory()
        try:
            rows = repositories.select_events_by_type(session, event_type.value)
            return tuple(mapping.row_to_event(row) for row in rows)
        except OperationalError as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        finally:
            session.close()
