"""Apply flow: apply_item() resolves trusted state, authorizes, and executes
a real MOVE via TransactionEngine -- never accepting a caller-supplied
TransactionRequest."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from file_agent.application import (
    ApplicationOutcomeStatus,
    ApplyResult,
    FileAgentApplicationService,
)
from file_agent.application.errors import TerminalPersistenceError
from file_agent.domain import EntityType, EventType, PolicyDecision, PolicyOutcome
from file_agent.persistence import AppPaths, FileAgentStore
from file_agent.policy_engine import policy_decision_event
from file_agent.scanner import SandboxRoot

from .conftest import FailOnEventType


def test_auto_applies_and_moves_the_file(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    source = make_source_file("report.pdf", content=b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    item = analysis.items[0]
    assert item.policy_outcome is PolicyOutcome.AUTO

    result = service.apply_item(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.SUCCEEDED
    assert result.transaction_id is not None
    assert not source.exists()
    assert result.destination_path == sandbox_root.path / "Documents" / "report.pdf"
    assert result.destination_path is not None
    assert result.destination_path.read_bytes() == b"pdf content"


def test_review_without_decision_rejects(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("app.exe", content=b"exe content")
    analysis = service.analyze_managed_root(managed_root_id)
    item = analysis.items[0]
    assert item.policy_outcome is PolicyOutcome.REVIEW

    result = service.apply_item(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == "policy_review_without_approval"
    assert result.transaction_id is None


def test_review_with_genuine_approve_applies(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    source = make_source_file("app.exe", content=b"exe content")
    analysis = service.analyze_managed_root(managed_root_id)
    item = analysis.items[0]

    review = service.approve_review(item.policy_decision_id)
    assert review.status is ApplicationOutcomeStatus.SUCCEEDED

    result = service.apply_item(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.SUCCEEDED
    assert not source.exists()
    assert result.destination_path == sandbox_root.path / "Executables" / "app.exe"


def test_review_with_skip_rejects(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("app.exe", content=b"exe content")
    analysis = service.analyze_managed_root(managed_root_id)
    item = analysis.items[0]

    review = service.skip_review(item.policy_decision_id)
    assert review.status is ApplicationOutcomeStatus.SUCCEEDED

    result = service.apply_item(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == "review_outcome_is_skip"


def test_block_rejects(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("report.pdf", content=b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    item = analysis.items[0]

    # PolicyEngine never produces BLOCK in v1 -- hand-craft a BLOCK decision
    # against the same real, persisted proposal to exercise the rule.
    blocked = PolicyDecision(
        proposal_id=item.proposal_id,
        file_id=item.file_id,
        decision=PolicyOutcome.BLOCK,
        reasons=("blocked for test",),
        evaluated_at=datetime.now(UTC),
        policy_engine_id="policy-v1",
        source_category=item.category,
        destination_category=item.proposed_destination_category,
        proposal_confidence=item.confidence,
        proposal_engine_id="rules-v1",
    )
    store.record_event(policy_decision_event(blocked))

    result = service.apply_item(blocked.id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == "policy_block"
    assert result.transaction_id is None


def test_forged_human_review_decision_cannot_authorize(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
    """apply_item's only decision input is queries.find_effective_human_review's
    PERSISTED result -- there is no parameter anywhere through which a
    hand-built HumanReviewDecision could be substituted (see
    test_trust_boundary.py for the structural proof); this test confirms
    the behavioral consequence: without a genuinely recorded, persisted
    review, REVIEW never applies, no matter what a caller might construct
    in memory."""
    make_source_file("app.exe", content=b"exe content")
    analysis = service.analyze_managed_root(managed_root_id)
    item = analysis.items[0]

    # No approve_review()/skip_review() call was ever made -- only a
    # hand-built, never-persisted decision "exists," entirely outside the
    # store. apply_item cannot see it because it never asks for anything
    # but the persisted history.
    result = service.apply_item(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == "policy_review_without_approval"


def test_transaction_requested_persisted_before_commit_terminal_after(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("report.pdf", content=b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    item = analysis.items[0]

    result = service.apply_item(item.policy_decision_id)
    assert result.status is ApplicationOutcomeStatus.SUCCEEDED
    assert result.transaction_id is not None

    events = store.list_events(EntityType.TRANSACTION, result.transaction_id)
    event_types = [e.event_type for e in events]
    assert event_types == [
        EventType.TRANSACTION_REQUESTED,
        EventType.TRANSACTION_SUCCEEDED,
    ]


def test_applying_older_generation_uses_its_own_snapshot_not_latest_hash(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    """The direct regression test for round-2 correction 1: apply_item(D1)
    must use D1's own analysis generation's identity snapshot, never
    whatever the shared DiscoveredFile row currently holds after a LATER
    re-analysis with different content."""
    source = make_source_file("report.pdf", content=b"generation one content")
    first = service.analyze_managed_root(managed_root_id)
    old_item = first.items[0]

    # Re-analyze the SAME file_id with DIFFERENT content -- a new generation,
    # sharing the underlying DiscoveredFile row's mutable sha256 field.
    source.write_bytes(b"generation two, totally different content")
    second = service.analyze_file(old_item.file_id)
    assert second.proposal_id != old_item.proposal_id
    assert second.policy_decision_id != old_item.policy_decision_id

    # Applying the OLDER generation must reverify against generation one's
    # OWN frozen snapshot -- not "latest hash for file_id." The file's
    # current bytes/metadata no longer match that snapshot (content AND
    # mtime changed), so TransactionEngine's own FileHasher-based
    # reverification correctly rejects with SOURCE_IDENTITY_CHANGED --
    # never silently applying using generation two's hash instead, and
    # never using whatever the shared DiscoveredFile row currently holds.
    result = service.apply_item(old_item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == "source_identity_changed"


def test_requested_persist_failure_prevents_commit(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    source = make_source_file("report.pdf", content=b"pdf content")
    plain_service = FileAgentApplicationService(app_paths, store)
    managed_root_id = plain_service.add_managed_root(sandbox_root.path).id
    analysis = plain_service.analyze_managed_root(managed_root_id)
    item = analysis.items[0]

    failing_store = FailOnEventType(store, {EventType.TRANSACTION_REQUESTED})
    service_with_failing_store = FileAgentApplicationService(app_paths, failing_store)  # type: ignore[arg-type]

    with pytest.raises(Exception) as excinfo:
        service_with_failing_store.apply_item(item.policy_decision_id)

    assert not isinstance(excinfo.value, TerminalPersistenceError)
    assert source.exists()
    assert source.read_bytes() == b"pdf content"


def test_terminal_persist_failure_after_success_raises_with_real_result(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    source = make_source_file("report.pdf", content=b"pdf content")
    plain_service = FileAgentApplicationService(app_paths, store)
    managed_root_id = plain_service.add_managed_root(sandbox_root.path).id
    analysis = plain_service.analyze_managed_root(managed_root_id)
    item = analysis.items[0]

    failing_store = FailOnEventType(
        store,
        {
            EventType.TRANSACTION_SUCCEEDED,
            EventType.TRANSACTION_REJECTED,
            EventType.TRANSACTION_FAILED,
        },
    )
    service_with_failing_store = FileAgentApplicationService(app_paths, failing_store)  # type: ignore[arg-type]

    with pytest.raises(TerminalPersistenceError) as excinfo:
        service_with_failing_store.apply_item(item.policy_decision_id)

    result = excinfo.value.result
    assert isinstance(result, ApplyResult)
    assert result.status is ApplicationOutcomeStatus.SUCCEEDED
    assert result.destination_path == sandbox_root.path / "Documents" / "report.pdf"
    assert not source.exists()
    assert result.destination_path is not None
    assert result.destination_path.read_bytes() == b"pdf content"
