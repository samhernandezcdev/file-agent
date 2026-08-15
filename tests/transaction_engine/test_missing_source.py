"""Source file gone before the transaction executes -> REJECTED."""

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


def test_missing_source_is_rejected(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    source = make_source_file("report.txt")
    request = make_request(source)
    policy_decision = make_policy_decision(request)
    authorization = ExecutionAuthorization.from_policy_auto(policy_decision)

    source.unlink()

    engine = TransactionEngine(sandbox_root)
    outcome = engine.prepare(request, authorization)

    assert isinstance(outcome, TransactionResult)
    assert outcome.rejection_code is RejectionCode.SOURCE_NOT_FOUND
    assert not request.destination_path.exists()
