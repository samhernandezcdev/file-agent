"""Source and destination must both remain inside the configured sandbox."""

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


def test_destination_outside_sandbox_is_rejected(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
    tmp_path: Path,
) -> None:
    source = make_source_file("report.txt")
    outside = tmp_path / "outside" / "report.txt"
    outside.parent.mkdir()
    request = make_request(
        source,
        destination_category=DestinationCategory.DOCUMENTS,
        destination_path=outside,
    )
    policy_decision = make_policy_decision(request)

    engine = TransactionEngine(sandbox_root)
    outcome = engine.prepare(request, policy_decision)

    assert isinstance(outcome, TransactionResult)
    # A destination outside the sandbox never matches the configured
    # physical directory for its claimed category either -- the
    # category-path check (earlier in the precedence chain) catches this
    # before the dedicated containment check is ever reached. The pure
    # "resolves outside sandbox despite a lexically-matching parent" case is
    # covered separately in test_reparse_escape.py (only reachable via a
    # reparse point at the configured directory itself).
    assert outcome.rejection_code is RejectionCode.DESTINATION_CATEGORY_PATH_MISMATCH
    assert not outside.exists()


def test_source_outside_sandbox_is_rejected(
    sandbox_root: SandboxRoot,
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
    tmp_path: Path,
) -> None:
    outside_source = tmp_path / "outside_report.txt"
    outside_source.write_bytes(b"hello world")
    request = make_request(outside_source, content=b"hello world")
    policy_decision = make_policy_decision(request)

    engine = TransactionEngine(sandbox_root)
    outcome = engine.prepare(request, policy_decision)

    assert isinstance(outcome, TransactionResult)
    assert outcome.rejection_code is RejectionCode.SOURCE_IDENTITY_CHANGED
    assert outside_source.exists()
    assert not request.destination_path.exists()
