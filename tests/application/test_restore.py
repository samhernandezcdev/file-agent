"""Restore flow: restore_capture() resolves a genuinely persisted, successful
Vault capture, reconstructs VaultCaptureEvidence internally, and restores via
RecoveryEngine -- the caller supplies only a capture_id, never a target path
or SHA."""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from file_agent.application import (
    ApplicationOutcomeStatus,
    FileAgentApplicationService,
    RestoreResult,
)
from file_agent.application.errors import TerminalPersistenceError
from file_agent.domain import (
    EntityType,
    EventType,
    VaultCaptureRequest,
    VaultCaptureStatus,
)
from file_agent.persistence import AppPaths, FileAgentStore
from file_agent.scanner import SandboxRoot
from file_agent.vault_engine import (
    VaultEngine,
    vault_capture_requested_event,
    vault_capture_result_event,
)
from file_agent.vault_engine.paths import object_abs_path

from .conftest import FailOnEventType


def _capture(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    source: Path,
    content: bytes,
) -> UUID:
    st = source.stat()
    request = VaultCaptureRequest(
        file_id=uuid4(),
        source_path=source,
        expected_size=st.st_size,
        expected_created_at=datetime.fromtimestamp(st.st_ctime, tz=UTC),
        expected_modified_at=datetime.fromtimestamp(st.st_mtime, tz=UTC),
        expected_sha256=hashlib.sha256(content).hexdigest(),
    )
    store.record_event(vault_capture_requested_event(request))
    result = VaultEngine(sandbox_root, app_paths).capture(request)
    store.record_event(vault_capture_result_event(result))
    assert result.status is VaultCaptureStatus.CAPTURED
    return request.id


def test_genuine_capture_restores(
    service: FileAgentApplicationService,
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    content = b"vault-backed content"
    source = make_source_file("report.txt", content=content)
    capture_id = _capture(sandbox_root, app_paths, store, source, content)
    source.unlink()

    result = service.restore_capture(capture_id)

    assert result.status is ApplicationOutcomeStatus.SUCCEEDED
    assert result.restored_path == source
    assert source.read_bytes() == content


def test_unknown_capture_id_rejected(service: FileAgentApplicationService) -> None:
    result = service.restore_capture(uuid4())
    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == "capture_not_found"


def test_failed_capture_cannot_restore(
    service: FileAgentApplicationService,
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
) -> None:
    missing_source = sandbox_root.path / "never_existed.txt"
    request = VaultCaptureRequest(
        file_id=uuid4(),
        source_path=missing_source,
        expected_size=1,
        expected_created_at=datetime.now(UTC),
        expected_modified_at=datetime.now(UTC),
        expected_sha256="a" * 64,
    )
    store.record_event(vault_capture_requested_event(request))
    capture_result = VaultEngine(sandbox_root, app_paths).capture(request)
    assert capture_result.status is VaultCaptureStatus.REJECTED
    store.record_event(vault_capture_result_event(capture_result))

    result = service.restore_capture(request.id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == "capture_not_successful"


def test_corrupted_vault_object_propagates_rejection(
    service: FileAgentApplicationService,
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    content = b"will be corrupted"
    source = make_source_file("report.txt", content=content)
    capture_id = _capture(sandbox_root, app_paths, store, source, content)
    source.unlink()

    vault_object = object_abs_path(app_paths, hashlib.sha256(content).hexdigest())
    vault_object.write_bytes(b"corrupted bytes, does not match the filename hash")

    result = service.restore_capture(capture_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == "vault_object_corrupted"
    assert not source.exists()


def test_recovery_event_ordering(
    service: FileAgentApplicationService,
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    content = b"ordering check"
    source = make_source_file("report.txt", content=content)
    capture_id = _capture(sandbox_root, app_paths, store, source, content)
    source.unlink()

    result = service.restore_capture(capture_id)
    assert result.status is ApplicationOutcomeStatus.SUCCEEDED
    assert result.recovery_id is not None

    events = store.list_events(EntityType.RECOVERY, result.recovery_id)
    event_types = [e.event_type for e in events]
    assert event_types == [EventType.RECOVERY_REQUESTED, EventType.RECOVERY_SUCCEEDED]


def test_restore_requested_persist_failure_prevents_commit(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    content = b"prevent commit"
    source = make_source_file("report.txt", content=content)
    capture_id = _capture(sandbox_root, app_paths, store, source, content)
    source.unlink()

    failing_store = FailOnEventType(store, {EventType.RECOVERY_REQUESTED})
    failing_service = FileAgentApplicationService(
        sandbox_root, app_paths, failing_store
    )  # type: ignore[arg-type]

    with pytest.raises(Exception) as excinfo:
        failing_service.restore_capture(capture_id)

    assert not isinstance(excinfo.value, TerminalPersistenceError)
    assert not source.exists()  # commit() never ran


def test_restore_terminal_persist_failure_raises_with_real_result(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    content = b"terminal failure"
    source = make_source_file("report.txt", content=content)
    capture_id = _capture(sandbox_root, app_paths, store, source, content)
    source.unlink()

    failing_store = FailOnEventType(
        store,
        {
            EventType.RECOVERY_SUCCEEDED,
            EventType.RECOVERY_REJECTED,
            EventType.RECOVERY_FAILED,
        },
    )
    failing_service = FileAgentApplicationService(
        sandbox_root, app_paths, failing_store
    )  # type: ignore[arg-type]

    with pytest.raises(TerminalPersistenceError) as excinfo:
        failing_service.restore_capture(capture_id)

    result = excinfo.value.result
    assert isinstance(result, RestoreResult)
    assert result.status is ApplicationOutcomeStatus.SUCCEEDED
    assert source.read_bytes() == content
