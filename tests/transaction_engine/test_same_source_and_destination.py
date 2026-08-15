"""Identical resolved source and destination -> REJECTED."""

from collections.abc import Callable

from file_agent.domain import (
    DestinationCategory,
    ExecutionAuthorization,
    PolicyDecision,
    RejectionCode,
    TransactionRequest,
    TransactionResult,
)
from file_agent.scanner import SandboxRoot
from file_agent.transaction_engine import TransactionEngine


def test_source_equal_to_destination_is_rejected(
    sandbox_root: SandboxRoot,
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    already_placed = sandbox_root.path / "Documents" / "report.txt"
    already_placed.write_bytes(b"hello world")
    request = make_request(
        already_placed,
        content=b"hello world",
        destination_category=DestinationCategory.DOCUMENTS,
        destination_path=already_placed,
    )
    policy_decision = make_policy_decision(request)
    authorization = ExecutionAuthorization.from_policy_auto(policy_decision)

    engine = TransactionEngine(sandbox_root)
    outcome = engine.prepare(request, authorization)

    assert isinstance(outcome, TransactionResult)
    assert outcome.rejection_code is RejectionCode.SOURCE_EQUALS_DESTINATION
    assert already_placed.exists()
