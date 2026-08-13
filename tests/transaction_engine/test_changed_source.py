"""TOCTOU: the source changed after observation/authorization -- reject,
don't silently move whatever currently exists."""

from collections.abc import Callable
from pathlib import Path

from file_agent.domain import (
    PolicyDecision,
    RejectionCode,
    TransactionRequest,
    TransactionResult,
)
from file_agent.scanner import SandboxRoot
from file_agent.transaction_engine import TransactionEngine


def test_content_modified_after_authorization_is_rejected(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    source = make_source_file("report.txt", content=b"original content")
    request = make_request(source, content=b"original content")
    policy_decision = make_policy_decision(request)

    # simulate the file changing between observation/proposal/policy and
    # transaction execution
    source.write_bytes(b"tampered content, different size")

    engine = TransactionEngine(sandbox_root)
    outcome = engine.prepare(request, policy_decision)

    assert isinstance(outcome, TransactionResult)
    assert outcome.rejection_code is RejectionCode.SOURCE_IDENTITY_CHANGED
    assert source.exists()
    assert not request.destination_path.exists()


def test_hash_mismatch_with_identical_metadata_is_rejected(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    """expected_sha256 doesn't match the file's actual content, even though
    size/timestamps were captured correctly -- SOURCE_HASH_MISMATCH, not
    SOURCE_IDENTITY_CHANGED."""
    source = make_source_file("report.txt", content=b"actual content")
    request = make_request(source, content=b"a different content entirely")
    policy_decision = make_policy_decision(request)

    engine = TransactionEngine(sandbox_root)
    outcome = engine.prepare(request, policy_decision)

    assert isinstance(outcome, TransactionResult)
    assert outcome.rejection_code is RejectionCode.SOURCE_HASH_MISMATCH
    assert source.exists()
