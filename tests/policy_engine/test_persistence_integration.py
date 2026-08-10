"""Proves policy evaluation composes with the existing FA-004 persistence
API with zero changes to file_agent.persistence."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from file_agent.domain import (
    DestinationCategory,
    EntityType,
    EventType,
    FileCategory,
    FileProposal,
)
from file_agent.persistence import (
    AppPaths,
    FileAgentStore,
    create_engine_and_session_factory,
)
from file_agent.persistence.orm import Base
from file_agent.policy_engine import evaluate_for, policy_decision_event


@pytest.fixture
def store(tmp_path: Path) -> Iterator[FileAgentStore]:
    config = AppPaths.from_root(tmp_path / "appdata")
    engine, session_factory = create_engine_and_session_factory(config)
    Base.metadata.create_all(engine)
    try:
        yield FileAgentStore(session_factory)
    finally:
        engine.dispose()


def test_policy_decision_event_round_trips_through_record_event(
    store: FileAgentStore, make_proposal: Callable[..., FileProposal]
) -> None:
    proposal = make_proposal()
    decision = evaluate_for(proposal)
    event = policy_decision_event(decision)

    inserted = store.record_event(event)

    assert inserted is True
    events = store.list_events(EntityType.POLICY_DECISION, decision.id)
    assert events == (event,)
    assert events[0].event_type is EventType.POLICY_EVALUATED


def test_persisted_event_payload_includes_structured_provenance(
    store: FileAgentStore, make_proposal: Callable[..., FileProposal]
) -> None:
    proposal = make_proposal()
    decision = evaluate_for(proposal)
    event = policy_decision_event(decision)
    store.record_event(event)

    fetched = store.list_events(EntityType.POLICY_DECISION, decision.id)[0]
    assert fetched.payload["proposal_id"] == str(decision.proposal_id)
    assert fetched.payload["file_id"] == str(decision.file_id)
    assert fetched.payload["decision"] == decision.decision.value
    assert fetched.payload["source_category"] == decision.source_category.value
    assert (
        fetched.payload["destination_category"] == decision.destination_category.value  # type: ignore[union-attr]
    )
    assert fetched.payload["proposal_confidence"] == decision.proposal_confidence
    assert fetched.payload["proposal_engine_id"] == decision.proposal_engine_id
    assert fetched.payload["policy_engine_id"] == decision.policy_engine_id
    assert tuple(fetched.payload["reasons"]) == decision.reasons


def test_review_decision_round_trips_through_persistence(
    store: FileAgentStore, make_proposal: Callable[..., FileProposal]
) -> None:
    """FA-007.1 (review m2): every other persistence test uses the default
    AUTO-producing proposal -- this proves a REVIEW decision (EXECUTABLE
    override) also round-trips correctly, including its None
    destination_category."""
    proposal = make_proposal(
        category=FileCategory.EXECUTABLE,
        proposed_destination_category=DestinationCategory.EXECUTABLES,
        confidence=1.0,
        source_classification_confidence=1.0,
    )
    decision = evaluate_for(proposal)
    assert decision.decision.value == "review"

    store.record_event(policy_decision_event(decision))

    fetched = store.list_events(EntityType.POLICY_DECISION, decision.id)[0]
    assert fetched.payload["decision"] == "review"
    assert fetched.payload["proposal_id"] == str(decision.proposal_id)
    assert fetched.payload["file_id"] == str(decision.file_id)
    assert fetched.payload["source_category"] == decision.source_category.value
    assert (
        fetched.payload["destination_category"] == decision.destination_category.value  # type: ignore[union-attr]
    )
    assert fetched.payload["proposal_confidence"] == decision.proposal_confidence
    assert fetched.payload["proposal_engine_id"] == decision.proposal_engine_id
    assert fetched.payload["policy_engine_id"] == decision.policy_engine_id
    assert tuple(fetched.payload["reasons"]) == decision.reasons


def test_repeated_evaluations_append_history_not_overwrite(
    store: FileAgentStore, make_proposal: Callable[..., FileProposal]
) -> None:
    proposal = make_proposal()

    first_decision = evaluate_for(proposal)
    store.record_event(policy_decision_event(first_decision))

    # simulate a later re-evaluation (e.g. after a policy-rule update) -- a
    # fresh decision id makes this a genuinely new historical fact
    second_decision = evaluate_for(proposal)
    store.record_event(policy_decision_event(second_decision))

    assert first_decision.id != second_decision.id
    first_events = store.list_events(EntityType.POLICY_DECISION, first_decision.id)
    second_events = store.list_events(EntityType.POLICY_DECISION, second_decision.id)
    assert len(first_events) == 1
    assert len(second_events) == 1
