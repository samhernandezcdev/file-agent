"""FA-017.3 (Round 2 -- "already undone" awareness): undo_available means
durable evidence permits OFFERING Deshacer, never a guarantee it will
succeed. True requires: transaction_id resolves to a SUCCEEDED
TransactionResult AND no validated RECOVERY_SUCCEEDED event exists for
that exact original_transaction_id. Malformed/unrelated recovery events
are non-evidence -- they must never falsely mark another transaction
already undone."""

from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

from file_agent.application import (
    ApplicationOutcomeStatus,
    BatchHistoryEntry,
    FileAgentApplicationService,
)
from file_agent.application.queries import find_successful_recoveries
from file_agent.domain import DomainEvent, EntityType, EventType
from file_agent.persistence import FileAgentStore


def _apply_one(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
    name: str,
    content: bytes,
) -> UUID:
    make_source_file(name, content=content)
    item = service.analyze_managed_root(managed_root_id).items[0]
    applied = service.apply_items([item.policy_decision_id])
    assert applied.summary.applied == 1
    return applied.batch_id


def test_successful_transaction_with_no_recovery_is_undo_available(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
    batch_id = _apply_one(
        service, managed_root_id, make_source_file, "report.pdf", b"pdf content"
    )
    entry = service.get_batch_history(batch_id, include_items=True)
    assert isinstance(entry, BatchHistoryEntry)
    assert entry.items is not None
    assert entry.items[0].undo_available is True


def test_exact_matching_successful_recovery_marks_undo_unavailable(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
    batch_id = _apply_one(
        service, managed_root_id, make_source_file, "report.pdf", b"pdf content"
    )
    entry_before = service.get_batch_history(batch_id, include_items=True)
    assert isinstance(entry_before, BatchHistoryEntry)
    assert entry_before.items is not None
    transaction_id = entry_before.items[0].transaction_id
    assert transaction_id is not None

    undo_result = service.undo_transaction(transaction_id)
    assert undo_result.status is ApplicationOutcomeStatus.SUCCEEDED

    entry_after = service.get_batch_history(batch_id, include_items=True)
    assert isinstance(entry_after, BatchHistoryEntry)
    assert entry_after.items is not None
    assert entry_after.items[0].undo_available is False


def test_rejected_and_failed_transactions_are_never_undo_available(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("app.exe", content=b"exe content")
    item = service.analyze_managed_root(managed_root_id).items[0]
    applied = service.apply_items([item.policy_decision_id])
    assert applied.summary.not_applied == 1

    entry = service.get_batch_history(applied.batch_id, include_items=True)
    assert isinstance(entry, BatchHistoryEntry)
    assert entry.items is not None
    assert entry.items[0].undo_available is False


def test_unrelated_recovery_does_not_suppress_a_different_transactions_undo(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    """find_successful_recoveries must key strictly on
    original_transaction_id -- a real RECOVERY_SUCCEEDED for some OTHER
    transaction must never leak into this one's undo_available."""
    make_source_file("a.pdf", content=b"a")
    make_source_file("b.pdf", content=b"b")
    analysis = service.analyze_managed_root(managed_root_id)
    ids = [i.policy_decision_id for i in analysis.items]
    applied = service.apply_items(ids)
    assert applied.summary.applied == 2

    entry = service.get_batch_history(applied.batch_id, include_items=True)
    assert isinstance(entry, BatchHistoryEntry)
    assert entry.items is not None
    first_transaction_id = entry.items[0].transaction_id
    second_transaction_id = entry.items[1].transaction_id
    assert first_transaction_id is not None
    assert second_transaction_id is not None

    # Undo only the first -- a real RECOVERY_SUCCEEDED now genuinely exists,
    # but keyed to first_transaction_id, not second_transaction_id.
    undo_result = service.undo_transaction(first_transaction_id)
    assert undo_result.status is ApplicationOutcomeStatus.SUCCEEDED

    entry_after = service.get_batch_history(applied.batch_id, include_items=True)
    assert isinstance(entry_after, BatchHistoryEntry)
    assert entry_after.items is not None
    by_transaction = {i.transaction_id: i for i in entry_after.items}
    assert by_transaction[first_transaction_id].undo_available is False
    assert by_transaction[second_transaction_id].undo_available is True


def test_malformed_recovery_event_is_non_evidence_and_does_not_suppress_undo(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    """A RECOVERY_SUCCEEDED event that cannot be fully reconstructed
    (missing required checkpoint) is skipped as non-evidence -- it must
    not falsely mark a real, unrelated transaction as already undone."""
    batch_id = _apply_one(
        service, managed_root_id, make_source_file, "report.pdf", b"pdf content"
    )
    entry = service.get_batch_history(batch_id, include_items=True)
    assert isinstance(entry, BatchHistoryEntry)
    assert entry.items is not None
    real_transaction_id = entry.items[0].transaction_id
    assert real_transaction_id is not None

    # A RECOVERY_SUCCEEDED terminal event with no matching RECOVERY_REQUESTED
    # checkpoint -- find_recovery_result will report this as malformed.
    store.record_event(
        DomainEvent(
            event_type=EventType.RECOVERY_SUCCEEDED,
            entity_type=EntityType.RECOVERY,
            entity_id=uuid4(),
            timestamp=entry.started_at,
            payload={
                "operation": "reverse_move",
                "file_id": str(uuid4()),
                "original_transaction_id": str(real_transaction_id),
                "source_path": None,
                "destination_path": "C:/sandbox/report.pdf",
                "expected_sha256": "a" * 64,
                "vault_object_path": None,
                "status": "succeeded",
                "rejection_code": None,
                "failure_reason": None,
                "verified_sha256": "a" * 64,
                "evaluated_at": entry.started_at.isoformat(),
                "started_at": entry.started_at.isoformat(),
                "completed_at": entry.started_at.isoformat(),
                "recovery_engine_id": "recovery-engine-v1",
            },
        )
    )

    recoveries = find_successful_recoveries(store)
    assert real_transaction_id not in recoveries

    entry_after = service.get_batch_history(batch_id, include_items=True)
    assert isinstance(entry_after, BatchHistoryEntry)
    assert entry_after.items is not None
    assert entry_after.items[0].undo_available is True


def test_find_successful_recoveries_returns_empty_when_none_exist(
    store: FileAgentStore,
) -> None:
    assert find_successful_recoveries(store) == {}
