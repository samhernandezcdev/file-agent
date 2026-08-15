"""REVERSE_MOVE: current_path (B) missing or changed -- never invent success."""

from collections.abc import Callable
from pathlib import Path

from file_agent.domain import (
    CompletedMoveEvidence,
    RecoveryRejectionCode,
    RecoveryResult,
    RecoveryStatus,
    ReverseMoveRequest,
)
from file_agent.persistence import AppPaths
from file_agent.recovery_engine import RecoveryEngine
from file_agent.scanner import SandboxRoot


def test_current_file_missing_is_rejected(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_move_evidence: Callable[..., CompletedMoveEvidence],
    make_reverse_move_request: Callable[..., ReverseMoveRequest],
) -> None:
    content = b"gone"
    current_path = make_source_file("Documents/report.txt", content=content)
    original_path = sandbox_root.path / "report.txt"
    evidence = make_move_evidence(
        source_path=original_path, destination_path=current_path, content=content
    )
    request = make_reverse_move_request(evidence, current_path=current_path)
    current_path.unlink()

    result = RecoveryEngine(sandbox_root, app_paths).prepare(request)

    assert isinstance(result, RecoveryResult)
    assert result.status is RecoveryStatus.REJECTED
    assert result.rejection_code is RecoveryRejectionCode.CURRENT_FILE_MISSING
    assert not original_path.exists()


def test_current_file_changed_is_rejected(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_move_evidence: Callable[..., CompletedMoveEvidence],
    make_reverse_move_request: Callable[..., ReverseMoveRequest],
) -> None:
    actual_content = b"actual current content"
    current_path = make_source_file("Documents/report.txt", content=actual_content)
    original_path = sandbox_root.path / "report.txt"
    # Evidence claims a DIFFERENT sha than what's actually on disk --
    # metadata (size/timestamps) still match, so this exercises the hash-
    # mismatch branch of the collapsed CURRENT_FILE_CHANGED code.
    evidence = make_move_evidence(
        source_path=original_path,
        destination_path=current_path,
        content=b"a completely different content entirely",
    )
    request = make_reverse_move_request(evidence, current_path=current_path)

    result = RecoveryEngine(sandbox_root, app_paths).prepare(request)

    assert isinstance(result, RecoveryResult)
    assert result.status is RecoveryStatus.REJECTED
    assert result.rejection_code is RecoveryRejectionCode.CURRENT_FILE_CHANGED
    assert current_path.read_bytes() == actual_content
    assert not original_path.exists()


def test_retry_after_successful_reverse_move_rejects_rather_than_duplicates(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_move_evidence: Callable[..., CompletedMoveEvidence],
    make_reverse_move_request: Callable[..., ReverseMoveRequest],
    prepare_and_commit: Callable[..., RecoveryResult],
) -> None:
    content = b"idempotency check"
    current_path = make_source_file("Documents/report.txt", content=content)
    original_path = sandbox_root.path / "report.txt"
    evidence = make_move_evidence(
        source_path=original_path, destination_path=current_path, content=content
    )
    request = make_reverse_move_request(evidence, current_path=current_path)
    engine = RecoveryEngine(sandbox_root, app_paths)

    retry_request = make_reverse_move_request(evidence, current_path=current_path)

    first = prepare_and_commit(engine, request)
    assert first.status is RecoveryStatus.SUCCEEDED

    # current_path no longer exists after the successful move -- the retry
    # request's expected_* fields were captured BEFORE that, exactly as a
    # real caller who observed B before the crash/first attempt would have.
    second = engine.prepare(retry_request)

    assert isinstance(second, RecoveryResult)
    assert second.status is RecoveryStatus.REJECTED
    # ORIGINAL_PATH_OCCUPIED, not CURRENT_FILE_MISSING: containment/occupancy
    # checks on original_path run BEFORE the expensive current_path identity
    # check (round-3 correction 3's ordering), and original_path now holds
    # the just-restored file -- so the retry is correctly rejected there,
    # never reaching the current-file check at all. Either code would be a
    # safe, fail-closed outcome; this is simply which one actually fires.
    assert second.rejection_code is RecoveryRejectionCode.ORIGINAL_PATH_OCCUPIED
    assert original_path.read_bytes() == content  # untouched by the retry
