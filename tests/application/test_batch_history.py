"""get_batch_history()/list_recent_batch_history() -- pure reconstruction
from durably persisted BATCH_APPLY_STARTED/BATCH_ITEM_RECORDED/
BATCH_APPLY_COMPLETED events. Both share one internal path
(_reconstruct_batch), so a list row is never less authoritative than the
detailed view -- every fail-closed rule proven for one must hold for the
other."""

from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

from file_agent.application import (
    BatchApplyItemStatus,
    BatchHistoryEntry,
    BatchStatus,
    FileAgentApplicationService,
    UnavailableBatchHistoryRow,
    queries,
)
from file_agent.domain import DomainEvent, EntityType, EventType
from file_agent.persistence import AppPaths, FileAgentStore
from file_agent.scanner import SandboxRoot

from .conftest import FailOnEventType


class FailOnNthCallOfType:
    """Like FailOnEventType, but only raises on the Nth (1-indexed) call
    whose event_type matches -- lets a test simulate "the Kth item's
    checkpoint/terminal persist never happens" (e.g. a crash) while earlier
    items of the same event_type genuinely succeed and persist."""

    def __init__(
        self, store: FileAgentStore, event_type: EventType, fail_at: int
    ) -> None:
        self._store = store
        self._event_type = event_type
        self._fail_at = fail_at
        self._count = 0

    def __getattr__(self, name: str) -> object:
        return getattr(self._store, name)

    def record_event(self, event: DomainEvent) -> bool:
        if event.event_type is self._event_type:
            self._count += 1
            if self._count == self._fail_at:
                from file_agent.persistence.errors import DatabaseUnavailableError

                raise DatabaseUnavailableError(
                    f"simulated failure on call {self._count} of {self._event_type}"
                )
        return self._store.record_event(event)


