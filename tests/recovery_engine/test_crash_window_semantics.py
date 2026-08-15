"""Proves the checkpoint boundary the design plan relies on: prepare()
mutates nothing, commit() is the only moment the filesystem changes, and an
orphaned RECOVERY_REQUESTED with no terminal event is exactly what a crash
between commit() and the terminal persist would leave behind -- for both
REVERSE_MOVE and RESTORE_FROM_VAULT. FA-011 does not implement crash
recovery/reconciliation -- these tests document the gap, they do not close
it. Also proves recovery never infers success from "the destination looks
right": a retry after a crash-simulated success cleanly rejects rather than
duplicating or overwriting.
"""

import hashlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from file_agent.domain import (
    CompletedMoveEvidence,
    EntityType,
    EventType,
    RecoveryRejectionCode,
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
from file_agent.recovery_engine import RecoveryEngine, recovery_requested_event
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


def test_reverse_move_prepare_alone_never_mutates_the_filesystem(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_move_evidence: Callable[..., CompletedMoveEvidence],
    make_reverse_move_request: Callable[..., ReverseMoveRequest],
) -> None:
    content = b"untouched by prepare"
    current_path = make_source_file("Documents/report.txt", content=content)
    original_path = sandbox_root.path / "report.txt"
    evidence = make_move_evidence(
        source_path=original_path, destination_path=current_path, content=content
    )
    request = make_reverse_move_request(evidence, current_path=current_path)

    prepared = RecoveryEngine(sandbox_root, app_paths).prepare(request)

    assert not isinstance(prepared, RecoveryResult)
    assert current_path.exists()
    assert not original_path.exists()


def test_reverse_move_crash_after_commit_before_terminal_persist_leaves_orphaned_requested(
    store: FileAgentStore,
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_move_evidence: Callable[..., CompletedMoveEvidence],
    make_reverse_move_request: Callable[..., ReverseMoveRequest],
) -> None:
    content = b"crash window 2"
    current_path = make_source_file("Documents/report.txt", content=content)
    original_path = sandbox_root.path / "report.txt"
    evidence = make_move_evidence(
        source_path=original_path, destination_path=current_path, content=content
    )
    request = make_reverse_move_request(evidence, current_path=current_path)

    engine = RecoveryEngine(sandbox_root, app_paths)
    prepared = engine.prepare(request)
    assert not isinstance(prepared, RecoveryResult)
    store.record_event(recovery_requested_event(request))

    result = engine.commit(prepared)  # the mutation happens here

    # simulated crash: the caller never reaches
    # store.record_event(recovery_result_event(result))

    assert result.status is RecoveryStatus.SUCCEEDED
    assert not current_path.exists()
    assert original_path.exists()

    events = store.list_events(EntityType.RECOVERY, request.id)
    assert len(events) == 1
    assert events[0].event_type is EventType.RECOVERY_REQUESTED


def test_retry_after_crash_simulated_reverse_move_success_rejects_not_duplicates(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_move_evidence: Callable[..., CompletedMoveEvidence],
    make_reverse_move_request: Callable[..., ReverseMoveRequest],
) -> None:
    content = b"no blind inference from destination existing"
    current_path = make_source_file("Documents/report.txt", content=content)
    original_path = sandbox_root.path / "report.txt"
    evidence = make_move_evidence(
        source_path=original_path, destination_path=current_path, content=content
    )
    request = make_reverse_move_request(evidence, current_path=current_path)
    retry_request = make_reverse_move_request(evidence, current_path=current_path)

    engine = RecoveryEngine(sandbox_root, app_paths)
    prepared = engine.prepare(request)
    assert not isinstance(prepared, RecoveryResult)
    first = engine.commit(prepared)
    assert first.status is RecoveryStatus.SUCCEEDED
    # simulated crash before the terminal event was ever persisted -- a
    # future caller only knows "REQUESTED, no terminal" and retries.

    retry_outcome = engine.prepare(retry_request)

    assert isinstance(retry_outcome, RecoveryResult)
    assert retry_outcome.status is RecoveryStatus.REJECTED
    # ORIGINAL_PATH_OCCUPIED: original_path now holds the just-restored
    # file, so the (cheaper, earlier-running) occupancy check rejects the
    # retry before the current-file identity check is ever reached. Either
    # rejection code would be a safe, fail-closed, non-duplicating outcome.
    assert retry_outcome.rejection_code is RecoveryRejectionCode.ORIGINAL_PATH_OCCUPIED
    assert original_path.read_bytes() == content  # not duplicated, not overwritten


def test_restore_crash_after_commit_before_terminal_persist_leaves_orphaned_requested(
    store: FileAgentStore,
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_vault_evidence: Callable[..., VaultCaptureEvidence],
    make_restore_request: Callable[..., RestoreFromVaultRequest],
) -> None:
    content = b"restore crash window"
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

    engine = RecoveryEngine(sandbox_root, app_paths)
    prepared = engine.prepare(request)
    assert not isinstance(prepared, RecoveryResult)
    store.record_event(recovery_requested_event(request))

    result = engine.commit(prepared)  # the mutation (publish) happens here

    # simulated crash: no terminal event persisted

    assert result.status is RecoveryStatus.SUCCEEDED
    assert source.read_bytes() == content

    events = store.list_events(EntityType.RECOVERY, request.id)
    assert len(events) == 1
    assert events[0].event_type is EventType.RECOVERY_REQUESTED
