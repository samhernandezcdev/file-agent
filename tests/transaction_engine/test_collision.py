"""Destination already exists -> REJECTED, no overwrite, nothing modified."""

from collections.abc import Callable
from pathlib import Path

from file_agent.domain import (
    ExecutionAuthorization,
    PolicyDecision,
    RejectionCode,
    TransactionRequest,
    TransactionResult,
)
from file_agent.scanner import SandboxRoot
from file_agent.transaction_engine import TransactionEngine


def test_existing_destination_file_is_rejected_and_neither_side_modified(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    source = make_source_file("report.txt", content=b"source content")
    request = make_request(source, content=b"source content")
    request.destination_path.write_bytes(b"existing destination content")
    policy_decision = make_policy_decision(request)
    authorization = ExecutionAuthorization.from_policy_auto(policy_decision)

    engine = TransactionEngine(sandbox_root)
    outcome = engine.prepare(request, authorization)

    assert isinstance(outcome, TransactionResult)
    assert outcome.rejection_code is RejectionCode.DESTINATION_ALREADY_EXISTS
    assert source.read_bytes() == b"source content"
    assert request.destination_path.read_bytes() == b"existing destination content"
