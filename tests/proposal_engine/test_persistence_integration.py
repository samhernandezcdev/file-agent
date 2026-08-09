"""Proves proposal generation composes with the existing FA-004 persistence
API with zero changes to file_agent.persistence."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from file_agent.classifier import ClassificationResult
from file_agent.domain import DiscoveredFile, EntityType, EventType, FileCategory
from file_agent.persistence import (
    AppPaths,
    FileAgentStore,
    create_engine_and_session_factory,
)
from file_agent.persistence.orm import Base
from file_agent.proposal_engine import proposal_event, propose_for


@pytest.fixture
def store(tmp_path: Path) -> Iterator[FileAgentStore]:
    config = AppPaths.from_root(tmp_path / "appdata")
    engine, session_factory = create_engine_and_session_factory(config)
    Base.metadata.create_all(engine)
    try:
        yield FileAgentStore(session_factory)
    finally:
        engine.dispose()


@pytest.fixture
def make_discovered_file() -> Callable[..., DiscoveredFile]:
    def _make(path: str, **overrides: object) -> DiscoveredFile:
        now = datetime.now(UTC)
        defaults: dict[str, object] = {
            "path": Path(path),
            "size_bytes": 10,
            "created_at": now,
            "modified_at": now,
        }
        defaults.update(overrides)
        return DiscoveredFile(**defaults)

    return _make


def _classification(discovered: DiscoveredFile) -> ClassificationResult:
    return ClassificationResult(
        discovered_file=discovered,
        category=FileCategory.DOCUMENT,
        confidence=1.0,
        reasons=("extension 'pdf' matched category document",),
        classified_at=datetime.now(UTC),
        classifier_id="rules-v1",
    )


def _unknown_classification(discovered: DiscoveredFile) -> ClassificationResult:
    return ClassificationResult(
        discovered_file=discovered,
        category=FileCategory.UNKNOWN,
        confidence=0.0,
        reasons=("no rule matched",),
        classified_at=datetime.now(UTC),
        classifier_id="rules-v1",
    )


def test_proposal_event_round_trips_through_record_event(
    store: FileAgentStore, make_discovered_file: Callable[..., DiscoveredFile]
) -> None:
    discovered = make_discovered_file("C:/sandbox/report.pdf")
    proposal = propose_for(_classification(discovered))
    event = proposal_event(proposal)

    inserted = store.record_event(event)

    assert inserted is True
    events = store.list_events(EntityType.PROPOSAL, proposal.id)
    assert events == (event,)
    assert events[0].event_type is EventType.PROPOSAL_CREATED


def test_persisted_event_payload_includes_structured_provenance(
    store: FileAgentStore, make_discovered_file: Callable[..., DiscoveredFile]
) -> None:
    discovered = make_discovered_file("C:/sandbox/report.pdf")
    proposal = propose_for(_classification(discovered))
    event = proposal_event(proposal)
    store.record_event(event)

    fetched = store.list_events(EntityType.PROPOSAL, proposal.id)[0]
    assert fetched.payload["file_id"] == str(discovered.id)
    assert fetched.payload["category"] == proposal.category.value
    assert (
        fetched.payload["proposed_destination_category"]
        == proposal.proposed_destination_category.value  # type: ignore[union-attr]
    )
    assert (
        fetched.payload["source_classification_confidence"]
        == proposal.source_classification_confidence
    )
    assert fetched.payload["source_classifier_id"] == proposal.source_classifier_id
    assert fetched.payload["proposal_engine_id"] == proposal.proposal_engine_id
    assert tuple(fetched.payload["reasons"]) == proposal.reasons


def test_no_destination_proposal_round_trips_through_persistence(
    store: FileAgentStore, make_discovered_file: Callable[..., DiscoveredFile]
) -> None:
    """FA-006.1 (review m1): every other persistence test uses a mapped
    category, so a None proposed_destination_category was never proven to
    survive record_event()/list_events() -- only asserted correct by
    reading engine.py's conditional serialization."""
    discovered = make_discovered_file("C:/sandbox/whatever.unknownext")
    proposal = propose_for(_unknown_classification(discovered))
    assert proposal.proposed_destination_category is None
    assert proposal.proposed_destination is None
    assert proposal.proposed_name is None
    assert proposal.confidence == 0.0

    store.record_event(proposal_event(proposal))

    fetched = store.list_events(EntityType.PROPOSAL, proposal.id)[0]
    assert fetched.payload["proposed_destination_category"] is None
    assert fetched.payload["proposed_name"] is None
    assert fetched.payload["confidence"] == 0.0


def test_repeated_proposals_append_history_not_overwrite(
    store: FileAgentStore, make_discovered_file: Callable[..., DiscoveredFile]
) -> None:
    discovered = make_discovered_file("C:/sandbox/report.pdf")
    classification = _classification(discovered)

    first_proposal = propose_for(classification)
    store.record_event(proposal_event(first_proposal))

    # simulate a later re-proposal (e.g. after a rule-table update) -- a
    # fresh proposal id makes this a genuinely new historical fact
    second_proposal = propose_for(classification)
    store.record_event(proposal_event(second_proposal))

    assert first_proposal.id != second_proposal.id
    first_events = store.list_events(EntityType.PROPOSAL, first_proposal.id)
    second_events = store.list_events(EntityType.PROPOSAL, second_proposal.id)
    assert len(first_events) == 1
    assert len(second_events) == 1
