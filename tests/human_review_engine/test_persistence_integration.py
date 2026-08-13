"""Proves human review events compose with the existing FA-004 persistence
API with zero changes to file_agent.persistence."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from file_agent.domain import (
    EntityType,
    EventType,
    FileProposal,
    HumanReviewOutcome,
    PolicyDecision,
)
from file_agent.human_review_engine import (
    human_review_recorded_event,
    record_human_review,
)
from file_agent.persistence import (
    AppPaths,
    FileAgentStore,
    create_engine_and_session_factory,
)
from file_agent.persistence.orm import Base


@pytest.fixture
def store(tmp_path: Path) -> Iterator[FileAgentStore]:
    config = AppPaths.from_root(tmp_path / "appdata")
    engine, session_factory = create_engine_and_session_factory(config)
    Base.metadata.create_all(engine)
    try:
        yield FileAgentStore(session_factory)
    finally:
        engine.dispose()


def test_review_event_round_trips_through_record_event(
    store: FileAgentStore,
    make_proposal: Callable[..., FileProposal],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    proposal = make_proposal()
    policy_decision = make_policy_decision(proposal)
    review = record_human_review(
        policy_decision, proposal, HumanReviewOutcome.APPROVE, note="looks fine"
    )
    event = human_review_recorded_event(review)

    inserted = store.record_event(event)

    assert inserted is True
    events = store.list_events(EntityType.HUMAN_REVIEW, review.id)
    assert events == (event,)
    assert events[0].event_type is EventType.HUMAN_REVIEW_RECORDED


def test_persisted_payload_includes_full_provenance(
    store: FileAgentStore,
    make_proposal: Callable[..., FileProposal],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    proposal = make_proposal()
    policy_decision = make_policy_decision(proposal)
    review = record_human_review(policy_decision, proposal, HumanReviewOutcome.SKIP)
    store.record_event(human_review_recorded_event(review))

    fetched = store.list_events(EntityType.HUMAN_REVIEW, review.id)[0]
    assert fetched.payload["review_id"] == str(review.id)
    assert fetched.payload["policy_decision_id"] == str(policy_decision.id)
    assert fetched.payload["proposal_id"] == str(proposal.id)
    assert fetched.payload["file_id"] == str(proposal.file_id)
    assert fetched.payload["outcome"] == "skip"
    assert fetched.payload["destination_category"] == review.destination_category.value  # type: ignore[union-attr]
    assert fetched.payload["policy_engine_id"] == policy_decision.policy_engine_id
    assert fetched.payload["proposal_engine_id"] == proposal.proposal_engine_id
    assert fetched.payload["human_review_engine_id"] == review.human_review_engine_id
    assert fetched.payload["review_source"] == "user"
