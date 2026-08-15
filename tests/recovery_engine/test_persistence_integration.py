"""Proves recovery events compose with the existing persistence API with
zero changes to file_agent.persistence, for both REVERSE_MOVE and
RESTORE_FROM_VAULT."""

import hashlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from file_agent.domain import (
    CompletedMoveEvidence,
    EntityType,
    RecoveryResult,
    RecoveryStatus,
    RestoreFromVaultRequest,
    ReverseMoveRequest,
    VaultCaptureEvidence,
    VaultCaptureRequest,
    VaultCaptureStatus,
)
from file_agent.persistence import (
    AppPaths,
    FileAgentStore,
    create_engine_and_session_factory,
)
from file_agent.persistence.orm import Base
from file_agent.recovery_engine import (
    RecoveryEngine,
    recovery_requested_event,
    recovery_result_event,
)
from file_agent.scanner import SandboxRoot
from file_agent.vault_engine import VaultEngine


@pytest.fixture
def store(tmp_path: Path) -> Iterator[FileAgentStore]:
    config = AppPaths.from_root(tmp_path / "store_appdata")
    engine, session_factory = create_engine_and_session_factory(config)
    Base.metadata.create_all(engine)
    try:
        yield FileAgentStore(session_factory)
    finally:
        engine.dispose()


def test_reverse_move_events_round_trip_through_persistence(
    store: FileAgentStore,
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_move_evidence: Callable[..., CompletedMoveEvidence],
    make_reverse_move_request: Callable[..., ReverseMoveRequest],
) -> None:
    content = b"persisted reverse move"
    current_path = make_source_file("Documents/report.txt", content=content)
    original_path = sandbox_root.path / "report.txt"
    evidence = make_move_evidence(
        source_path=original_path, destination_path=current_path, content=content
    )
    request = make_reverse_move_request(evidence, current_path=current_path)
    requested_event = recovery_requested_event(request)
    assert store.record_event(requested_event) is True

    engine = RecoveryEngine(sandbox_root, app_paths)
    prepared = engine.prepare(request)
    assert not isinstance(prepared, RecoveryResult)
    result = engine.commit(prepared)
    result_event = recovery_result_event(result)
    assert store.record_event(result_event) is True

    events = store.list_events(EntityType.RECOVERY, request.id)
    assert events == (requested_event, result_event)


def test_restore_events_round_trip_through_persistence(
    store: FileAgentStore,
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_vault_evidence: Callable[..., VaultCaptureEvidence],
    make_restore_request: Callable[..., RestoreFromVaultRequest],
) -> None:
    content = b"persisted restore"
    source = make_source_file("report.txt", content=content)
    st = source.stat()
    capture_request = VaultCaptureRequest(
        file_id=uuid4(),
        source_path=source,
        expected_size=st.st_size,
        expected_created_at=datetime.fromtimestamp(st.st_ctime, tz=UTC),
        expected_modified_at=datetime.fromtimestamp(st.st_mtime, tz=UTC),
        expected_sha256=hashlib.sha256(content).hexdigest(),
    )
    capture_result = VaultEngine(sandbox_root, app_paths).capture(capture_request)
    assert capture_result.status is VaultCaptureStatus.CAPTURED
    source.unlink()

    evidence = make_vault_evidence(source_path=source, content=content)
    request = make_restore_request(evidence)
    requested_event = recovery_requested_event(request)
    assert store.record_event(requested_event) is True

    engine = RecoveryEngine(sandbox_root, app_paths)
    prepared = engine.prepare(request)
    assert not isinstance(prepared, RecoveryResult)
    result = engine.commit(prepared)
    result_event = recovery_result_event(result)
    assert store.record_event(result_event) is True

    events = store.list_events(EntityType.RECOVERY, request.id)
    assert events == (requested_event, result_event)
    assert result.status is RecoveryStatus.SUCCEEDED
