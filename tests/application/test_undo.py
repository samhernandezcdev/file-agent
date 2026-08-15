"""Undo flow: undo_transaction() resolves a genuinely persisted, SUCCEEDED
transaction, reconstructs CompletedMoveEvidence internally, and reverses it
via RecoveryEngine -- the caller supplies only a transaction_id."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from file_agent.application import (
    ApplicationOutcomeStatus,
    ApplyResult,
    FileAgentApplicationService,
    UndoResult,
)
from file_agent.application.errors import TerminalPersistenceError
from file_agent.domain import (
    DestinationCategory,
    EntityType,
    EventType,
    TransactionOperation,
    TransactionResult,
    TransactionStatus,
)
from file_agent.persistence import AppPaths, FileAgentStore
from file_agent.scanner import SandboxRoot
from file_agent.transaction_engine import transaction_result_event

from .conftest import FailOnEventType


def _apply_auto(
    service: FileAgentApplicationService,
    make_source_file: Callable[..., Path],
    name: str,
    content: bytes,
) -> tuple[Path, ApplyResult]:
    make_source_file(name, content=content)
    item = service.analyze_scan().items[0]
    result = service.apply_item(item.policy_decision_id)
    assert result.status is ApplicationOutcomeStatus.SUCCEEDED
    return result.destination_path, result


def test_genuine_successful_transaction_undoes(
    service: FileAgentApplicationService,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    destination, apply_result = _apply_auto(
        service, make_source_file, "report.pdf", b"pdf content"
    )

    result = service.undo_transaction(apply_result.transaction_id)

    assert result.status is ApplicationOutcomeStatus.SUCCEEDED
    assert not destination.exists()
    original = sandbox_root.path / "report.pdf"
    assert original.exists()
    assert original.read_bytes() == b"pdf content"


def test_non_successful_transaction_rejected(
    service: FileAgentApplicationService,
    make_source_file: Callable[..., Path],
) -> None:
    _destination, apply_result = _apply_auto(
        service, make_source_file, "report.pdf", b"pdf content"
    )

    # Re-applying the same (already-moved) policy decision produces a
    # genuine REJECTED TransactionResult (source no longer at its original
    # path) with its own fresh transaction id.
    item_id = apply_result.policy_decision_id
    second = service.apply_item(item_id)
    assert second.status is ApplicationOutcomeStatus.REJECTED
    assert second.transaction_id is not None

    result = service.undo_transaction(second.transaction_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == "original_transaction_not_succeeded"


def test_unknown_transaction_id_rejected(service: FileAgentApplicationService) -> None:
    result = service.undo_transaction(uuid4())
    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == "transaction_not_found"


def test_requested_without_terminal_cannot_undo(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    plain_service = FileAgentApplicationService(sandbox_root, app_paths, store)
    make_source_file("report.pdf", content=b"pdf content")
    item = plain_service.analyze_scan().items[0]

    failing_store = FailOnEventType(
        store,
        {
            EventType.TRANSACTION_SUCCEEDED,
            EventType.TRANSACTION_REJECTED,
            EventType.TRANSACTION_FAILED,
        },
    )
    failing_service = FileAgentApplicationService(
        sandbox_root, app_paths, failing_store
    )  # type: ignore[arg-type]
    with pytest.raises(TerminalPersistenceError) as excinfo:
        failing_service.apply_item(item.policy_decision_id)
    transaction_id = excinfo.value.result.transaction_id
    assert transaction_id is not None

    result = plain_service.undo_transaction(transaction_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == "requested_without_terminal"


def test_conflicting_terminal_history_fails_closed(
    service: FileAgentApplicationService,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    destination, apply_result = _apply_auto(
        service, make_source_file, "report.pdf", b"pdf content"
    )
    transaction_id = apply_result.transaction_id

    # Hand-craft and persist a SECOND, conflicting terminal event for the
    # same transaction id (simulating corrupted/duplicated history).
    conflicting = TransactionResult(
        request_id=transaction_id,
        file_id=uuid4(),
        proposal_id=uuid4(),
        policy_decision_id=uuid4(),
        operation=TransactionOperation.MOVE,
        source_path=destination,
        destination_path=destination,
        destination_category=DestinationCategory.DOCUMENTS,
        expected_sha256="b" * 64,
        expected_size=1,
        status=TransactionStatus.FAILED,
        failure_reason="conflicting synthetic failure",
        evaluated_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        transaction_engine_id="v1",
    )
    store.record_event(transaction_result_event(conflicting))

    result = service.undo_transaction(transaction_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == "ambiguous_transaction_history"


def test_current_destination_changed_propagates_safe_rejection(
    service: FileAgentApplicationService,
    make_source_file: Callable[..., Path],
) -> None:
    destination, apply_result = _apply_auto(
        service, make_source_file, "report.pdf", b"pdf content"
    )
    destination.write_bytes(b"tampered content, different length entirely")

    result = service.undo_transaction(apply_result.transaction_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code in ("current_file_changed", "current_file_missing")
    assert destination.read_bytes() == b"tampered content, different length entirely"


def test_recovery_requested_persisted_before_commit_terminal_after(
    service: FileAgentApplicationService,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    _destination, apply_result = _apply_auto(
        service, make_source_file, "report.pdf", b"pdf content"
    )

    result = service.undo_transaction(apply_result.transaction_id)
    assert result.status is ApplicationOutcomeStatus.SUCCEEDED
    assert result.recovery_id is not None

    events = store.list_events(EntityType.RECOVERY, result.recovery_id)
    event_types = [e.event_type for e in events]
    assert event_types == [EventType.RECOVERY_REQUESTED, EventType.RECOVERY_SUCCEEDED]


def test_undo_requested_persist_failure_prevents_commit(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    plain_service = FileAgentApplicationService(sandbox_root, app_paths, store)
    destination, apply_result = _apply_auto(
        plain_service, make_source_file, "report.pdf", b"pdf content"
    )

    failing_store = FailOnEventType(store, {EventType.RECOVERY_REQUESTED})
    failing_service = FileAgentApplicationService(
        sandbox_root, app_paths, failing_store
    )  # type: ignore[arg-type]

    with pytest.raises(Exception) as excinfo:
        failing_service.undo_transaction(apply_result.transaction_id)

    assert not isinstance(excinfo.value, TerminalPersistenceError)
    assert destination.exists()  # commit() never ran


def test_undo_terminal_persist_failure_raises_with_real_result(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    plain_service = FileAgentApplicationService(sandbox_root, app_paths, store)
    destination, apply_result = _apply_auto(
        plain_service, make_source_file, "report.pdf", b"pdf content"
    )

    failing_store = FailOnEventType(
        store,
        {
            EventType.RECOVERY_SUCCEEDED,
            EventType.RECOVERY_REJECTED,
            EventType.RECOVERY_FAILED,
        },
    )
    failing_service = FileAgentApplicationService(
        sandbox_root, app_paths, failing_store
    )  # type: ignore[arg-type]

    with pytest.raises(TerminalPersistenceError) as excinfo:
        failing_service.undo_transaction(apply_result.transaction_id)

    result = excinfo.value.result
    assert isinstance(result, UndoResult)
    assert result.status is ApplicationOutcomeStatus.SUCCEEDED
    assert not destination.exists()
    original = sandbox_root.path / "report.pdf"
    assert original.read_bytes() == b"pdf content"
