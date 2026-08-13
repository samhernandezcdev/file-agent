"""Tests for HumanReviewDecision and HumanReviewOutcome/ReviewSource."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from file_agent.domain import (
    DestinationCategory,
    HumanReviewDecision,
    HumanReviewOutcome,
    ReviewSource,
)


def _make(**overrides: object) -> HumanReviewDecision:
    defaults: dict[str, object] = {
        "policy_decision_id": uuid4(),
        "proposal_id": uuid4(),
        "file_id": uuid4(),
        "outcome": HumanReviewOutcome.APPROVE,
        "destination_category": DestinationCategory.DOCUMENTS,
        "policy_engine_id": "policy-v1",
        "proposal_engine_id": "rules-v1",
        "human_review_engine_id": "v1",
    }
    defaults.update(overrides)
    return HumanReviewDecision(**defaults)


def test_valid_construction_preserves_lineage() -> None:
    policy_decision_id = uuid4()
    proposal_id = uuid4()
    file_id = uuid4()

    review = _make(
        policy_decision_id=policy_decision_id, proposal_id=proposal_id, file_id=file_id
    )

    assert review.policy_decision_id == policy_decision_id
    assert review.proposal_id == proposal_id
    assert review.file_id == file_id


def test_destination_category_none_accepted_for_skip() -> None:
    review = _make(outcome=HumanReviewOutcome.SKIP, destination_category=None)
    assert review.destination_category is None


def test_two_instances_get_distinct_ids() -> None:
    first = _make()
    second = _make()
    assert first.id != second.id


def test_frozen_mutation_raises() -> None:
    review = _make()
    with pytest.raises(ValidationError):
        review.outcome = HumanReviewOutcome.SKIP  # type: ignore[misc]


def test_unknown_field_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(bogus_field="nope")


def test_empty_note_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(note="")


def test_note_none_by_default() -> None:
    assert _make().note is None


def test_empty_policy_engine_id_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(policy_engine_id="")


def test_empty_proposal_engine_id_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(proposal_engine_id="")


def test_empty_human_review_engine_id_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(human_review_engine_id="")


def test_invalid_outcome_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(outcome="not-a-real-outcome")


def test_naive_reviewed_at_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(reviewed_at=datetime.now())  # noqa: DTZ005 -- intentionally naive


def test_aware_non_utc_reviewed_at_normalized() -> None:
    plus_two = timezone(timedelta(hours=2))
    local = datetime(2026, 1, 1, 12, 0, 0, tzinfo=plus_two)
    review = _make(reviewed_at=local)
    assert review.reviewed_at.tzinfo == UTC
    assert review.reviewed_at.hour == 10


def test_human_review_outcome_values() -> None:
    assert HumanReviewOutcome.APPROVE.value == "approve"
    assert HumanReviewOutcome.SKIP.value == "skip"


def test_review_source_default_and_value() -> None:
    review = _make()
    assert review.review_source is ReviewSource.USER
    assert ReviewSource.USER.value == "user"


@pytest.mark.parametrize("outcome", list(HumanReviewOutcome))
def test_outcome_serializes_as_its_value(outcome: HumanReviewOutcome) -> None:
    review = _make(outcome=outcome)
    assert review.model_dump()["outcome"] == outcome.value
