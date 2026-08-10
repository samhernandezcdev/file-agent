"""Tests for PolicyDecision and PolicyOutcome."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from file_agent.domain import (
    DestinationCategory,
    FileCategory,
    PolicyDecision,
    PolicyOutcome,
)


def _make(**overrides: object) -> PolicyDecision:
    defaults: dict[str, object] = {
        "proposal_id": uuid4(),
        "file_id": uuid4(),
        "decision": PolicyOutcome.AUTO,
        "reasons": ["destination category documents exists"],
        "policy_engine_id": "rules-v1",
        "source_category": FileCategory.DOCUMENT,
        "destination_category": DestinationCategory.DOCUMENTS,
        "proposal_confidence": 1.0,
        "proposal_engine_id": "rules-v1",
    }
    defaults.update(overrides)
    return PolicyDecision(**defaults)


def test_valid_construction_preserves_provenance() -> None:
    proposal_id = uuid4()
    file_id = uuid4()

    decision = _make(
        proposal_id=proposal_id,
        file_id=file_id,
        source_category=FileCategory.IMAGE,
        destination_category=DestinationCategory.IMAGES,
    )

    assert decision.proposal_id == proposal_id
    assert decision.file_id == file_id
    assert decision.source_category is FileCategory.IMAGE
    assert decision.destination_category is DestinationCategory.IMAGES


def test_destination_category_none_accepted() -> None:
    decision = _make(destination_category=None, decision=PolicyOutcome.REVIEW)
    assert decision.destination_category is None


def test_frozen_mutation_raises() -> None:
    decision = _make()
    with pytest.raises(ValidationError):
        decision.decision = PolicyOutcome.REVIEW  # type: ignore[misc]


def test_unknown_field_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(bogus_field="nope")


def test_empty_reasons_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(reasons=[])


def test_confidence_too_low_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(proposal_confidence=-0.01)


def test_confidence_too_high_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(proposal_confidence=1.01)


@pytest.mark.parametrize("boundary", [0.0, 1.0])
def test_confidence_boundary_accepted(boundary: float) -> None:
    assert _make(proposal_confidence=boundary).proposal_confidence == boundary


def test_empty_policy_engine_id_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(policy_engine_id="")


def test_empty_proposal_engine_id_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(proposal_engine_id="")


def test_invalid_decision_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(decision="not-a-real-decision")


def test_naive_evaluated_at_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(evaluated_at=datetime.now())  # noqa: DTZ005 -- intentionally naive


def test_aware_non_utc_evaluated_at_normalized() -> None:
    plus_two = timezone(timedelta(hours=2))
    local = datetime(2026, 1, 1, 12, 0, 0, tzinfo=plus_two)
    decision = _make(evaluated_at=local)
    assert decision.evaluated_at.tzinfo == UTC
    assert decision.evaluated_at.hour == 10


@pytest.mark.parametrize("outcome", list(PolicyOutcome))
def test_policy_outcome_serializes_as_its_value(outcome: PolicyOutcome) -> None:
    decision = _make(decision=outcome)
    assert decision.model_dump()["decision"] == outcome.value


def test_policy_outcome_values() -> None:
    assert PolicyOutcome.AUTO.value == "auto"
    assert PolicyOutcome.REVIEW.value == "review"
    assert PolicyOutcome.BLOCK.value == "block"
