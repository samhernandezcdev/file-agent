"""FA-017.5: already_undone item-level fact and the batch-level
BatchRecoveryState aggregate. Extends test_history_undo_availability.py's
own real-service/real-store integration style -- undo_available's existing
coverage there is not duplicated here, only the new already_undone/
recovery_state facts derived alongside it."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from file_agent.application import (
    ApplicationOutcomeStatus,
    BatchHistoryEntry,
    FileAgentApplicationService,
)
from file_agent.application.history import BatchRecoveryState
from file_agent.application.queries import LookupFailure
from file_agent.domain import DomainEvent, EntityType, EventType
from file_agent.persistence import FileAgentStore


def _apply_one(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
    name: str,
    content: bytes,
) -> tuple[UUID, UUID]:
    """Returns (batch_id, transaction_id) for a single successfully-applied file."""
    make_source_file(name, content=content)
    item = service.analyze_managed_root(managed_root_id).items[0]
    applied = service.apply_items([item.policy_decision_id])
    assert applied.summary.applied == 1
    entry = service.get_batch_history(applied.batch_id, include_items=True)
    assert isinstance(entry, BatchHistoryEntry)
    assert entry.items is not None
    transaction_id = entry.items[0].transaction_id
    assert transaction_id is not None
    return applied.batch_id, transaction_id


def test_successful_unrecovered_transaction_is_not_already_undone(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
    batch_id, _ = _apply_one(
        service, managed_root_id, make_source_file, "report.pdf", b"pdf content"
    )
    entry = service.get_batch_history(batch_id, include_items=True)
    assert isinstance(entry, BatchHistoryEntry)
    assert entry.items is not None
    assert entry.items[0].undo_available is True
    assert entry.items[0].already_undone is False
    assert entry.recovery_state is BatchRecoveryState.AVAILABLE


def test_recovered_transaction_is_already_undone_and_not_undo_available(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
    batch_id, transaction_id = _apply_one(
        service, managed_root_id, make_source_file, "report.pdf", b"pdf content"
    )
    undo_result = service.undo_transaction(transaction_id)
    assert undo_result.status is ApplicationOutcomeStatus.SUCCEEDED

    entry = service.get_batch_history(batch_id, include_items=True)
    assert isinstance(entry, BatchHistoryEntry)
    assert entry.items is not None
    assert entry.items[0].undo_available is False
    assert entry.items[0].already_undone is True
    assert entry.recovery_state is BatchRecoveryState.FULLY_RECOVERED


def test_rejected_transaction_is_neither_undo_available_nor_already_undone(
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
    assert entry.items[0].already_undone is False
    assert entry.recovery_state is BatchRecoveryState.NONE


def test_malformed_recovery_evidence_never_produces_already_undone_or_fully_recovered(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    """Design Round 3 Task 5 item 6/12: a RECOVERY_SUCCEEDED event that
    cannot be fully reconstructed must never promote the affected item to
    already_undone, and must never let the batch claim FULLY_RECOVERED --
    it stays AVAILABLE (the item's undo_available stays True)."""
    batch_id, real_transaction_id = _apply_one(
        service, managed_root_id, make_source_file, "report.pdf", b"pdf content"
    )
    entry_before = service.get_batch_history(batch_id, include_items=True)
    assert isinstance(entry_before, BatchHistoryEntry)

    # A RECOVERY_SUCCEEDED terminal event with no matching RECOVERY_REQUESTED
    # checkpoint -- find_recovery_result will report this as malformed
    # (mirrors test_history_undo_availability.py's own established
    # malformation technique).
    store.record_event(
        DomainEvent(
            event_type=EventType.RECOVERY_SUCCEEDED,
            entity_type=EntityType.RECOVERY,
            entity_id=uuid4(),
            timestamp=entry_before.started_at,
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
                "evaluated_at": entry_before.started_at.isoformat(),
                "started_at": entry_before.started_at.isoformat(),
                "completed_at": entry_before.started_at.isoformat(),
                "recovery_engine_id": "recovery-engine-v1",
            },
        )
    )

    entry = service.get_batch_history(batch_id, include_items=True)
    assert isinstance(entry, BatchHistoryEntry)
    assert entry.items is not None
    assert entry.items[0].undo_available is True
    assert entry.items[0].already_undone is False
    assert entry.recovery_state is BatchRecoveryState.AVAILABLE


