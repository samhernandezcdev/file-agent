"""FA-017.3 (Round 2 Major 1): BATCH_ITEM_RECORDED persists file_id -- a
semantic identity fact -- never a display string. History derives
filename/source/destination from durable facts: the resolved
TransactionResult when a transaction_id is present, otherwise
store.get_discovered_file(file_id). A pre-FA-017.3 row (no file_id key at
all) or a file_id whose discovery record is gone must reconstruct honestly
(None fields), never fabricate a value."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from file_agent.application import BatchHistoryEntry, FileAgentApplicationService
from file_agent.domain import DomainEvent, EntityType, EventType
from file_agent.persistence import FileAgentStore
from file_agent.scanner import SandboxRoot


def test_batch_item_recorded_persists_file_id_but_not_display_strings(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("report.pdf", content=b"pdf content")
    item = service.analyze_managed_root(managed_root_id).items[0]
    applied = service.apply_items([item.policy_decision_id])

    events = store.list_events(EntityType.BATCH, applied.batch_id)
    item_recorded = [e for e in events if e.event_type is EventType.BATCH_ITEM_RECORDED]
    assert len(item_recorded) == 1
    payload = item_recorded[0].payload

    assert payload["file_id"] == str(item.file_id)
    assert "filename" not in payload
    assert "source_display_path" not in payload
    assert "destination_display_path" not in payload


def test_history_reconstructs_filename_source_destination_for_transaction_linked_item(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("report.pdf", content=b"pdf content")
    item = service.analyze_managed_root(managed_root_id).items[0]
    applied = service.apply_items([item.policy_decision_id])

    entry = service.get_batch_history(applied.batch_id, include_items=True)
    assert isinstance(entry, BatchHistoryEntry)
    assert entry.items is not None
    history_item = entry.items[0]

    assert history_item.filename == "report.pdf"
    assert history_item.source_path == sandbox_root.path / "report.pdf"
    assert (
        history_item.destination_path == sandbox_root.path / "Documents" / "report.pdf"
    )


def test_history_reconstructs_filename_and_source_for_early_rejected_item_via_file_id(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    """A REVIEW item with no approval is rejected before TransactionEngine
    -- no transaction_id, so filename/source must come from file_id."""
    make_source_file("app.exe", content=b"exe content")
    item = service.analyze_managed_root(managed_root_id).items[0]
    applied = service.apply_items([item.policy_decision_id])

    entry = service.get_batch_history(applied.batch_id, include_items=True)
    assert isinstance(entry, BatchHistoryEntry)
    assert entry.items is not None
    history_item = entry.items[0]

    assert history_item.transaction_id is None
    assert history_item.filename == "app.exe"
    assert history_item.source_path == sandbox_root.path / "app.exe"
    assert history_item.destination_path is None


def test_history_with_file_id_whose_discovery_record_is_gone_is_honest_not_fabricated(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    """Simulates a file_id that was persisted but whose discovery record
    cannot be resolved (store.get_discovered_file returns None) -- direct,
    hand-crafted event, since this state cannot arise through the normal
    API (discovery rows are never deleted)."""
    batch_id = uuid4()
    policy_decision_id = uuid4()
    bogus_file_id = uuid4()
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
                "item_status": "not_applied",
                "reason_code": "policy_block",
                "transaction_id": None,
                "file_id": str(bogus_file_id),
            },
        )
    )
    store.record_event(
        DomainEvent(
            event_type=EventType.BATCH_APPLY_COMPLETED,
            entity_type=EntityType.BATCH,
            entity_id=batch_id,
            timestamp=now,
            payload={
                "batch_id": str(batch_id),
                "selected": 1,
                "processed": 1,
                "applied": 0,
                "not_applied": 1,
                "skipped": 0,
                "invalid": 0,
            },
        )
    )

    entry = service.get_batch_history(batch_id, include_items=True)
    assert isinstance(entry, BatchHistoryEntry)
    assert entry.items is not None
    history_item = entry.items[0]

    assert history_item.filename is None
    assert history_item.source_path is None


def test_old_batch_item_recorded_without_file_id_reconstructs_honestly(
    service: FileAgentApplicationService,
    store: FileAgentStore,
) -> None:
    """A pre-FA-017.3 BATCH_ITEM_RECORDED payload simply has no "file_id"
    key at all -- must parse and reconstruct without crashing, and never
    guess a filename."""
    batch_id = uuid4()
    policy_decision_id = uuid4()
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
                "item_status": "not_applied",
                "reason_code": "policy_block",
                "transaction_id": None,
                # deliberately no "file_id" key -- pre-FA-017.3 shape
            },
        )
    )
    store.record_event(
        DomainEvent(
            event_type=EventType.BATCH_APPLY_COMPLETED,
            entity_type=EntityType.BATCH,
            entity_id=batch_id,
            timestamp=now,
            payload={
                "batch_id": str(batch_id),
                "selected": 1,
                "processed": 1,
                "applied": 0,
                "not_applied": 1,
                "skipped": 0,
                "invalid": 0,
            },
        )
    )

    entry = service.get_batch_history(batch_id, include_items=True)
    assert isinstance(entry, BatchHistoryEntry)
    assert entry.items is not None
    history_item = entry.items[0]

    assert history_item.filename is None
    assert history_item.source_path is None
    assert history_item.status.value == "not_applied"
