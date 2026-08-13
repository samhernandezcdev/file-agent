"""Proves transaction events compose with the existing FA-004 persistence
API with zero changes to file_agent.persistence."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from file_agent.domain import (
    EntityType,
    EventType,
    PolicyDecision,
    PolicyOutcome,
    TransactionRequest,
    TransactionResult,
)
from file_agent.persistence import (
    AppPaths,
    FileAgentStore,
    create_engine_and_session_factory,
)
from file_agent.persistence.orm import Base
from file_agent.scanner import SandboxRoot
from file_agent.transaction_engine import (
    TransactionEngine,
    transaction_requested_event,
    transaction_result_event,
)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[FileAgentStore]:
    config = AppPaths.from_root(tmp_path / "appdata")
    engine, session_factory = create_engine_and_session_factory(config)
    Base.metadata.create_all(engine)
    try:
        yield FileAgentStore(session_factory)
    finally:
        engine.dispose()


def test_rejected_transaction_persists_one_event_with_full_lineage(
    store: FileAgentStore,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    source = make_source_file("run.bat", content=b"echo hi")
    request = make_request(source, content=b"echo hi")
    policy_decision = make_policy_decision(request, decision=PolicyOutcome.REVIEW)

    engine = TransactionEngine(sandbox_root)
    outcome = engine.prepare(request, policy_decision)
    assert isinstance(outcome, TransactionResult)
    store.record_event(transaction_result_event(outcome))

    events = store.list_events(EntityType.TRANSACTION, request.id)
    assert len(events) == 1
    assert events[0].event_type is EventType.TRANSACTION_REJECTED
    payload = events[0].payload
    assert payload["transaction_id"] == str(request.id)
    assert payload["file_id"] == str(request.file_id)
    assert payload["proposal_id"] == str(request.proposal_id)
    assert payload["policy_decision_id"] == str(request.policy_decision_id)
    assert payload["operation"] == "move"
    assert payload["source_path"] == str(request.source_path)
    assert payload["destination_path"] == str(request.destination_path)
    assert payload["destination_category"] == request.destination_category.value
    assert payload["expected_sha256"] == request.expected_sha256
    assert payload["expected_size"] == request.expected_size
    assert payload["rejection_code"] == "policy_review"
    assert payload["transaction_engine_id"] == "v1"


def test_successful_transaction_persists_requested_then_succeeded(
    store: FileAgentStore,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    source = make_source_file("report.txt", content=b"hello world")
    request = make_request(source, content=b"hello world")
    policy_decision = make_policy_decision(request)

    engine = TransactionEngine(sandbox_root)
    prepared = engine.prepare(request, policy_decision)
    assert not isinstance(prepared, TransactionResult)
    store.record_event(transaction_requested_event(request))
    result = engine.commit(prepared)
    store.record_event(transaction_result_event(result))

    events = store.list_events(EntityType.TRANSACTION, request.id)
    assert len(events) == 2
    assert events[0].event_type is EventType.TRANSACTION_REQUESTED
    assert events[1].event_type is EventType.TRANSACTION_SUCCEEDED

    terminal_payload = events[1].payload
    assert terminal_payload["status"] == "succeeded"
    assert terminal_payload["verified_sha256"] == request.expected_sha256
    assert terminal_payload["started_at"] is not None
    assert terminal_payload["completed_at"] is not None
    assert terminal_payload["rejection_code"] is None
    assert terminal_payload["failure_reason"] is None


def test_repeated_evaluation_of_same_request_appends_history(
    store: FileAgentStore,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    """A second prepare() against a REVIEW policy decision (i.e. never
    reaching commit()) for a DIFFERENT request still appends independently
    -- distinct request ids produce distinct, non-overwriting event
    histories."""
    source_a = make_source_file("a.bat", content=b"a")
    source_b = make_source_file("b.bat", content=b"b")
    request_a = make_request(source_a, content=b"a")
    request_b = make_request(source_b, content=b"b")
    policy_a = make_policy_decision(request_a, decision=PolicyOutcome.REVIEW)
    policy_b = make_policy_decision(request_b, decision=PolicyOutcome.REVIEW)

    engine = TransactionEngine(sandbox_root)
    outcome_a = engine.prepare(request_a, policy_a)
    outcome_b = engine.prepare(request_b, policy_b)
    assert isinstance(outcome_a, TransactionResult)
    assert isinstance(outcome_b, TransactionResult)
    store.record_event(transaction_result_event(outcome_a))
    store.record_event(transaction_result_event(outcome_b))

    assert len(store.list_events(EntityType.TRANSACTION, request_a.id)) == 1
    assert len(store.list_events(EntityType.TRANSACTION, request_b.id)) == 1
