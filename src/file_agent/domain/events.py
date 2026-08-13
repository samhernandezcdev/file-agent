"""DomainEvent — a minimal, generic record of something that happened during scanning."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from file_agent.domain._validators import deep_freeze, deep_thaw, normalize_to_utc


class EventType(str, Enum):
    """The kinds of events this domain model can currently represent."""

    FILE_DISCOVERED = "file_discovered"
    FILE_HASHED = "file_hashed"
    FILE_CLASSIFIED = "file_classified"
    PROPOSAL_CREATED = "proposal_created"
    POLICY_EVALUATED = "policy_evaluated"
    TRANSACTION_REQUESTED = "transaction_requested"
    TRANSACTION_SUCCEEDED = "transaction_succeeded"
    TRANSACTION_REJECTED = "transaction_rejected"
    TRANSACTION_FAILED = "transaction_failed"
    HUMAN_REVIEW_RECORDED = "human_review_recorded"


class EntityType(str, Enum):
    """What kind of entity a DomainEvent's ``entity_id`` refers to."""

    FILE = "file"
    PROPOSAL = "proposal"
    POLICY_DECISION = "policy_decision"
    TRANSACTION = "transaction"
    HUMAN_REVIEW = "human_review"
    SCAN = "scan"


class DomainEvent(BaseModel):
    """A single generic domain event.

    Intentionally one flat model rather than a class hierarchy per event
    type — this is not an event-sourcing framework, just an auditable record
    of "something happened, to this entity, with these details."

    ``payload`` is deep-frozen on construction (nested dicts become read-only
    mappings, nested lists become tuples) so that, combined with
    ``frozen=True``, an event is genuinely immutable after creation — not
    just protected against top-level attribute reassignment.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    event_type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    entity_type: EntityType
    entity_id: UUID
    payload: Mapping[str, Any] = Field(default_factory=dict)

    _validate_timestamp = field_validator("timestamp")(normalize_to_utc)

    @field_validator("payload", mode="after")
    @classmethod
    def _freeze_payload(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        plain = dict(value)
        try:
            json.dumps(plain)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"payload must be JSON-serializable: {exc}") from exc
        return deep_freeze(plain)  # type: ignore[no-any-return]

    @field_serializer("payload")
    def _serialize_payload(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return deep_thaw(value)  # type: ignore[no-any-return]
