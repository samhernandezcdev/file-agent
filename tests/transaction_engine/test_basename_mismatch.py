"""v1 preserves basename -- a differing destination filename is a rejected
rename attempt, not a move."""

from collections.abc import Callable
from pathlib import Path

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


def test_differing_basename_is_rejected(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    source = make_source_file("report.txt")
    renamed_destination = sandbox_root.path / "Documents" / "report-final.txt"
    request = make_request(
        source,
        destination_category=DestinationCategory.DOCUMENTS,
        destination_path=renamed_destination,
    )
    policy_decision = make_policy_decision(request)
    authorization = ExecutionAuthorization.from_policy_auto(policy_decision)

    engine = TransactionEngine(sandbox_root)
    outcome = engine.prepare(request, authorization)

    assert isinstance(outcome, TransactionResult)
    assert outcome.rejection_code is RejectionCode.BASENAME_MISMATCH
    assert source.exists()
    assert not renamed_destination.exists()
