"""Adversarial tests for the prepared-capability bypass surface, mirroring
transaction_engine's own test_prepared_move_bypass.py exactly.

Imports _PreparedRecovery via the private module path -- the same way any
other leading-underscore internal in this codebase is reachable by code that
specifically needs to (not advertised via __init__.py).
"""

from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest

from file_agent.domain import (
    CompletedMoveEvidence,
    RecoveryResult,
    RecoveryStatus,
    ReverseMoveRequest,
)
from file_agent.persistence import AppPaths
from file_agent.recovery_engine import RecoveryEngine
from file_agent.recovery_engine.engine import _PreparedRecovery
from file_agent.recovery_engine.errors import InvalidPreparedRecoveryError
from file_agent.scanner import SandboxRoot


def test_forged_prepared_recovery_cannot_commit(
    sandbox_root: SandboxRoot, app_paths: AppPaths
) -> None:
    engine = RecoveryEngine(sandbox_root, app_paths)
    forged = _PreparedRecovery(_token=uuid4())

    with pytest.raises(InvalidPreparedRecoveryError):
        engine.commit(forged)


def test_prepared_recovery_from_another_engine_instance_cannot_commit(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_move_evidence: Callable[..., CompletedMoveEvidence],
    make_reverse_move_request: Callable[..., ReverseMoveRequest],
) -> None:
    content = b"hello world"
    current_path = make_source_file("Documents/report.txt", content=content)
    original_path = sandbox_root.path / "report.txt"
    evidence = make_move_evidence(
        source_path=original_path, destination_path=current_path, content=content
    )
    request = make_reverse_move_request(evidence, current_path=current_path)

    engine_a = RecoveryEngine(sandbox_root, app_paths)
    engine_b = RecoveryEngine(sandbox_root, app_paths)
    prepared = engine_a.prepare(request)
    assert not isinstance(prepared, RecoveryResult)

    with pytest.raises(InvalidPreparedRecoveryError):
        engine_b.commit(prepared)

    assert current_path.exists()
    assert not original_path.exists()


def test_same_prepared_recovery_cannot_commit_twice(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_move_evidence: Callable[..., CompletedMoveEvidence],
    make_reverse_move_request: Callable[..., ReverseMoveRequest],
) -> None:
    content = b"hello world"
    current_path = make_source_file("Documents/report.txt", content=content)
    original_path = sandbox_root.path / "report.txt"
    evidence = make_move_evidence(
        source_path=original_path, destination_path=current_path, content=content
    )
    request = make_reverse_move_request(evidence, current_path=current_path)

    engine = RecoveryEngine(sandbox_root, app_paths)
    prepared = engine.prepare(request)
    assert not isinstance(prepared, RecoveryResult)

    first = engine.commit(prepared)
    assert first.status is RecoveryStatus.SUCCEEDED

    with pytest.raises(InvalidPreparedRecoveryError):
        engine.commit(prepared)


def test_rejected_prepare_never_produces_a_committable_capability(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_move_evidence: Callable[..., CompletedMoveEvidence],
    make_reverse_move_request: Callable[..., ReverseMoveRequest],
) -> None:
    content = b"hello world"
    current_path = make_source_file("Documents/report.txt", content=content)
    original_path = make_source_file("report.txt", content=b"already occupied")
    evidence = make_move_evidence(
        source_path=original_path, destination_path=current_path, content=content
    )
    request = make_reverse_move_request(evidence, current_path=current_path)

    engine = RecoveryEngine(sandbox_root, app_paths)
    outcome = engine.prepare(request)

    assert isinstance(outcome, RecoveryResult)
    assert not isinstance(outcome, _PreparedRecovery)


def test_commit_ignores_caller_controlled_state_and_uses_only_the_registry(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_move_evidence: Callable[..., CompletedMoveEvidence],
    make_reverse_move_request: Callable[..., ReverseMoveRequest],
) -> None:
    """A NEW _PreparedRecovery instance built from a token COPIED off a
    genuine, still-pending capability still commits successfully using the
    engine's own stored request/hash data -- proving commit() is driven
    entirely by the token-keyed registry lookup, never by the identity of
    the object the caller happens to pass in."""
    content = b"hello world"
    current_path = make_source_file("Documents/report.txt", content=content)
    original_path = sandbox_root.path / "report.txt"
    evidence = make_move_evidence(
        source_path=original_path, destination_path=current_path, content=content
    )
    request = make_reverse_move_request(evidence, current_path=current_path)

    engine = RecoveryEngine(sandbox_root, app_paths)
    prepared = engine.prepare(request)
    assert not isinstance(prepared, RecoveryResult)

    copied_token_capability = _PreparedRecovery(_token=prepared._token)
    assert copied_token_capability is not prepared

    result = engine.commit(copied_token_capability)

    assert result.status is RecoveryStatus.SUCCEEDED
    assert not current_path.exists()
    assert original_path.exists()
