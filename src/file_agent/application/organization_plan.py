"""OrganizationPlan -- FA-013's product-facing preview read model. Plain
frozen dataclasses (matching dto.py's existing convention), output-only,
never parsed from external input.

PREVIEW IS NOT AUTHORIZATION. An OrganizationPlan is an immutable
informational snapshot of proposed organization state, built once, never
updated in place. It never itself authorizes filesystem mutation --
TransactionEngine remains the sole authority for live mutation checks, and
independently re-verifies everything a plan observed before any apply_item
call actually moves a file. See application/planner.py for how a plan is
built, and file_agent.destination for the shared destination-resolution/
inspection logic both this module and TransactionEngine consume.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from uuid import UUID

from file_agent.domain import (
    DestinationCategory,
    FileCategory,
    HumanReviewOutcome,
    PolicyOutcome,
)


class PlanStatus(str, Enum):
    """Readiness dimension -- distinct from PolicyOutcome/HumanReviewOutcome,
    which are preserved on the item unchanged (§5 of the FA-013 design:
    policy_outcome=REVIEW + status=READY can and does coexist).

    READY means "ready according to the state observed when this plan was
    created" -- never "guaranteed to execute successfully later."
    TransactionEngine always revalidates independently.
    """

    READY = "ready"
    REVIEW_REQUIRED = "review_required"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    CONFLICT = "conflict"  # destination-side filesystem readiness problem only
    INVALID = "invalid"  # trusted item identity exists, but a downstream fact (review history) is ambiguous/malformed
    NO_ACTION = "no_action"


class PlanReasonCode(str, Enum):
    """Plan-level reason vocabulary -- not a re-export of every lower-engine
    RejectionCode/RecoveryRejectionCode, matching ApplicationRejectionReason's
    own precedent of a small, UI-appropriate string enum."""

    DESTINATION_OCCUPIED = "destination_occupied"
    DESTINATION_UNSAFE = "destination_unsafe"
    DESTINATION_PARENT_MISSING = "destination_parent_missing"
    FILESYSTEM_STATE_UNCERTAIN = "filesystem_state_uncertain"
    REVIEW_REQUIRED = "review_required"
    HUMAN_SKIPPED = "human_skipped"
    POLICY_BLOCK = "policy_block"
    NO_DESTINATION_PROPOSED = "no_destination_proposed"
    SOURCE_ALREADY_AT_DESTINATION = "source_already_at_destination"
    AMBIGUOUS_REVIEW_HISTORY = "ambiguous_review_history"
    MALFORMED_EVENT_PAYLOAD = "malformed_event_payload"


@dataclass(frozen=True, slots=True)
class OrganizationPlanItem:
    file_id: UUID
    proposal_id: UUID
    policy_decision_id: UUID
    source_path: Path
    filename: str
    category: FileCategory
    destination_category: DestinationCategory | None
    destination_path: Path | None
    policy_outcome: PolicyOutcome
    human_review_outcome: HumanReviewOutcome | None
    status: PlanStatus
    reason_code: PlanReasonCode | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class PlanIssue:
    """An input id whose own PolicyDecision/FileProposal could not be
    reconstructed at all -- there is no reliable identity to hang an item's
    required fields off of. Distinct from OrganizationPlanItem(status=INVALID),
    where the item's own identity IS trustworthy but a downstream fact is
    ambiguous."""

    policy_decision_id: UUID
    reason_code: str
    detail: str


@dataclass(frozen=True, slots=True)
class OrganizationPlanSummary:
    files_total: int
    ready: int
    review_required: int
    conflicts: int
    invalid: int
    blocked: int
    skipped: int
    no_action: int
    issues: int


@dataclass(frozen=True, slots=True)
class OrganizationPlan:
    id: UUID
    created_at: datetime
    root_path: Path
    source_policy_decision_ids: tuple[UUID, ...]
    items: tuple[OrganizationPlanItem, ...]
    issues: tuple[PlanIssue, ...]
    summary: OrganizationPlanSummary
