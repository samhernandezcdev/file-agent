"""application/queries.py: typed reconstruction round trips, malformed
payload handling, and duplicate/conflicting-history fail-closed behavior --
plus the new FileAgentStore.list_events_by_type query method."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from file_agent.application import (
    ApplicationOutcomeStatus,
    FileAgentApplicationService,
    queries,
)
from file_agent.application.errors import TerminalPersistenceError
from file_agent.application.queries import LookupFailure, LookupStatus
from file_agent.domain import (
    DestinationCategory,
    DomainEvent,
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


def test_find_proposal_round_trips(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("report.pdf", content=b"pdf content")
    item = service.analyze_managed_root(managed_root_id).items[0]

    proposal = queries.find_proposal(store, item.proposal_id)

    assert not isinstance(proposal, LookupFailure)
    assert proposal.id == item.proposal_id
    assert proposal.sha256 is not None
    assert proposal.expected_size >= 0


def test_find_policy_decision_round_trips(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("report.pdf", content=b"pdf content")
    item = service.analyze_managed_root(managed_root_id).items[0]

    decision = queries.find_policy_decision(store, item.policy_decision_id)

    assert not isinstance(decision, LookupFailure)
    assert decision.id == item.policy_decision_id


def test_find_proposal_not_found(store: FileAgentStore) -> None:
    result = queries.find_proposal(store, uuid4())
    assert isinstance(result, LookupFailure)
    assert result.status is LookupStatus.NOT_FOUND


def test_find_proposal_malformed_payload(store: FileAgentStore) -> None:
    proposal_id = uuid4()
    bad_event = DomainEvent(
        event_type=EventType.PROPOSAL_CREATED,
        entity_type=EntityType.PROPOSAL,
        entity_id=proposal_id,
        payload={"file_id": "not-a-uuid"},  # missing required keys entirely
    )
    store.record_event(bad_event)

    result = queries.find_proposal(store, proposal_id)

    assert isinstance(result, LookupFailure)
    assert result.status is LookupStatus.MALFORMED


def test_find_effective_human_review_none_when_absent(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("app.exe", content=b"exe content")
    item = service.analyze_managed_root(managed_root_id).items[0]

    result = queries.find_effective_human_review(store, item.policy_decision_id)

    assert result is None


def test_find_effective_human_review_ambiguous_on_duplicate_events(
    store: FileAgentStore,
) -> None:
    policy_decision_id = uuid4()
    for outcome in ("approve", "skip"):
        event = DomainEvent(
            event_type=EventType.HUMAN_REVIEW_RECORDED,
            entity_type=EntityType.HUMAN_REVIEW,
            entity_id=uuid4(),
            payload={
                "review_id": str(uuid4()),
                "policy_decision_id": str(policy_decision_id),
                "proposal_id": str(uuid4()),
                "file_id": str(uuid4()),
                "outcome": outcome,
                "destination_category": "documents",
                "policy_engine_id": "policy-v1",
                "proposal_engine_id": "rules-v1",
                "reviewed_at": "2026-01-01T00:00:00+00:00",
                "review_source": "user",
                "note": None,
                "human_review_engine_id": "v1",
            },
        )
        store.record_event(event)

    result = queries.find_effective_human_review(store, policy_decision_id)

    assert isinstance(result, LookupFailure)
    assert result.status is LookupStatus.AMBIGUOUS


def test_find_transaction_result_ambiguous_on_conflicting_terminals(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("report.pdf", content=b"pdf content")
    item = service.analyze_managed_root(managed_root_id).items[0]
    apply_result = service.apply_item(item.policy_decision_id)
    assert apply_result.status is ApplicationOutcomeStatus.SUCCEEDED
    transaction_id = apply_result.transaction_id
    assert transaction_id is not None
    assert apply_result.destination_path is not None

    conflicting = TransactionResult(
        request_id=transaction_id,
        file_id=uuid4(),
        proposal_id=uuid4(),
        policy_decision_id=uuid4(),
        operation=TransactionOperation.MOVE,
        source_path=apply_result.destination_path,
        destination_path=apply_result.destination_path,
        destination_category=DestinationCategory.DOCUMENTS,
        expected_sha256="c" * 64,
        expected_size=1,
        status=TransactionStatus.FAILED,
        failure_reason="synthetic conflict",
        evaluated_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        transaction_engine_id="v1",
    )
    store.record_event(transaction_result_event(conflicting))

    result = queries.find_transaction_result(store, transaction_id)

    assert isinstance(result, LookupFailure)
    assert result.status is LookupStatus.AMBIGUOUS


def test_find_transaction_result_incomplete_on_requested_without_terminal(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    plain_service = FileAgentApplicationService(app_paths, store)
    managed_root_id = plain_service.add_managed_root(sandbox_root.path).id
    make_source_file("report.pdf", content=b"pdf content")
    item = plain_service.analyze_managed_root(managed_root_id).items[0]

    failing_store = FailOnEventType(
        store,
        {
            EventType.TRANSACTION_SUCCEEDED,
            EventType.TRANSACTION_REJECTED,
            EventType.TRANSACTION_FAILED,
        },
    )
    failing_service = FileAgentApplicationService(app_paths, failing_store)  # type: ignore[arg-type]
    with pytest.raises(TerminalPersistenceError) as excinfo:
        failing_service.apply_item(item.policy_decision_id)
    transaction_id = excinfo.value.result.transaction_id
    assert transaction_id is not None

    result = queries.find_transaction_result(store, transaction_id)

    assert isinstance(result, LookupFailure)
    assert result.status is LookupStatus.INCOMPLETE


def test_list_events_by_type_spans_multiple_entities_ordered(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
    store: FileAgentStore,
) -> None:
    make_source_file("a.pdf", content=b"a")
    make_source_file("b.pdf", content=b"b")
    result = service.analyze_managed_root(managed_root_id)
    assert len(result.items) == 2

    events = store.list_events_by_type(EventType.PROPOSAL_CREATED)

    assert len(events) == 2
    timestamps = [e.timestamp for e in events]
    assert timestamps == sorted(timestamps)
