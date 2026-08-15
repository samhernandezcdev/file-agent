"""Proves the checkpoint boundary the design plan relies on: prepare()
mutates nothing, commit() is the only moment the filesystem changes, and an
orphaned TRANSACTION_REQUESTED with no terminal event is exactly what a
crash between commit() and the terminal persist would leave behind.

FA-008 does not implement crash recovery -- this test documents the gap,
it does not close it.
"""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from file_agent.domain import (
    EntityType,
    EventType,
    ExecutionAuthorization,
    PolicyDecision,
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
from file_agent.transaction_engine import TransactionEngine, transaction_requested_event


@pytest.fixture
def store(tmp_path: Path) -> Iterator[FileAgentStore]:
    config = AppPaths.from_root(tmp_path / "appdata")
    engine, session_factory = create_engine_and_session_factory(config)
    Base.metadata.create_all(engine)
    try:
        yield FileAgentStore(session_factory)
    finally:
        engine.dispose()


def test_prepare_alone_never_mutates_the_filesystem(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    source = make_source_file("report.txt")
    request = make_request(source)
    policy_decision = make_policy_decision(request)
    authorization = ExecutionAuthorization.from_policy_auto(policy_decision)

    engine = TransactionEngine(sandbox_root)
    prepared = engine.prepare(request, authorization)

    assert not isinstance(prepared, TransactionResult)
    assert source.exists()
    assert not request.destination_path.exists()


def test_crash_after_commit_before_terminal_persist_leaves_orphaned_requested(
    store: FileAgentStore,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    """Simulates crash window 2 from the design plan: the caller persists
    TRANSACTION_REQUESTED, commit() actually moves the file, and then --
    simulating a crash -- the terminal event is never persisted. The
    resulting event history (one orphaned REQUESTED, no terminal event) is
    exactly the detectable signature a future reconciler would look for.
    """
    source = make_source_file("report.txt", content=b"hello world")
    request = make_request(source, content=b"hello world")
    policy_decision = make_policy_decision(request)
    authorization = ExecutionAuthorization.from_policy_auto(policy_decision)

    engine = TransactionEngine(sandbox_root)
    prepared = engine.prepare(request, authorization)
    assert not isinstance(prepared, TransactionResult)
    store.record_event(transaction_requested_event(request))

    result = engine.commit(prepared)  # the mutation happens here

    # simulated crash: the caller never reaches
    # store.record_event(transaction_result_event(result))

    assert result.source_path == request.source_path  # commit() did complete
    assert not source.exists()  # the filesystem HAS mutated
    assert request.destination_path.exists()

    events = store.list_events(EntityType.TRANSACTION, request.id)
    assert len(events) == 1
    assert events[0].event_type is EventType.TRANSACTION_REQUESTED
    # audit trail and filesystem now disagree -- exactly the documented,
    # unclosed gap; FA-008 does not reconcile this automatically
