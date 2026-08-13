"""REVIEW and BLOCK never execute -- no caller discretion, no override."""

from collections.abc import Callable
from pathlib import Path

import pytest

from file_agent.domain import (
    PolicyDecision,
    PolicyOutcome,
    RejectionCode,
    TransactionRequest,
    TransactionResult,
)
from file_agent.scanner import SandboxRoot
from file_agent.transaction_engine import TransactionEngine


@pytest.mark.parametrize(
    ("decision", "expected_code"),
    [
        (PolicyOutcome.REVIEW, RejectionCode.POLICY_REVIEW),
        (PolicyOutcome.BLOCK, RejectionCode.POLICY_BLOCK),
    ],
)
def test_non_auto_decision_is_rejected_and_untouched(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
    decision: PolicyOutcome,
    expected_code: RejectionCode,
) -> None:
    source = make_source_file("run.bat", content=b"echo hi")
    request = make_request(source, content=b"echo hi")
    policy_decision = make_policy_decision(request, decision=decision)

    engine = TransactionEngine(sandbox_root)
    outcome = engine.prepare(request, policy_decision)

    assert isinstance(outcome, TransactionResult)
    assert outcome.status.value == "rejected"
    assert outcome.rejection_code is expected_code
    assert source.exists()
    assert not request.destination_path.exists()
