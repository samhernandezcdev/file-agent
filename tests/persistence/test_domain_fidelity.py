"""Tests proving persisted-and-reconstructed domain values are faithful."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from uuid import UUID, uuid4

import pytest

from file_agent.domain import DomainEvent, ScanStatus
from file_agent.persistence import FileAgentStore, mapping
from file_agent.persistence.errors import MappingError
from file_agent.persistence.orm import ScanRow
from file_agent.scanner import ScanResult


def test_uuid_reconstructed_as_uuid(
    store: FileAgentStore, make_scan_result: Callable[..., ScanResult]
) -> None:
    result = make_scan_result(file_count=0)
    store.record_scan(result)
    fetched = store.get_scan(result.scan_run.id)
    assert fetched is not None
    assert isinstance(fetched.id, UUID)


def test_path_reconstructed_as_path(
    store: FileAgentStore, make_scan_result: Callable[..., ScanResult]
) -> None:
    result = make_scan_result(file_count=0)
    store.record_scan(result)
    fetched = store.get_scan(result.scan_run.id)
    assert fetched is not None
    assert isinstance(fetched.root_path, Path)
    assert fetched.root_path == result.scan_run.root_path


def test_datetime_reconstructed_aware_utc(
    store: FileAgentStore, make_scan_result: Callable[..., ScanResult]
) -> None:
    result = make_scan_result(file_count=0)
    store.record_scan(result)
    fetched = store.get_scan(result.scan_run.id)
    assert fetched is not None
    assert fetched.started_at.tzinfo is not None
    offset = fetched.started_at.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 0
    assert fetched.started_at == result.scan_run.started_at


def test_enum_reconstructed_as_enum_member(
    store: FileAgentStore, make_scan_result: Callable[..., ScanResult]
) -> None:
    result = make_scan_result(file_count=0)
    store.record_scan(result)
    fetched = store.get_scan(result.scan_run.id)
    assert fetched is not None
    assert fetched.status is ScanStatus.COMPLETED


def test_event_payload_reconstructed_as_immutable_mapping(
    store: FileAgentStore, make_event: Callable[..., DomainEvent]
) -> None:
    event = make_event(payload={"tags": ["a", "b"]})
    store.record_event(event)
    fetched = store.list_events(event.entity_type, event.entity_id)[0]
    assert isinstance(fetched.payload, MappingProxyType)
    with pytest.raises(TypeError):
        fetched.payload["tags"] = "mutated"  # type: ignore[index]


def test_naive_datetime_at_mapping_boundary_raises_mapping_error() -> None:
    row = ScanRow(
        id=uuid4(),
        root_path="C:/sandbox",
        started_at=datetime(2026, 1, 1),  # noqa: DTZ001 -- intentionally naive
        completed_at=None,
        files_discovered=0,
        status="pending",
    )
    with pytest.raises(MappingError):
        mapping.row_to_scan(row)