def test_unresolvable_transaction_lookup_fails_the_whole_batch_closed(
    store: FileAgentStore,
) -> None:
    """Design Round 3 §1/§3/Task 5 item 12: a batch whose sole item
    references a transaction_id that has no TRANSACTION_REQUESTED/terminal
    events at all (unresolvable) never reaches recovery_state computation
    -- the whole batch fails closed to a LookupFailure, never a
    BatchHistoryEntry that could wrongly claim FULLY_RECOVERED. Entirely
    hand-crafted events -- no real apply needed, since this specifically
    tests the batch-level fail-closed guarantee itself."""
    from file_agent.application import history as history_module

    batch_id = uuid4()
    policy_decision_id = uuid4()
    bogus_transaction_id = uuid4()
    now = datetime.now(UTC)

    store.record_event(
        DomainEvent(
            event_type=EventType.BATCH_APPLY_STARTED,
            entity_type=EntityType.BATCH,
            entity_id=batch_id,
            timestamp=now,
            payload={
                "batch_id": str(batch_id),
                "requested_policy_decision_ids": [str(policy_decision_id)],
                "managed_root_id": None,
            },
        )
    )
    store.record_event(
        DomainEvent(
            event_type=EventType.BATCH_ITEM_RECORDED,
            entity_type=EntityType.BATCH,
            entity_id=batch_id,
            timestamp=now,
            payload={
                "batch_id": str(batch_id),
                "policy_decision_id": str(policy_decision_id),
                "input_index": 0,
                "item_status": "applied",
                "reason_code": None,
                "transaction_id": str(bogus_transaction_id),
                "file_id": None,
            },
        )
    )

    result = history_module.get_batch_history(store, batch_id, include_items=True)
    assert isinstance(result, LookupFailure)


def test_two_successful_one_recovered_one_not_is_mixed(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
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
    assert first_transaction_id is not None

    undo_result = service.undo_transaction(first_transaction_id)
    assert undo_result.status is ApplicationOutcomeStatus.SUCCEEDED

    entry_after = service.get_batch_history(applied.batch_id, include_items=True)
    assert isinstance(entry_after, BatchHistoryEntry)
    assert entry_after.recovery_state is BatchRecoveryState.MIXED


def test_recovered_transaction_plus_non_successful_item_is_still_fully_recovered(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
    """Design Round 3 Task 5 item 5: a durably-proven-irrelevant item
    (REJECTED/FAILED, never a successful transaction) coexisting with one
    fully-recovered item does not prevent FULLY_RECOVERED."""
    make_source_file("report.pdf", content=b"pdf content")
    make_source_file("app.exe", content=b"exe content")
    analysis = service.analyze_managed_root(managed_root_id)
    ids = [i.policy_decision_id for i in analysis.items]
    applied = service.apply_items(ids)
    assert applied.summary.applied == 1
    assert applied.summary.not_applied == 1

    entry = service.get_batch_history(applied.batch_id, include_items=True)
    assert isinstance(entry, BatchHistoryEntry)
    assert entry.items is not None
    applied_item = next(i for i in entry.items if i.transaction_id is not None)
    transaction_id = applied_item.transaction_id
    assert transaction_id is not None
    undo_result = service.undo_transaction(transaction_id)
    assert undo_result.status is ApplicationOutcomeStatus.SUCCEEDED

    entry_after = service.get_batch_history(applied.batch_id, include_items=True)
    assert isinstance(entry_after, BatchHistoryEntry)
    assert entry_after.recovery_state is BatchRecoveryState.FULLY_RECOVERED
