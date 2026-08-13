"""The golden path: a valid AUTO-authorized MOVE succeeds."""

from collections.abc import Callable
from pathlib import Path

from file_agent.domain import (
    PolicyDecision,
    TransactionRequest,
    TransactionResult,
    TransactionStatus,
)
from file_agent.scanner import SandboxRoot
from file_agent.transaction_engine import TransactionEngine


def test_successful_move_relocates_file_and_preserves_content(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
    prepare_and_commit: Callable[
        [TransactionEngine, TransactionRequest, PolicyDecision], TransactionResult
    ],
) -> None:
    source = make_source_file("report.txt", content=b"hello world")
    request = make_request(source, content=b"hello world")
    policy_decision = make_policy_decision(request)

    engine = TransactionEngine(sandbox_root)
    result = prepare_and_commit(engine, request, policy_decision)

    assert result.status is TransactionStatus.SUCCEEDED
    assert result.verified_sha256 == request.expected_sha256
    assert not source.exists()
    assert request.destination_path.exists()
    assert request.destination_path.read_bytes() == b"hello world"
    assert result.started_at is not None
    assert result.completed_at is not None
    assert result.started_at <= result.completed_at
