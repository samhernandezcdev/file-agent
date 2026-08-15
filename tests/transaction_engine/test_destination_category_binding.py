"""AUTO authorizes a specific logical destination, not arbitrary movement.

Round-2 correction 1: matching ids alone is insufficient -- the request's
claimed destination_category must match the PolicyDecision's, and the
destination_path's parent must be exactly the configured physical directory
for that category.
"""

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


def test_destination_category_mismatch_is_rejected(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    source = make_source_file("report.txt")
    request = make_request(source, destination_category=DestinationCategory.DOCUMENTS)
    # policy authorized IMAGES, not DOCUMENTS -- the request's own claim disagrees
    policy_decision = make_policy_decision(
        request, destination_category=DestinationCategory.IMAGES
    )
    authorization = ExecutionAuthorization.from_policy_auto(policy_decision)

    engine = TransactionEngine(sandbox_root)
    outcome = engine.prepare(request, authorization)

    assert isinstance(outcome, TransactionResult)
    assert outcome.rejection_code is RejectionCode.DESTINATION_CATEGORY_MISMATCH
    assert source.exists()


def test_documents_pointed_at_executables_folder_is_rejected(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    """DOCUMENTS -> sandbox/Executables/report.txt -- category ids agree,
    but the physical path does not correspond to DOCUMENTS' configured
    directory."""
    source = make_source_file("report.txt")
    wrong_destination = sandbox_root.path / "Executables" / "report.txt"
    request = make_request(
        source,
        destination_category=DestinationCategory.DOCUMENTS,
        destination_path=wrong_destination,
    )
    policy_decision = make_policy_decision(
        request, destination_category=DestinationCategory.DOCUMENTS
    )
    authorization = ExecutionAuthorization.from_policy_auto(policy_decision)

    engine = TransactionEngine(sandbox_root)
    outcome = engine.prepare(request, authorization)

    assert isinstance(outcome, TransactionResult)
    assert outcome.rejection_code is RejectionCode.DESTINATION_CATEGORY_PATH_MISMATCH
    assert source.exists()


def test_documents_pointed_at_arbitrary_folder_is_rejected(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    """DOCUMENTS -> sandbox/arbitrary/report.txt -- an unconfigured folder."""
    source = make_source_file("report.txt")
    arbitrary = sandbox_root.path / "arbitrary"
    arbitrary.mkdir()
    wrong_destination = arbitrary / "report.txt"
    request = make_request(
        source,
        destination_category=DestinationCategory.DOCUMENTS,
        destination_path=wrong_destination,
    )
    policy_decision = make_policy_decision(
        request, destination_category=DestinationCategory.DOCUMENTS
    )
    authorization = ExecutionAuthorization.from_policy_auto(policy_decision)

    engine = TransactionEngine(sandbox_root)
    outcome = engine.prepare(request, authorization)

    assert isinstance(outcome, TransactionResult)
    assert outcome.rejection_code is RejectionCode.DESTINATION_CATEGORY_PATH_MISMATCH


def test_matching_category_and_configured_directory_proceeds(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    source = make_source_file("report.txt")
    request = make_request(source, destination_category=DestinationCategory.DOCUMENTS)
    policy_decision = make_policy_decision(
        request, destination_category=DestinationCategory.DOCUMENTS
    )
    authorization = ExecutionAuthorization.from_policy_auto(policy_decision)

    engine = TransactionEngine(sandbox_root)
    outcome = engine.prepare(request, authorization)

    assert not isinstance(outcome, TransactionResult)
