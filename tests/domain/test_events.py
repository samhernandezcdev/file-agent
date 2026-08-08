"""Tests for DomainEvent."""

from datetime import UTC, datetime, timedelta, timezone
from types import MappingProxyType
from uuid import uuid4

import pytest
from pydantic import ValidationError

from file_agent.domain import DomainEvent, EntityType, EventType


def _make(**overrides: object) -> DomainEvent:
    defaults: dict[str, object] = {
        "event_type": EventType.FILE_DISCOVERED,
        "entity_type": EntityType.FILE,
        "entity_id": uuid4(),
    }
    defaults.update(overrides)
    return DomainEvent(**defaults)


@pytest.mark.parametrize("event_type", list(EventType))
def test_valid_construction_for_each_event_type(event_type: EventType) -> None:
    event = _make(event_type=event_type)
    assert event.event_type is event_type


def test_invalid_event_type_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(event_type="not-a-real-event-type")


def test_non_json_serializable_payload_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(payload={"tags": {"a", "b"}})


def test_default_payload_is_empty_dict() -> None:
    assert _make().payload == {}


def test_default_payload_is_not_shared_between_instances() -> None:
    a = _make()
    b = _make()
    assert a.payload is not b.payload


def test_frozen_mutation_raises() -> None:
    event = _make()
    with pytest.raises(ValidationError):
        event.entity_id = uuid4()  # type: ignore[misc]


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(timestamp=datetime.now())  # noqa: DTZ005 -- intentionally naive


def test_aware_non_utc_timestamp_normalized() -> None:
    plus_two = timezone(timedelta(hours=2))
    local = datetime(2026, 1, 1, 12, 0, 0, tzinfo=plus_two)
    event = _make(timestamp=local)
    assert event.timestamp.tzinfo == UTC
    assert event.timestamp.hour == 10


def test_serialization_round_trip_json() -> None:
    event = _make(
        event_type=EventType.PROPOSAL_CREATED,
        entity_type=EntityType.PROPOSAL,
        payload={"confidence": 0.9, "category": "document"},
    )
    restored = DomainEvent.model_validate_json(event.model_dump_json())
    assert restored == event


def test_serialization_round_trip_dict() -> None:
    event = _make(payload={"note": "example"})
    restored = DomainEvent.model_validate(event.model_dump())
    assert restored == event


def test_unknown_field_rejected() -> None:
    with pytest.raises(ValidationError):
        _make(bogus_field="nope")


# --- M1: payload is deep-frozen, not just protected against reassignment ------


def test_payload_is_a_read_only_mapping() -> None:
    event = _make(payload={"key": "value"})
    assert isinstance(event.payload, MappingProxyType)


def test_payload_top_level_item_assignment_impossible() -> None:
    event = _make(payload={"key": "value"})
    with pytest.raises(TypeError):
        event.payload["key"] = "mutated"  # type: ignore[index]


def test_payload_nested_list_is_frozen_as_tuple() -> None:
    event = _make(payload={"tags": ["a", "b"]})
    assert event.payload["tags"] == ("a", "b")
    with pytest.raises(AttributeError):
        event.payload["tags"].append("mutated")  # type: ignore[attr-defined]


def test_payload_nested_dict_is_frozen_as_mapping() -> None:
    event = _make(payload={"details": {"nested": "value"}})
    assert isinstance(event.payload["details"], MappingProxyType)
    with pytest.raises(TypeError):
        event.payload["details"]["nested"] = "mutated"  # type: ignore[index]
