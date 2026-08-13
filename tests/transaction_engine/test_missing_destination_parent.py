"""Missing destination parent -> REJECTED. No auto-creation in v1."""

from collections.abc import Callable
from pathlib import Path

from file_agent.domain import (
    DestinationCategory,
    PolicyDecision,
    RejectionCode,
    TransactionRequest,
    TransactionResult,
)
from file_agent.scanner import SandboxRoot
from file_agent.transaction_engine import TransactionEngine


def test_missing_configured_directory_is_rejected_not_created(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    (sandbox_root.path / "Documents").rmdir()
    source = make_source_file("report.txt")
    request = make_request(source, destination_category=DestinationCategory.DOCUMENTS)
    policy_decision = make_policy_decision(request)

    engine = TransactionEngine(sandbox_root)
    outcome = engine.prepare(request, policy_decision)

    assert isinstance(outcome, TransactionResult)
    assert outcome.rejection_code is RejectionCode.DESTINATION_PARENT_MISSING
    assert not (sandbox_root.path / "Documents").exists()
