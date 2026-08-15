"""vault_capture_requested_event / vault_capture_result_event -- payload and
provenance completeness, and persistence round-trip via the existing,
unmodified FileAgentStore."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from file_agent.domain import (
    EntityType,
    EventType,
    VaultCaptureRequest,
    VaultCaptureStatus,
)
from file_agent.persistence import (
    AppPaths,
    FileAgentStore,
    create_engine_and_session_factory,
)
from file_agent.persistence.orm import Base
from file_agent.scanner import SandboxRoot
from file_agent.vault_engine import (
    VaultEngine,
    vault_capture_requested_event,
    vault_capture_result_event,
)
from file_agent.vault_engine.rules import VAULT_ENGINE_ID


def test_requested_event_payload(
    make_source_file: Callable[..., Path],
    make_request: Callable[..., VaultCaptureRequest],
) -> None:
    source = make_source_file("report.txt", content=b"x")
    request = make_request(source, content=b"x")

    event = vault_capture_requested_event(request)

    assert event.event_type is EventType.VAULT_CAPTURE_REQUESTED
    assert event.entity_type is EntityType.VAULT_CAPTURE
    assert event.entity_id == request.id
    assert event.payload["request_id"] == str(request.id)
    assert event.payload["file_id"] == str(request.file_id)
    assert event.payload["source_path"] == str(request.source_path)
    assert event.payload["expected_sha256"] == request.expected_sha256
    assert event.payload["expected_size"] == request.expected_size


def test_result_event_payload_is_self_contained(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., VaultCaptureRequest],
) -> None:
    source = make_source_file("report.txt", content=b"payload check")
    request = make_request(source, content=b"payload check")
    result = VaultEngine(sandbox_root, app_paths).capture(request)
    assert result.status is VaultCaptureStatus.CAPTURED

    event = vault_capture_result_event(result)

    assert event.event_type is EventType.VAULT_CAPTURE_SUCCEEDED
    assert event.entity_type is EntityType.VAULT_CAPTURE
    assert event.entity_id == result.request_id
    assert event.payload["request_id"] == str(result.request_id)
    assert event.payload["file_id"] == str(result.file_id)
    assert event.payload["source_path"] == str(result.source_path)
    assert event.payload["expected_sha256"] == result.expected_sha256
    assert event.payload["expected_size"] == result.expected_size
    assert event.payload["status"] == "captured"
    assert event.payload["rejection_code"] is None
    assert event.payload["failure_reason"] is None
    assert event.payload["verified_sha256"] == result.verified_sha256
    assert event.payload["verified_size"] == result.verified_size
    assert event.payload["vault_object_path"] == result.vault_object_path
    assert result.started_at is not None
    assert result.completed_at is not None
    assert event.payload["started_at"] == result.started_at.isoformat()
    assert event.payload["completed_at"] == result.completed_at.isoformat()
    assert event.payload["vault_engine_id"] == VAULT_ENGINE_ID


def test_rejected_result_maps_to_capture_failed_event_type(
    tmp_path: Path,
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_request: Callable[..., VaultCaptureRequest],
) -> None:
    outside = tmp_path / "outside" / "a.txt"
    outside.parent.mkdir()
    outside.write_bytes(b"x")
    request = make_request(outside, content=b"x")

    result = VaultEngine(sandbox_root, app_paths).capture(request)
    assert result.status is VaultCaptureStatus.REJECTED

    event = vault_capture_result_event(result)
    assert event.event_type is EventType.VAULT_CAPTURE_FAILED
    assert event.payload["status"] == "rejected"
    assert event.payload["rejection_code"] == "source_outside_sandbox"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[FileAgentStore]:
    config = AppPaths.from_root(tmp_path / "store_appdata")
    engine, session_factory = create_engine_and_session_factory(config)
    Base.metadata.create_all(engine)
    try:
        yield FileAgentStore(session_factory)
    finally:
        engine.dispose()


def test_capture_events_round_trip_through_persistence(
    store: FileAgentStore,
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., VaultCaptureRequest],
) -> None:
    source = make_source_file("report.txt", content=b"persisted")
    request = make_request(source, content=b"persisted")
    requested_event = vault_capture_requested_event(request)
    assert store.record_event(requested_event) is True

    result = VaultEngine(sandbox_root, app_paths).capture(request)
    result_event = vault_capture_result_event(result)
    assert store.record_event(result_event) is True

    events = store.list_events(EntityType.VAULT_CAPTURE, request.id)
    assert events == (requested_event, result_event)
