"""Pure domain<->row translation functions. No Session involved, no I/O.

Uses only the domain layer's public API (constructors and model_dump()) —
never file_agent.domain._validators' private deep_freeze/deep_thaw helpers.
"""

from pathlib import Path

from pydantic import ValidationError

from file_agent.domain import (
    DiscoveredFile,
    DomainEvent,
    EntityType,
    EventType,
    ScanRun,
    ScanStatus,
)
from file_agent.persistence.errors import MappingError
from file_agent.persistence.orm import DomainEventRow, FileObservationRow, ScanRow


def scan_to_row(scan: ScanRun) -> ScanRow:
    return ScanRow(
        id=scan.id,
        root_path=str(scan.root_path),
        started_at=scan.started_at,
        completed_at=scan.completed_at,
        files_discovered=scan.files_discovered,
        status=scan.status.value,
    )


def row_to_scan(row: ScanRow) -> ScanRun:
    try:
        return ScanRun(
            id=row.id,
            root_path=Path(row.root_path),
            started_at=row.started_at,
            completed_at=row.completed_at,
            files_discovered=row.files_discovered,
            status=ScanStatus(row.status),
        )
    except (ValueError, ValidationError) as exc:
        raise MappingError(
            f"failed to reconstruct ScanRun from row id={row.id}: {exc}"
        ) from exc


def discovered_file_to_row(discovered: DiscoveredFile) -> FileObservationRow:
    return FileObservationRow(
        id=discovered.id,
        path=str(discovered.path),
        size_bytes=discovered.size_bytes,
        sha256=discovered.sha256,
        created_at=discovered.created_at,
        modified_at=discovered.modified_at,
        discovered_at=discovered.discovered_at,
        discovered_by_scan_id=discovered.discovered_by_scan_id,
    )


def row_to_discovered_file(row: FileObservationRow) -> DiscoveredFile:
    try:
        return DiscoveredFile(
            id=row.id,
            path=Path(row.path),
            size_bytes=row.size_bytes,
            sha256=row.sha256,
            created_at=row.created_at,
            modified_at=row.modified_at,
            discovered_at=row.discovered_at,
            discovered_by_scan_id=row.discovered_by_scan_id,
        )
    except (ValueError, ValidationError) as exc:
        raise MappingError(
            f"failed to reconstruct DiscoveredFile from row id={row.id}: {exc}"
        ) from exc


def event_to_row(event: DomainEvent) -> DomainEventRow:
    dumped = event.model_dump()
    return DomainEventRow(
        id=dumped["id"],
        event_type=dumped["event_type"].value,
        timestamp=dumped["timestamp"],
        entity_type=dumped["entity_type"].value,
        entity_id=dumped["entity_id"],
        payload=dumped["payload"],
    )


def row_to_event(row: DomainEventRow) -> DomainEvent:
    try:
        return DomainEvent(
            id=row.id,
            event_type=EventType(row.event_type),
            timestamp=row.timestamp,
            entity_type=EntityType(row.entity_type),
            entity_id=row.entity_id,
            payload=row.payload,
        )
    except (ValueError, ValidationError) as exc:
        raise MappingError(
            f"failed to reconstruct DomainEvent from row id={row.id}: {exc}"
        ) from exc
