"""apply_items() -- batch orchestration over the exact same trusted
per-item path apply_item already walks. Batch intent is NOT batch
authorization: every id below is independently reconstructed and
live-verified, in caller order, with best-effort/per-item atomicity."""

from collections.abc import Callable
from pathlib import Path

import pytest

from file_agent.application import (
    BatchApplyItemStatus,
    BatchStatus,
    FileAgentApplicationService,
)
from file_agent.application.dto import BatchApplyItemResult
from file_agent.application.errors import (
    DuplicatePolicyDecisionIdError,
    EmptyBatchSelectionError,
)
from file_agent.domain import EntityType, EventType
from file_agent.persistence import AppPaths, FileAgentStore
from file_agent.persistence.errors import DatabaseUnavailableError
from file_agent.scanner import SandboxRoot

from .conftest import FailOnEventType


def test_batch_happy_path_applies_all_in_order(
    service: FileAgentApplicationService,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("a.pdf", content=b"a")
    make_source_file("b.pdf", content=b"b")
    make_source_file("c.pdf", content=b"c")
    analysis = service.analyze_scan()
    ids = [item.policy_decision_id for item in analysis.items]

    result = service.apply_items(ids)

    assert result.status is BatchStatus.COMPLETED
    assert result.requested_policy_decision_ids == tuple(ids)
    assert [i.policy_decision_id for i in result.items] == ids
    assert [i.input_index for i in result.items] == [0, 1, 2]
    assert all(i.status is BatchApplyItemStatus.APPLIED for i in result.items)
    assert len({i.transaction_id for i in result.items}) == 3
    assert result.summary.selected == 3
    assert result.summary.processed == 3
    assert result.summary.applied == 3
    assert result.summary.not_applied == 0
    assert result.completed_at is not None


def test_batch_partial_success_continues_past_a_rejection(
    service: FileAgentApplicationService,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("a.pdf", content=b"a")
    make_source_file("b.pdf", content=b"b")
    make_source_file("c.pdf", content=b"c")
    analysis = service.analyze_scan()
    ids = [item.policy_decision_id for item in analysis.items]

    # Pre-occupy item[1]'s destination so its own TransactionEngine
    # precondition rejects it live -- proves preview/staleness never
    # substitutes for live verification, and that the batch continues past
    # a normal business rejection to still process item[2].
    conflicting = analysis.items[1]
    dest_dir = sandbox_root.path / "Documents"
    (dest_dir / conflicting.filename).write_bytes(b"already here")

    result = service.apply_items(ids)

    assert result.status is BatchStatus.COMPLETED
    assert result.items[0].status is BatchApplyItemStatus.APPLIED
    assert result.items[1].status is BatchApplyItemStatus.NOT_APPLIED
    assert result.items[2].status is BatchApplyItemStatus.APPLIED
    assert result.summary.applied == 2
    assert result.summary.not_applied == 1
    assert result.summary.processed == 3


def test_batch_review_scenarios_map_correctly(
    service: FileAgentApplicationService,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("approved.exe", content=b"a")
    make_source_file("pending.exe", content=b"b")
    make_source_file("skipped.exe", content=b"c")
    analysis = service.analyze_scan()
    approved, pending, skipped = analysis.items

    service.approve_review(approved.policy_decision_id)
    service.skip_review(skipped.policy_decision_id)

    result = service.apply_items(
        [
            approved.policy_decision_id,
            pending.policy_decision_id,
            skipped.policy_decision_id,
        ]
    )

    assert result.items[0].status is BatchApplyItemStatus.APPLIED
    assert result.items[1].status is BatchApplyItemStatus.NOT_APPLIED
    assert result.items[1].reason_code == "policy_review_without_approval"
    assert result.items[2].status is BatchApplyItemStatus.SKIPPED
    assert result.items[2].reason_code == "review_outcome_is_skip"
    assert result.summary.applied == 1
    assert result.summary.not_applied == 1
    assert result.summary.skipped == 1


def test_batch_rejects_duplicate_ids_before_any_store_interaction(
    service: FileAgentApplicationService,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("a.pdf", content=b"a")
    analysis = service.analyze_scan()
    dup = analysis.items[0].policy_decision_id
    events_before = store.list_events_by_type(EventType.BATCH_APPLY_STARTED)

    with pytest.raises(DuplicatePolicyDecisionIdError) as excinfo:
        service.apply_items([dup, dup])

    assert excinfo.value.duplicate_ids == (dup,)
    assert store.list_events_by_type(EventType.BATCH_APPLY_STARTED) == events_before


def test_batch_rejects_empty_selection_before_any_store_interaction(
    service: FileAgentApplicationService, store: FileAgentStore
) -> None:
    events_before = store.list_events_by_type(EventType.BATCH_APPLY_STARTED)

    with pytest.raises(EmptyBatchSelectionError):
        service.apply_items([])

    assert store.list_events_by_type(EventType.BATCH_APPLY_STARTED) == events_before


def test_started_persist_failure_propagates_unwrapped_zero_mutation(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    source = make_source_file("a.pdf", content=b"a")
    plain_service = FileAgentApplicationService(sandbox_root, app_paths, store)
    analysis = plain_service.analyze_scan()
    ids = [item.policy_decision_id for item in analysis.items]

    failing_store = FailOnEventType(store, {EventType.BATCH_APPLY_STARTED})
    failing_service = FileAgentApplicationService(
        sandbox_root, app_paths, failing_store
    )  # type: ignore[arg-type]

    with pytest.raises(DatabaseUnavailableError):
        failing_service.apply_items(ids)

    assert source.exists()


def test_child_requested_persist_failure_stops_batch_with_no_item_result(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("a.pdf", content=b"a")
    make_source_file("b.pdf", content=b"b")
    plain_service = FileAgentApplicationService(sandbox_root, app_paths, store)
    analysis = plain_service.analyze_scan()
    ids = [item.policy_decision_id for item in analysis.items]

    failing_store = FailOnEventType(store, {EventType.TRANSACTION_REQUESTED})
    failing_service = FileAgentApplicationService(
        sandbox_root, app_paths, failing_store
    )  # type: ignore[arg-type]

    result = failing_service.apply_items(ids)

    assert result.status is BatchStatus.INCOMPLETE
    assert result.completed_at is None
    assert result.items == ()


def test_terminal_persist_failure_reports_real_result_but_no_checkpoint(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    """The round-2 correction: a genuine mutation happened, but its
    authoritative terminal event failed to persist. This call's OWN
    BatchApplyResult still reports the real outcome (runtime knows more than
    durable history) -- but durable history (get_batch_history, separately
    tested) must never claim BATCH_ITEM_RECORDED for this item."""
    source = make_source_file("a.pdf", content=b"a")
    plain_service = FileAgentApplicationService(sandbox_root, app_paths, store)
    analysis = plain_service.analyze_scan()
    ids = [item.policy_decision_id for item in analysis.items]

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

    result = failing_service.apply_items(ids)

    assert result.status is BatchStatus.INCOMPLETE
    assert len(result.items) == 1
    item = result.items[0]
    assert item.status is BatchApplyItemStatus.APPLIED
    assert item.transaction_id is not None
    assert not source.exists()
    # No BATCH_ITEM_RECORDED was persisted for this item, but nothing before
    # it exists to persist either -- the durable check lives in
    # test_batch_history.py's crash-durability test.
    events = store.list_events(EntityType.BATCH, result.batch_id)
    assert not any(e.event_type is EventType.BATCH_ITEM_RECORDED for e in events)


def test_checkpoint_persist_failure_still_returns_in_process_result(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    """Round-3 correction 2: _apply_one's own try/except and the
    BATCH_ITEM_RECORDED checkpoint's try/except are separate -- a checkpoint
    persist failure must not drop the already-known, correct item_result
    from this call's own returned BatchApplyResult."""
    make_source_file("a.pdf", content=b"a")
    plain_service = FileAgentApplicationService(sandbox_root, app_paths, store)
    analysis = plain_service.analyze_scan()
    ids = [item.policy_decision_id for item in analysis.items]

    failing_store = FailOnEventType(store, {EventType.BATCH_ITEM_RECORDED})
    failing_service = FileAgentApplicationService(
        sandbox_root, app_paths, failing_store
    )  # type: ignore[arg-type]

    result = failing_service.apply_items(ids)

    assert result.status is BatchStatus.INCOMPLETE
    assert len(result.items) == 1
    assert result.items[0].status is BatchApplyItemStatus.APPLIED
    assert result.items[0].transaction_id is not None
    events = store.list_events(EntityType.BATCH, result.batch_id)
    assert not any(e.event_type is EventType.BATCH_ITEM_RECORDED for e in events)


def test_completed_persist_failure_still_returns_every_checkpointed_item(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("a.pdf", content=b"a")
    make_source_file("b.pdf", content=b"b")
    plain_service = FileAgentApplicationService(sandbox_root, app_paths, store)
    analysis = plain_service.analyze_scan()
    ids = [item.policy_decision_id for item in analysis.items]

    failing_store = FailOnEventType(store, {EventType.BATCH_APPLY_COMPLETED})
    failing_service = FileAgentApplicationService(
        sandbox_root, app_paths, failing_store
    )  # type: ignore[arg-type]

    result = failing_service.apply_items(ids)

    assert result.status is BatchStatus.INCOMPLETE
    assert result.completed_at is None
    assert len(result.items) == 2
    assert all(i.status is BatchApplyItemStatus.APPLIED for i in result.items)


def test_apply_items_signature_accepts_only_uuid_sequence() -> None:
    import inspect

    sig = inspect.signature(FileAgentApplicationService.apply_items)
    params = [p for name, p in sig.parameters.items() if name != "self"]
    assert len(params) == 1
    assert params[0].name == "policy_decision_ids"


def test_batch_item_result_carries_no_trust_bearing_object() -> None:
    field_types = {f: t for f, t in BatchApplyItemResult.__annotations__.items()}
    forbidden_substrings = (
        "ExecutionAuthorization",
        "TransactionRequest",
        "PolicyDecision",
        "HumanReviewDecision",
        "OrganizationPlan",
    )
    for annotation in field_types.values():
        rendered = str(annotation)
        for forbidden in forbidden_substrings:
            assert forbidden not in rendered