def test_completed_batch_reconstructs_exact_ordered_results(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("a.pdf", content=b"a")
    make_source_file("b.pdf", content=b"b")
    analysis = service.analyze_managed_root(managed_root_id)
    ids = [item.policy_decision_id for item in analysis.items]

    applied = service.apply_items(ids)
    entry = service.get_batch_history(applied.batch_id, include_items=True)

    assert isinstance(entry, BatchHistoryEntry)
    assert entry.status is BatchStatus.COMPLETED
    assert entry.requested_policy_decision_ids == tuple(ids)
    assert entry.selected_count == 2
    assert entry.applied_count == 2
    assert entry.processed_count == 2
    assert entry.items is not None
    assert [i.policy_decision_id for i in entry.items] == ids


def test_get_batch_history_without_include_items_omits_items(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("a.pdf", content=b"a")
    analysis = service.analyze_managed_root(managed_root_id)
    ids = [item.policy_decision_id for item in analysis.items]
    applied = service.apply_items(ids)

    entry = service.get_batch_history(applied.batch_id)

    assert isinstance(entry, BatchHistoryEntry)
    assert entry.items is None
    assert entry.applied_count == 1


def test_incomplete_batch_never_fabricates_unprocessed_remainder(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    """Crash-durability regression: D1 applies with a real TransactionResult,
    then a simulated crash prevents D2 from ever being processed. History
    must show D1 with its real outcome and D2 absent (UNPROCESSED/UNKNOWN),
    never fabricated as NOT_APPLIED."""
    make_source_file("a.pdf", content=b"a")
    make_source_file("b.pdf", content=b"b")
    plain_service = FileAgentApplicationService(app_paths, store)
    managed_root_id = plain_service.add_managed_root(sandbox_root.path).id
    analysis = plain_service.analyze_managed_root(managed_root_id)
    ids = [item.policy_decision_id for item in analysis.items]

    # D1's own checkpoint genuinely persists; D2's checkpoint persist is
    # where the simulated crash happens -- D2 is never processed at all.
    failing_store = FailOnNthCallOfType(store, EventType.BATCH_ITEM_RECORDED, fail_at=2)
    failing_service = FileAgentApplicationService(app_paths, failing_store)  # type: ignore[arg-type]
    result = failing_service.apply_items(ids)
    assert result.status is BatchStatus.INCOMPLETE

    entry = plain_service.get_batch_history(result.batch_id, include_items=True)

    assert isinstance(entry, BatchHistoryEntry)
    assert entry.status is BatchStatus.INCOMPLETE
    assert entry.completed_at is None
    assert entry.selected_count == 2
    assert entry.processed_count == 1
    assert entry.items is not None
    assert [i.policy_decision_id for i in entry.items] == [ids[0]]


def test_review_pending_and_block_outcomes_survive_a_crash(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    """D2 (REVIEW pending) and D3 (BLOCK) never touch TransactionEngine at
    all -- their own BATCH_ITEM_RECORDED checkpoint is the SOLE durable
    record of their outcome. A crash before D4 must not lose them."""
    make_source_file("applied.pdf", content=b"a")
    make_source_file("pending.exe", content=b"b")
    plain_service = FileAgentApplicationService(app_paths, store)
    managed_root_id = plain_service.add_managed_root(sandbox_root.path).id
    analysis = plain_service.analyze_managed_root(managed_root_id)
    applied_item, pending_item = analysis.items
    ids = [applied_item.policy_decision_id, pending_item.policy_decision_id]

    failing_store = FailOnEventType(store, {EventType.BATCH_APPLY_COMPLETED})
    failing_service = FileAgentApplicationService(app_paths, failing_store)  # type: ignore[arg-type]
    result = failing_service.apply_items(ids)
    assert result.status is BatchStatus.INCOMPLETE
    assert result.items[1].status is BatchApplyItemStatus.NOT_APPLIED

    entry = plain_service.get_batch_history(result.batch_id, include_items=True)
    assert isinstance(entry, BatchHistoryEntry)
    assert entry.items is not None
    assert entry.items[1].status is BatchApplyItemStatus.NOT_APPLIED
    assert entry.items[1].reason_code == "policy_review_without_approval"


def test_terminal_persist_failure_item_is_unprocessed_in_durable_history(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    """The precise distinction FA-014 round-2 exists to draw: the in-process
    BatchApplyResult for THIS call reports APPLIED (runtime knows the real
    outcome), but durable history has no checkpoint for it at all -- never
    APPLIED, never NOT_APPLIED."""
    make_source_file("a.pdf", content=b"a")
    plain_service = FileAgentApplicationService(app_paths, store)
    managed_root_id = plain_service.add_managed_root(sandbox_root.path).id
    analysis = plain_service.analyze_managed_root(managed_root_id)
    ids = [item.policy_decision_id for item in analysis.items]

    failing_store = FailOnEventType(
        store,
        {
            EventType.TRANSACTION_SUCCEEDED,
            EventType.TRANSACTION_REJECTED,
            EventType.TRANSACTION_FAILED,
        },
    )
    failing_service = FileAgentApplicationService(app_paths, failing_store)  # type: ignore[arg-type]
    result = failing_service.apply_items(ids)
    assert result.items[0].status is BatchApplyItemStatus.APPLIED

    entry = plain_service.get_batch_history(result.batch_id, include_items=True)
    assert isinstance(entry, BatchHistoryEntry)
    assert entry.processed_count == 0
    assert entry.items == ()


def test_duplicate_started_events_fail_closed_ambiguous(
    service: FileAgentApplicationService, store: FileAgentStore
) -> None:
    batch_id = uuid4()
    for _ in range(2):
        store.record_event(
            DomainEvent(
                event_type=EventType.BATCH_APPLY_STARTED,
                entity_type=EntityType.BATCH,
                entity_id=batch_id,
                payload={
                    "batch_id": str(batch_id),
                    "requested_policy_decision_ids": [],
                },
            )
        )

    entry = service.get_batch_history(batch_id)

    assert isinstance(entry, queries.LookupFailure)
    assert entry.status is queries.LookupStatus.AMBIGUOUS


def test_structural_incompleteness_under_completed_fails_closed_malformed(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
    store: FileAgentStore,
) -> None:
    """A COMPLETED batch missing one selected id's BATCH_ITEM_RECORDED
    contradicts its own sequencing contract (BATCH_APPLY_COMPLETED only
    ever persists after every checkpoint already succeeded) -- reconstructed
    history must fail closed rather than silently tolerate the gap."""
    make_source_file("a.pdf", content=b"a")
    make_source_file("b.pdf", content=b"b")
    analysis = service.analyze_managed_root(managed_root_id)
    ids = [item.policy_decision_id for item in analysis.items]
    applied = service.apply_items(ids)
    assert applied.status is BatchStatus.COMPLETED

    # Corrupt the persisted history directly: delete is not available on the
    # store, so instead hand-build a NEW batch_id with a STARTED for 2 ids,
    # only 1 checkpoint, and a COMPLETED claiming success for both --
    # simulates a missing checkpoint under an otherwise-valid COMPLETED
    # batch without needing store-level deletion.
    batch_id = uuid4()
    store.record_event(
        DomainEvent(
            event_type=EventType.BATCH_APPLY_STARTED,
            entity_type=EntityType.BATCH,
            entity_id=batch_id,
            payload={
                "batch_id": str(batch_id),
                "requested_policy_decision_ids": [str(ids[0]), str(ids[1])],
            },
        )
    )
    store.record_event(
        DomainEvent(
            event_type=EventType.BATCH_ITEM_RECORDED,
            entity_type=EntityType.BATCH,
            entity_id=batch_id,
            payload={
                "batch_id": str(batch_id),
                "policy_decision_id": str(ids[0]),
                "input_index": 0,
                "item_status": "not_applied",
                "reason_code": "policy_block",
                "transaction_id": None,
            },
        )
    )
    store.record_event(
        DomainEvent(
            event_type=EventType.BATCH_APPLY_COMPLETED,
            entity_type=EntityType.BATCH,
            entity_id=batch_id,
            payload={
                "batch_id": str(batch_id),
                "selected": 2,
                "processed": 2,
                "applied": 0,
                "not_applied": 2,
                "skipped": 0,
                "invalid": 0,
            },
        )
    )

    entry = service.get_batch_history(batch_id)

    assert isinstance(entry, queries.LookupFailure)
    assert entry.status is queries.LookupStatus.MALFORMED


def test_completed_summary_disagreement_fails_closed_malformed(
    service: FileAgentApplicationService, store: FileAgentStore
) -> None:
    d1 = uuid4()
    batch_id = uuid4()
    store.record_event(
        DomainEvent(
            event_type=EventType.BATCH_APPLY_STARTED,
            entity_type=EntityType.BATCH,
            entity_id=batch_id,
            payload={
                "batch_id": str(batch_id),
                "requested_policy_decision_ids": [str(d1)],
            },
        )
    )
    store.record_event(
        DomainEvent(
            event_type=EventType.BATCH_ITEM_RECORDED,
            entity_type=EntityType.BATCH,
            entity_id=batch_id,
            payload={
                "batch_id": str(batch_id),
                "policy_decision_id": str(d1),
                "input_index": 0,
                "item_status": "not_applied",
                "reason_code": "policy_block",
                "transaction_id": None,
            },
        )
    )
    # Persisted summary lies: claims 1 applied, but the only checkpoint is
    # not_applied.
    store.record_event(
        DomainEvent(
            event_type=EventType.BATCH_APPLY_COMPLETED,
            entity_type=EntityType.BATCH,
            entity_id=batch_id,
            payload={
                "batch_id": str(batch_id),
                "selected": 1,
                "processed": 1,
                "applied": 1,
                "not_applied": 0,
                "skipped": 0,
                "invalid": 0,
            },
        )
    )

    entry = service.get_batch_history(batch_id)

    assert isinstance(entry, queries.LookupFailure)
    assert entry.status is queries.LookupStatus.MALFORMED


def test_checkpoint_lineage_mismatch_fails_closed_malformed(
    service: FileAgentApplicationService, store: FileAgentStore
) -> None:
    d1 = uuid4()
    d2 = uuid4()
    batch_id = uuid4()
    store.record_event(
        DomainEvent(
            event_type=EventType.BATCH_APPLY_STARTED,
            entity_type=EntityType.BATCH,
            entity_id=batch_id,
            payload={
                "batch_id": str(batch_id),
                "requested_policy_decision_ids": [str(d1)],
            },
        )
    )
    # Wrong policy_decision_id at input_index 0.
    store.record_event(
        DomainEvent(
            event_type=EventType.BATCH_ITEM_RECORDED,
            entity_type=EntityType.BATCH,
            entity_id=batch_id,
            payload={
                "batch_id": str(batch_id),
                "policy_decision_id": str(d2),
                "input_index": 0,
                "item_status": "not_applied",
                "reason_code": "policy_block",
                "transaction_id": None,
            },
        )
    )

    entry = service.get_batch_history(batch_id, include_items=True)

    assert isinstance(entry, queries.LookupFailure)
    assert entry.status is queries.LookupStatus.MALFORMED


def test_duplicate_checkpoint_input_index_fails_closed_ambiguous(
    service: FileAgentApplicationService, store: FileAgentStore
) -> None:
    d1 = uuid4()
    d2 = uuid4()
    batch_id = uuid4()
    store.record_event(
        DomainEvent(
            event_type=EventType.BATCH_APPLY_STARTED,
            entity_type=EntityType.BATCH,
            entity_id=batch_id,
            payload={
                "batch_id": str(batch_id),
                "requested_policy_decision_ids": [str(d1), str(d2)],
            },
        )
    )
    for pid in (d1, d2):
        store.record_event(
            DomainEvent(
                event_type=EventType.BATCH_ITEM_RECORDED,
                entity_type=EntityType.BATCH,
                entity_id=batch_id,
                payload={
                    "batch_id": str(batch_id),
                    "policy_decision_id": str(pid),
                    "input_index": 0,  # duplicate index across 2 records
                    "item_status": "not_applied",
                    "reason_code": "policy_block",
                    "transaction_id": None,
                },
            )
        )

    entry = service.get_batch_history(batch_id)

    assert isinstance(entry, queries.LookupFailure)
    assert entry.status is queries.LookupStatus.AMBIGUOUS


def test_transaction_ownership_mismatch_fails_closed_malformed(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
    store: FileAgentStore,
) -> None:
    """A checkpoint referencing a genuine, resolvable transaction_id that
    belongs to a DIFFERENT batch must never be trusted just because it
    resolves -- round-5 correction 1."""
    make_source_file("a.pdf", content=b"a")
    analysis = service.analyze_managed_root(managed_root_id)
    real_item = analysis.items[0]
    real_result = service.apply_items([real_item.policy_decision_id])
    real_transaction_id = real_result.items[0].transaction_id
    assert real_transaction_id is not None

    foreign_batch_id = uuid4()
    foreign_policy_decision_id = uuid4()
    store.record_event(
        DomainEvent(
            event_type=EventType.BATCH_APPLY_STARTED,
            entity_type=EntityType.BATCH,
            entity_id=foreign_batch_id,
            payload={
                "batch_id": str(foreign_batch_id),
                "requested_policy_decision_ids": [str(foreign_policy_decision_id)],
            },
        )
    )
    store.record_event(
        DomainEvent(
            event_type=EventType.BATCH_ITEM_RECORDED,
            entity_type=EntityType.BATCH,
            entity_id=foreign_batch_id,
            payload={
                "batch_id": str(foreign_batch_id),
                "policy_decision_id": str(foreign_policy_decision_id),
                "input_index": 0,
                "item_status": "applied",
                "reason_code": None,
                # Genuinely resolvable, but belongs to the OTHER batch/id.
                "transaction_id": str(real_transaction_id),
            },
        )
    )

    entry = service.get_batch_history(foreign_batch_id)

    assert isinstance(entry, queries.LookupFailure)
    assert entry.status is queries.LookupStatus.MALFORMED


def test_list_and_detail_report_identical_counts_for_a_valid_batch(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("a.pdf", content=b"a")
    make_source_file("b.pdf", content=b"b")
    analysis = service.analyze_managed_root(managed_root_id)
    ids = [item.policy_decision_id for item in analysis.items]
    applied = service.apply_items(ids)

    detail = service.get_batch_history(applied.batch_id)
    rows = service.list_recent_batch_history()
    row = next(r for r in rows if r.batch_id == applied.batch_id)

    assert isinstance(detail, BatchHistoryEntry)
    assert isinstance(row, BatchHistoryEntry)
    assert row.applied_count == detail.applied_count
    assert row.not_applied_count == detail.not_applied_count
    assert row.selected_count == detail.selected_count
    assert row.status is detail.status


def test_list_shows_unavailable_row_for_malformed_batch_never_false_counts(
    service: FileAgentApplicationService, store: FileAgentStore
) -> None:
    d1 = uuid4()
    batch_id = uuid4()
    store.record_event(
        DomainEvent(
            event_type=EventType.BATCH_APPLY_STARTED,
            entity_type=EntityType.BATCH,
            entity_id=batch_id,
            payload={
                "batch_id": str(batch_id),
                "requested_policy_decision_ids": [str(d1)],
            },
        )
    )
    store.record_event(
        DomainEvent(
            event_type=EventType.BATCH_APPLY_COMPLETED,
            entity_type=EntityType.BATCH,
            entity_id=batch_id,
            payload={
                "batch_id": str(batch_id),
                "selected": 1,
                "processed": 1,
                "applied": 1,
                "not_applied": 0,
                "skipped": 0,
                "invalid": 0,
            },
        )
    )  # COMPLETED with zero checkpoints at all -- structurally impossible.

    rows = service.list_recent_batch_history()
    row = next(r for r in rows if r.batch_id == batch_id)

    assert isinstance(row, UnavailableBatchHistoryRow)
    assert row.started_at is not None


def test_list_ambiguous_started_produces_one_row_with_none_started_at(
    service: FileAgentApplicationService, store: FileAgentStore
) -> None:
    batch_id = uuid4()
    for _ in range(2):
        store.record_event(
            DomainEvent(
                event_type=EventType.BATCH_APPLY_STARTED,
                entity_type=EntityType.BATCH,
                entity_id=batch_id,
                payload={
                    "batch_id": str(batch_id),
                    "requested_policy_decision_ids": [],
                },
            )
        )

    rows = service.list_recent_batch_history()
    matches = [r for r in rows if r.batch_id == batch_id]

    assert len(matches) == 1
    assert isinstance(matches[0], UnavailableBatchHistoryRow)
    assert matches[0].started_at is None
