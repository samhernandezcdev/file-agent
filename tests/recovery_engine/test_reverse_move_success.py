"""REVERSE_MOVE: successful undo, byte-identical restoration, audit event."""

from collections.abc import Callable
from pathlib import Path

from file_agent.domain import (
    CompletedMoveEvidence,
    EntityType,
    EventType,
    RecoveryResult,
    RecoveryStatus,
    ReverseMoveRequest,
)
from file_agent.persistence import AppPaths
from file_agent.recovery_engine import (
    RecoveryEngine,
    recovery_requested_event,
    recovery_result_event,
)
from file_agent.scanner import SandboxRoot


def test_successful_reverse_move_restores_original_path(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_move_evidence: Callable[..., CompletedMoveEvidence],
    make_reverse_move_request: Callable[..., ReverseMoveRequest],
    prepare_and_commit: Callable[..., RecoveryResult],
) -> None:
    content = b"undo me byte for byte"
    current_path = make_source_file("Documents/report.txt", content=content)
    original_path = sandbox_root.path / "report.txt"

    evidence = make_move_evidence(
        source_path=original_path, destination_path=current_path, content=content
    )
    request = make_reverse_move_request(evidence, current_path=current_path)

    result = prepare_and_commit(RecoveryEngine(sandbox_root, app_paths), request)

    assert result.status is RecoveryStatus.SUCCEEDED
    assert result.verified_sha256 == evidence.verified_sha256
    assert result.source_path == current_path
    assert result.destination_path == original_path
    assert not current_path.exists()
    assert original_path.read_bytes() == content


def test_reverse_move_audit_events(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_move_evidence: Callable[..., CompletedMoveEvidence],
    make_reverse_move_request: Callable[..., ReverseMoveRequest],
) -> None:
    content = b"audit trail"
    current_path = make_source_file("Documents/report.txt", content=content)
    original_path = sandbox_root.path / "report.txt"
    evidence = make_move_evidence(
        source_path=original_path, destination_path=current_path, content=content
    )
    request = make_reverse_move_request(evidence, current_path=current_path)

    requested_event = recovery_requested_event(request)
    assert requested_event.event_type is EventType.RECOVERY_REQUESTED
    assert requested_event.entity_type is EntityType.RECOVERY
    assert requested_event.entity_id == request.id
    assert requested_event.payload["current_path"] == str(current_path)
    assert requested_event.payload["original_path"] == str(original_path)
    assert requested_event.payload["expected_sha256"] == evidence.verified_sha256

    engine = RecoveryEngine(sandbox_root, app_paths)
    prepared = engine.prepare(request)
    assert not isinstance(prepared, RecoveryResult)
    result = engine.commit(prepared)

    result_event = recovery_result_event(result)
    assert result_event.event_type is EventType.RECOVERY_SUCCEEDED
    assert result_event.entity_type is EntityType.RECOVERY
    assert result_event.entity_id == request.id
    assert result_event.payload["status"] == "succeeded"
    assert result_event.payload["verified_sha256"] == evidence.verified_sha256
    assert result_event.payload["vault_object_path"] is None
