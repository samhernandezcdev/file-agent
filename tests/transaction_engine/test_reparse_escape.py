"""Destination path safety against symlink/junction escapes -- where the
platform permits creating them."""

import subprocess
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


def _make_junction(link: Path, target: Path) -> None:
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
    )


def test_destination_parent_replaced_by_escaping_junction_is_rejected(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
    tmp_path: Path,
) -> None:
    """sandbox/Documents replaced by a junction pointing OUTSIDE the
    sandbox -- must resolve as an escape, not a legitimate destination."""
    outside_target = tmp_path / "outside_documents"
    outside_target.mkdir()
    documents = sandbox_root.path / "Documents"
    documents.rmdir()
    _make_junction(documents, outside_target)

    source = make_source_file("report.txt")
    request = make_request(source, destination_category=DestinationCategory.DOCUMENTS)
    policy_decision = make_policy_decision(request)

    engine = TransactionEngine(sandbox_root)
    outcome = engine.prepare(request, policy_decision)

    assert isinstance(outcome, TransactionResult)
    assert outcome.rejection_code is RejectionCode.DESTINATION_OUTSIDE_SANDBOX
    assert not (outside_target / "report.txt").exists()


def test_destination_parent_replaced_by_in_bounds_junction_is_rejected(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    """sandbox/Documents replaced by a junction pointing at ANOTHER
    directory still inside the sandbox -- containment alone would pass, but
    the conservative "never follow a reparse point" policy (matching the
    scanner's own stance) must still reject it."""
    real_docs = sandbox_root.path / "RealDocs"
    real_docs.mkdir()
    documents = sandbox_root.path / "Documents"
    documents.rmdir()
    _make_junction(documents, real_docs)

    source = make_source_file("report.txt")
    request = make_request(source, destination_category=DestinationCategory.DOCUMENTS)
    policy_decision = make_policy_decision(request)

    engine = TransactionEngine(sandbox_root)
    outcome = engine.prepare(request, policy_decision)

    assert isinstance(outcome, TransactionResult)
    assert outcome.rejection_code is RejectionCode.DESTINATION_UNSAFE_REPARSE_POINT
    assert not (real_docs / "report.txt").exists()
