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
    VAULT_CAPTURE_REQUESTED = "vault_capture_requested"
    VAULT_CAPTURE_SUCCEEDED = "vault_capture_succeeded"
    VAULT_CAPTURE_FAILED = "vault_capture_failed"
    RECOVERY_REQUESTED = "recovery_requested"
    RECOVERY_SUCCEEDED = "recovery_succeeded"
    RECOVERY_REJECTED = "recovery_rejected"
    RECOVERY_FAILED = "recovery_failed"
    BATCH_APPLY_STARTED = "batch_apply_started"
    BATCH_ITEM_RECORDED = "batch_item_recorded"
    BATCH_APPLY_COMPLETED = "batch_apply_completed"
    PROTECTED_TREE_DETECTED = "protected_tree_detected"
    """FA-016: one event per detected marker-based Protected Tree root, per
    scan (never per file). entity_type=SCAN, entity_id=scan_run.id. Hard
    exclusions never produce this event -- they remain silent, matching the
    pre-existing internal-artifact exclusion's own silent treatment."""
    DESTINATION_SETUP_STARTED = "destination_setup_started"
    """FA-017.2: written before any directory-creation attempt for a
    prepare_destinations call. entity_type=DESTINATION_SETUP,
    entity_id=setup_id."""
    DESTINATION_SETUP_ITEM_RESULT = "destination_setup_item_result"
    """FA-017.2: one per requested-category outcome (prepared/
    already_available/not_prepared, including not_currently_required),
    written immediately after that category's attempt. Same
    entity_type/entity_id as DESTINATION_SETUP_STARTED -- one event type
    for every outcome kind, distinguished by payload, mirroring
    BATCH_ITEM_RECORDED's own shape."""
    DESTINATION_SETUP_COMPLETED = "destination_setup_completed"
    """FA-017.2: a convenience batch-level marker written after every
    requested category has been processed. Best-effort durable audit only
    -- see application/destination_setup.py's module docstring for why
    this stream is never treated as an authoritative reconstruction
    source."""


class EntityType(str, Enum):
    """What kind of entity a DomainEvent's ``entity_id`` refers to."""

    FILE = "file"
    PROPOSAL = "proposal"
    POLICY_DECISION = "policy_decision"
    TRANSACTION = "transaction"
    HUMAN_REVIEW = "human_review"
    SCAN = "scan"
    VAULT_CAPTURE = "vault_capture"
    RECOVERY = "recovery"
    BATCH = "batch"
    DESTINATION_SETUP = "destination_setup"
    """FA-017.2: entity_id is the setup_id of one prepare_destinations
    call."""


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
