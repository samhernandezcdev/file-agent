"""Batch history read model (FA-014) -- pure reconstruction from durably
persisted events, zero mutation, zero engine calls. Mirrors application/
queries.py's own "found | structured failure" profile, and reuses
queries.find_transaction_result directly for authoritative cross-
verification -- this module owns batch-specific payload shapes
(BATCH_APPLY_STARTED/BATCH_ITEM_RECORDED/BATCH_APPLY_COMPLETED), which
queries.py deliberately does not know about.

get_batch_history and list_recent_batch_history both delegate to the single
private _reconstruct_batch -- a list row is never less authoritative than
the detailed view, only less verbose (FA-014 round-4 correction). Both run
the complete integrity chain: STARTED/COMPLETED resolution, BATCH_ITEM_
RECORDED lineage validation against STARTED, status-dependent completeness,
TransactionResult cross-verification (with batch/policy_decision ownership
proof, not just existence -- round-5 correction 1), and, for COMPLETED
batches, terminal-summary agreement. Any inconsistency fails closed; nothing
is ever silently repaired or guessed from filesystem state or timestamp/
UUID ordering.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from file_agent.application import queries
from file_agent.application.dto import (
    BatchApplyItemResult,
    BatchApplyItemStatus,
    BatchApplySummary,
    BatchStatus,
)
from file_agent.domain import (
    DomainEvent,
    EntityType,
    EventType,
    TransactionResult,
    TransactionStatus,
)
from file_agent.persistence import FileAgentStore


@dataclass(frozen=True, slots=True)
class BatchHistoryItem:
    policy_decision_id: UUID
    input_index: int
    status: BatchApplyItemStatus
    transaction_id: UUID | None
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class BatchHistoryEntry:
    batch_id: UUID
    started_at: datetime
    completed_at: datetime | None
    """None iff status is INCOMPLETE."""
    status: BatchStatus
    requested_policy_decision_ids: tuple[UUID, ...]
    managed_root_id: UUID | None
    """FA-015: cross-verified (not merely copied) against every selected
    id's independently-resolvable lineage -- see _reconstruct_batch's step
    2. None for a legacy pre-FA-015 batch, in which case no cross-check is
    ever attempted (never retroactively inferred)."""
    selected_count: int
    applied_count: int
    not_applied_count: int
    skipped_count: int
    invalid_count: int
    processed_count: int
    items: tuple[BatchHistoryItem, ...] | None
    """None unless include_items=True was requested."""


@dataclass(frozen=True, slots=True)
class UnavailableBatchHistoryRow:
    """A row-level, read-model-only state for list rendering -- NOT a
    persisted BatchStatus, NOT used anywhere in apply_items' execution
    semantics. Exists solely so one malformed/ambiguous historical batch
    can be shown honestly in a list of otherwise-valid recent batches,
    without either fabricating its counts or silently dropping the row."""

    batch_id: UUID
    started_at: datetime | None
    """None specifically when BATCH_APPLY_STARTED itself is ambiguous/
    unresolvable -- no genuine single start time exists to report. Populated
    with the genuine STARTED event's own timestamp whenever exactly one
    trustworthy STARTED exists but a later reconstruction step failed."""
    reason: str
    """A queries.LookupStatus value (e.g. "malformed"/"ambiguous")."""


# --- Event builders (payload shape owned here, alongside the parsers below) -


def batch_apply_started_event(
    batch_id: UUID,
    requested_policy_decision_ids: Sequence[UUID],
    started_at: datetime,
    managed_root_id: UUID | None,
) -> DomainEvent:
    return DomainEvent(
        event_type=EventType.BATCH_APPLY_STARTED,
        entity_type=EntityType.BATCH,
        entity_id=batch_id,
        timestamp=started_at,
        payload={
            "batch_id": str(batch_id),
            "requested_policy_decision_ids": [
                str(pid) for pid in requested_policy_decision_ids
            ],
            "managed_root_id": (
                str(managed_root_id) if managed_root_id is not None else None
            ),
        },
    )


def batch_item_recorded_event(
    batch_id: UUID,
    item: BatchApplyItemResult,
    recorded_at: datetime,
) -> DomainEvent:
    return DomainEvent(
        event_type=EventType.BATCH_ITEM_RECORDED,
        entity_type=EntityType.BATCH,
        entity_id=batch_id,
        timestamp=recorded_at,
        payload={
            "batch_id": str(batch_id),
            "policy_decision_id": str(item.policy_decision_id),
            "input_index": item.input_index,
            "item_status": item.status.value,
            "reason_code": item.reason_code,
            "transaction_id": (
                str(item.transaction_id) if item.transaction_id is not None else None
            ),
        },
    )


def batch_apply_completed_event(
    batch_id: UUID,
    completed_at: datetime,
    summary: BatchApplySummary,
) -> DomainEvent:
    return DomainEvent(
        event_type=EventType.BATCH_APPLY_COMPLETED,
        entity_type=EntityType.BATCH,
        entity_id=batch_id,
        timestamp=completed_at,
        payload={
            "batch_id": str(batch_id),
            "selected": summary.selected,
            "processed": summary.processed,
            "applied": summary.applied,
            "not_applied": summary.not_applied,
            "skipped": summary.skipped,
            "invalid": summary.invalid,
        },
    )


# --- Payload parsing -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ParsedItemRecord:
    policy_decision_id: UUID
    input_index: int
    item_status: BatchApplyItemStatus
    reason_code: str | None
    transaction_id: UUID | None


@dataclass(frozen=True, slots=True)
class _ParsedSummary:
    selected: int
    processed: int
    applied: int
    not_applied: int
    skipped: int
    invalid: int


def _malformed(batch_id: UUID, exc: Exception) -> queries.LookupFailure:
    return queries.LookupFailure(
        queries.LookupStatus.MALFORMED,
        f"failed to reconstruct batch event payload for {batch_id}: {exc}",
    )


def _parse_requested_ids(event: DomainEvent) -> tuple[UUID, ...]:
    return tuple(
        UUID(str(pid)) for pid in event.payload["requested_policy_decision_ids"]
    )


def _parse_managed_root_id(event: DomainEvent) -> UUID | None:
    """.get, not [], and defaults to None -- a legacy pre-FA-015
    BATCH_APPLY_STARTED payload simply has no "managed_root_id" key at
    all, exactly the same optional-payload-key pattern batch_id/
    policy_decision_id reconstruction already uses elsewhere
    (queries._parse_transaction_result)."""
    raw = event.payload.get("managed_root_id")
    return None if raw is None else UUID(str(raw))


def _parse_item_record(event: DomainEvent) -> _ParsedItemRecord:
    payload = event.payload
    return _ParsedItemRecord(
        policy_decision_id=UUID(str(payload["policy_decision_id"])),
        input_index=int(payload["input_index"]),
        item_status=BatchApplyItemStatus(payload["item_status"]),
        reason_code=payload["reason_code"],
        transaction_id=(
            UUID(str(payload["transaction_id"]))
            if payload["transaction_id"] is not None
            else None
        ),
    )


def _parse_summary(event: DomainEvent) -> _ParsedSummary:
    payload = event.payload
    return _ParsedSummary(
        selected=int(payload["selected"]),
        processed=int(payload["processed"]),
        applied=int(payload["applied"]),
        not_applied=int(payload["not_applied"]),
        skipped=int(payload["skipped"]),
        invalid=int(payload["invalid"]),
    )


def _effective_status_from_transaction(
    result: TransactionResult,
) -> tuple[BatchApplyItemStatus, str | None]:
    """A checkpoint WITH a transaction_id can only ever have gone through
    TransactionEngine -- its effective status is therefore always APPLIED or
    NOT_APPLIED, never SKIPPED/INVALID (those are exclusively produced for
    items that never reach TransactionEngine at all, which never carry a
    transaction_id in the first place)."""
    if result.status is TransactionStatus.SUCCEEDED:
        return BatchApplyItemStatus.APPLIED, None
    if result.status is TransactionStatus.REJECTED:
        reason_code = result.rejection_code.value if result.rejection_code else None
        return BatchApplyItemStatus.NOT_APPLIED, reason_code
    return BatchApplyItemStatus.NOT_APPLIED, result.failure_reason


def _count_statuses(items: Sequence[BatchHistoryItem]) -> dict[str, int]:
    counts = {"applied": 0, "not_applied": 0, "skipped": 0, "invalid": 0}
    for item in items:
        counts[item.status.value] += 1
    return counts


# --- Reconstruction ----------------------------------------------------------


def _reconstruct_batch(
    store: FileAgentStore, batch_id: UUID, *, include_items: bool
) -> BatchHistoryEntry | queries.LookupFailure:
    events = store.list_events(EntityType.BATCH, batch_id)
    if not events:
        return queries.LookupFailure(
            queries.LookupStatus.NOT_FOUND, f"no events for id={batch_id}"
        )

    started_events = [
        e for e in events if e.event_type is EventType.BATCH_APPLY_STARTED
    ]
    completed_events = [
        e for e in events if e.event_type is EventType.BATCH_APPLY_COMPLETED
    ]
    item_events = [e for e in events if e.event_type is EventType.BATCH_ITEM_RECORDED]

    # Step 1: resolve STARTED/COMPLETED existence and ambiguity.
    if len(started_events) > 1:
        return queries.LookupFailure(
            queries.LookupStatus.AMBIGUOUS,
            f"{len(started_events)} BATCH_APPLY_STARTED events for id={batch_id}",
        )
    if not started_events:
        return queries.LookupFailure(
            queries.LookupStatus.MALFORMED,
            f"batch events exist for id={batch_id} without BATCH_APPLY_STARTED",
        )
    if len(completed_events) > 1:
        return queries.LookupFailure(
            queries.LookupStatus.AMBIGUOUS,
            f"{len(completed_events)} BATCH_APPLY_COMPLETED events for id={batch_id}",
        )
    started_event = started_events[0]
    completed_event = completed_events[0] if completed_events else None

    try:
        requested_ids = _parse_requested_ids(started_event)
    except (KeyError, ValueError, TypeError) as exc:
        return _malformed(batch_id, exc)

    try:
        managed_root_id = _parse_managed_root_id(started_event)
    except (ValueError, TypeError) as exc:
        return _malformed(batch_id, exc)

    try:
        records = [_parse_item_record(e) for e in item_events]
    except (KeyError, ValueError, TypeError) as exc:
        return _malformed(batch_id, exc)

    # Step 2 (FA-015): batch-root agreement. managed_root_id is an
    # AGGREGATE CLAIM about the caller-selected set, not a primitive fact
    # like a timestamp -- cross-verify it against every selected id's
    # independently-resolvable lineage rather than trusting the persisted
    # payload value uncritically, the same discipline steps 4/5 below
    # already apply to checkpoint ownership and terminal-summary agreement.
    # Skipped entirely for a legacy pre-FA-015 batch (managed_root_id is
    # None) -- nothing to verify, and a root is never retroactively
    # inferred for one. An id whose own lineage fails to resolve is simply
    # skipped here (orthogonal, handled by steps 3-4) -- this step only
    # ever detects a genuine CONTRADICTION between two independently-known
    # facts, never incompleteness.
    if managed_root_id is not None:
        for requested_id in requested_ids:
            policy_decision = queries.find_policy_decision(store, requested_id)
            if isinstance(policy_decision, queries.LookupFailure):
                continue
            proposal = queries.find_proposal(store, policy_decision.proposal_id)
            if isinstance(proposal, queries.LookupFailure):
                continue
            discovered = store.get_discovered_file(policy_decision.file_id)
            if discovered is None or discovered.managed_root_id is None:
                continue
            if discovered.managed_root_id != managed_root_id:
                return queries.LookupFailure(
                    queries.LookupStatus.MALFORMED,
                    f"BATCH_APPLY_STARTED claims managed_root_id={managed_root_id} "
                    f"for batch={batch_id}, but policy_decision_id={requested_id} "
                    f"resolves to managed_root_id={discovered.managed_root_id}",
                )

    # Step 3: lineage validation against STARTED -- always performed,
    # regardless of COMPLETED/INCOMPLETE status.
    seen_ids: set[UUID] = set()
    seen_indexes: set[int] = set()
    for record in records:
        if record.policy_decision_id in seen_ids:
            return queries.LookupFailure(
                queries.LookupStatus.AMBIGUOUS,
                f"duplicate BATCH_ITEM_RECORDED for "
                f"policy_decision_id={record.policy_decision_id} in batch={batch_id}",
            )
        if record.input_index in seen_indexes:
            return queries.LookupFailure(
                queries.LookupStatus.AMBIGUOUS,
                f"duplicate BATCH_ITEM_RECORDED for "
                f"input_index={record.input_index} in batch={batch_id}",
            )
        seen_ids.add(record.policy_decision_id)
        seen_indexes.add(record.input_index)
        if not (0 <= record.input_index < len(requested_ids)):
            return queries.LookupFailure(
                queries.LookupStatus.MALFORMED,
                f"BATCH_ITEM_RECORDED input_index={record.input_index} out of "
                f"range for batch={batch_id}",
            )
        if requested_ids[record.input_index] != record.policy_decision_id:
            return queries.LookupFailure(
                queries.LookupStatus.MALFORMED,
                f"BATCH_ITEM_RECORDED policy_decision_id/input_index mismatch "
                f"against BATCH_APPLY_STARTED for batch={batch_id}",
            )

    is_completed = completed_event is not None

    # Step 4: status-dependent completeness.
    if is_completed and len(records) != len(requested_ids):
        return queries.LookupFailure(
            queries.LookupStatus.MALFORMED,
            f"COMPLETED batch={batch_id} has {len(records)} item checkpoints "
            f"for {len(requested_ids)} selected ids",
        )

    # Step 5: cross-verification, with ownership validation (round-5
    # correction 1) -- a resolvable transaction_id is not enough; it must
    # genuinely belong to THIS batch and THIS policy_decision_id.
    effective_items: list[BatchHistoryItem] = []
    for record in records:
        status = record.item_status
        reason_code = record.reason_code
        if record.transaction_id is not None:
            tx_lookup = queries.find_transaction_result(store, record.transaction_id)
            if isinstance(tx_lookup, queries.LookupFailure):
                return queries.LookupFailure(
                    queries.LookupStatus.MALFORMED,
                    f"BATCH_ITEM_RECORDED for "
                    f"policy_decision_id={record.policy_decision_id} references "
                    f"transaction_id={record.transaction_id}, which does not "
                    f"resolve: {tx_lookup.detail}",
                )
            if (
                tx_lookup.batch_id != batch_id
                or tx_lookup.policy_decision_id != record.policy_decision_id
            ):
                return queries.LookupFailure(
                    queries.LookupStatus.MALFORMED,
                    f"BATCH_ITEM_RECORDED for "
                    f"policy_decision_id={record.policy_decision_id} references "
                    f"transaction_id={record.transaction_id}, which does not "
                    "genuinely belong to this batch/policy_decision_id",
                )
            status, reason_code = _effective_status_from_transaction(tx_lookup)
        effective_items.append(
            BatchHistoryItem(
                record.policy_decision_id,
                record.input_index,
                status,
                record.transaction_id,
                reason_code,
            )
        )

    counts = _count_statuses(effective_items)

    # Step 6: terminal-summary agreement, COMPLETED batches only.
    if is_completed:
        assert completed_event is not None
        try:
            persisted = _parse_summary(completed_event)
        except (KeyError, ValueError, TypeError) as exc:
            return _malformed(batch_id, exc)
        reconstructed = (
            len(requested_ids),
            len(effective_items),
            counts["applied"],
            counts["not_applied"],
            counts["skipped"],
            counts["invalid"],
        )
        persisted_tuple = (
            persisted.selected,
            persisted.processed,
            persisted.applied,
            persisted.not_applied,
            persisted.skipped,
            persisted.invalid,
        )
        if persisted_tuple != reconstructed:
            return queries.LookupFailure(
                queries.LookupStatus.MALFORMED,
                f"BATCH_APPLY_COMPLETED summary for batch={batch_id} disagrees "
                "with independently reconstructed item outcomes",
            )

    return BatchHistoryEntry(
        batch_id=batch_id,
        started_at=started_event.timestamp,
        completed_at=completed_event.timestamp if completed_event is not None else None,
        status=BatchStatus.COMPLETED if is_completed else BatchStatus.INCOMPLETE,
        requested_policy_decision_ids=requested_ids,
        managed_root_id=managed_root_id,
        selected_count=len(requested_ids),
        applied_count=counts["applied"],
        not_applied_count=counts["not_applied"],
        skipped_count=counts["skipped"],
        invalid_count=counts["invalid"],
        processed_count=len(effective_items),
        items=tuple(effective_items) if include_items else None,
    )


def get_batch_history(
    store: FileAgentStore, batch_id: UUID, *, include_items: bool = False
) -> BatchHistoryEntry | queries.LookupFailure:
    return _reconstruct_batch(store, batch_id, include_items=include_items)


def _resolve_started_at_for_unavailable_row(
    store: FileAgentStore, batch_id: UUID
) -> datetime | None:
    """None specifically when BATCH_APPLY_STARTED itself is ambiguous/
    unresolvable for this batch_id -- never earliest/latest/min/max chosen
    among conflicting candidates."""
    events = store.list_events(EntityType.BATCH, batch_id)
    started_events = [
        e for e in events if e.event_type is EventType.BATCH_APPLY_STARTED
    ]
    if len(started_events) != 1:
        return None
    return started_events[0].timestamp


def _sort_key(
    row: "BatchHistoryEntry | UnavailableBatchHistoryRow",
) -> tuple[int, float, int]:
    """Known started_at sorts newest-first (group 0). Rows with no genuine
    started_at (STARTED itself ambiguous) sort after every timestamped row,
    ordered by batch_id as a stable, deterministic tiebreaker -- never a
    claim about actual recency."""
    if row.started_at is not None:
        return (0, -row.started_at.timestamp(), 0)
    return (1, 0.0, row.batch_id.int)


def list_recent_batch_history(
    store: FileAgentStore, *, limit: int = 20
) -> tuple[BatchHistoryEntry | UnavailableBatchHistoryRow, ...]:
    events = store.list_events_by_type(EventType.BATCH_APPLY_STARTED)
    batch_ids: list[UUID] = []
    seen: set[UUID] = set()
    for event in events:
        if event.entity_id not in seen:
            seen.add(event.entity_id)
            batch_ids.append(event.entity_id)

    rows: list[BatchHistoryEntry | UnavailableBatchHistoryRow] = []
    for batch_id in batch_ids:
        result = _reconstruct_batch(store, batch_id, include_items=False)
        if isinstance(result, queries.LookupFailure):
            started_at = _resolve_started_at_for_unavailable_row(store, batch_id)
            rows.append(
                UnavailableBatchHistoryRow(batch_id, started_at, result.status.value)
            )
        else:
            rows.append(result)

    rows.sort(key=_sort_key)
    return tuple(rows[:limit])
