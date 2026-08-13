"""The engine cross-validates ids in-memory rather than trusting the caller's
claims -- an unrelated PolicyDecision must never authorize a request."""

from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest

from file_agent.domain import (
    PolicyDecision,
    RejectionCode,
    TransactionRequest,
    TransactionResult,
)
from file_agent.scanner import SandboxRoot
from file_agent.transaction_engine import TransactionEngine


@pytest.mark.parametrize(
    "field", ["policy_decision_id_override", "proposal_id_override", "file_id_override"]
)
def test_mismatched_linkage_field_is_rejected(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
    field: str,
) -> None:
    source = make_source_file("report.txt")
    request = make_request(source)
    overrides: dict[str, object] = {}
    if field == "policy_decision_id_override":
        overrides["id"] = uuid4()
    elif field == "proposal_id_override":
        overrides["proposal_id"] = uuid4()
    else:
        overrides["file_id"] = uuid4()
    policy_decision = make_policy_decision(request, **overrides)

    engine = TransactionEngine(sandbox_root)
    outcome = engine.prepare(request, policy_decision)

    assert isinstance(outcome, TransactionResult)
    assert outcome.rejection_code is RejectionCode.AUTHORIZATION_LINKAGE_MISMATCH
    assert source.exists()
