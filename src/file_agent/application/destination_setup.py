"""FA-017.2 -- Destination Setup Experience. Plain frozen dataclasses
(matching organization_plan.py's own convention), output-only, plus the
DomainEvent builders for this feature's audit trail -- mirrors
application/history.py's own "payload shape owned alongside the event
builders" pattern for BATCH_APPLY_STARTED/BATCH_ITEM_RECORDED/
BATCH_APPLY_COMPLETED.

DESTINATION NEED != DIRECTORY CREATION AUTHORIZATION. A category appearing
in missing_destination_categories() (organization_plan.py) at analysis
time is a fact about a past analysis, not a grant -- see
FileAgentApplicationService.prepare_destinations for where that fact is
re-derived fresh, live, before any mutation.

Audit-authority note: the events built here are a BEST-EFFORT durable
audit trail, not an authoritative reconstruction/history source. A
successful directory creation can outlive a failed ITEM_RESULT/COMPLETED
write (see prepare_destinations's own per-category persistence-failure
handling) -- domain_events for this entity type may therefore be
incomplete even when the real filesystem mutation succeeded. No product
read model consumes these events in FA-017.2; a future one must never
infer a fact these events don't actually prove.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from file_agent.domain import DestinationCategory, DomainEvent, EntityType, EventType


class DestinationPreparationStatus(str, Enum):
    PREPARED = "prepared"
    """This call's own create_directory_no_replace succeeded, just now."""
    ALREADY_AVAILABLE = "already_available"
    """A safe, normal directory was observed already present -- this call
    did NOT create it. Existence != provenance: never conflated with
    PREPARED."""
    NOT_PREPARED = "not_prepared"
    """Blocked -- reason_code explains why."""


class DestinationSetupReasonCode(str, Enum):
    NOT_CURRENTLY_REQUIRED = "not_currently_required"
    """The requested category is a valid DestinationCategory, but the
    fresh, live re-derivation of current organization need did not include
    it -- zero filesystem interaction is performed for this category."""
    FILE_AT_DESTINATION = "file_at_destination"
    UNSAFE_REPARSE_POINT = "unsafe_reparse_point"
    STRUCTURALLY_PROTECTED = "structurally_protected"
    OBSERVATION_FAILED = "observation_failed"
    # Deliberately NOT "already_exists" -- that is ALREADY_AVAILABLE, not a
    # failure.


@dataclass(frozen=True, slots=True)
class DestinationPreparationOutcome:
    destination_category: DestinationCategory
    status: DestinationPreparationStatus
    reason_code: DestinationSetupReasonCode | None
    """Populated iff status is NOT_PREPARED."""


@dataclass(frozen=True, slots=True)
class DestinationSetupResult:
    setup_id: UUID
    managed_root_id: UUID
    outcomes: tuple[DestinationPreparationOutcome, ...]
    """Stable input order -- the original, deduplicated request order, not
    grouped by authorized/unauthorized or by status."""


# --- Event builders (payload shape owned here, alongside the event types) ---


def destination_setup_started_event(
    setup_id: UUID,
    managed_root_id: UUID,
    requested_categories: tuple[DestinationCategory, ...],
    started_at: datetime,
) -> DomainEvent:
    return DomainEvent(
        event_type=EventType.DESTINATION_SETUP_STARTED,
        entity_type=EntityType.DESTINATION_SETUP,
        entity_id=setup_id,
        timestamp=started_at,
        payload={
            "setup_id": str(setup_id),
            "managed_root_id": str(managed_root_id),
            "requested_categories": [c.value for c in requested_categories],
        },
    )


def destination_setup_item_result_event(
    setup_id: UUID,
    outcome: DestinationPreparationOutcome,
    recorded_at: datetime,
) -> DomainEvent:
    return DomainEvent(
        event_type=EventType.DESTINATION_SETUP_ITEM_RESULT,
        entity_type=EntityType.DESTINATION_SETUP,
        entity_id=setup_id,
        timestamp=recorded_at,
        payload={
            "setup_id": str(setup_id),
            "destination_category": outcome.destination_category.value,
            "status": outcome.status.value,
            "reason_code": (
                outcome.reason_code.value if outcome.reason_code is not None else None
            ),
        },
    )


def destination_setup_completed_event(
    setup_id: UUID,
    completed_at: datetime,
) -> DomainEvent:
    return DomainEvent(
        event_type=EventType.DESTINATION_SETUP_COMPLETED,
        entity_type=EntityType.DESTINATION_SETUP,
        entity_id=setup_id,
        timestamp=completed_at,
        payload={"setup_id": str(setup_id)},
    )
