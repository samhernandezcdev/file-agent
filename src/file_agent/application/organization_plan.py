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

from collections.abc import Sequence
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
    PROTECTED = "protected"
    """FA-016: find_structural_protection found the source and/or
    prospective destination structurally protected -- a Protected Tree, a
    hard exclusion, or an inconclusive structural inspection. Distinct from
    BLOCKED (a policy-level refusal): PROTECTED is a filesystem
    structural-safety refusal. Human review can never make a PROTECTED item
    READY -- this status is checked before, and takes precedence over,
    REVIEW_REQUIRED presentation."""


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
    STRUCTURALLY_PROTECTED = "structurally_protected"
    """FA-016 -- .value matches ApplicationRejectionReason.STRUCTURALLY_PROTECTED
    exactly, so the shared Spanish rejection_reason_detail lookup works
    uniformly across both enums."""


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


def missing_destination_categories(
    items: Sequence[OrganizationPlanItem],
) -> frozenset[DestinationCategory]:
    """FA-017.2: the single, shared definition of "this category currently
    has a destination_parent_missing conflict". Both PlanAttentionView's
    missing-destination aggregation (desktop_api/views.py::
    _missing_destination_folder_attentions, presentation layer) and
    destination-setup's current-need authorization
    (application/service.py::prepare_destinations) call this ONE function,
    so the two can never independently drift into disagreeing about what
    "missing" means. Deliberately requires BOTH status and reason_code --
    reason_code alone would not distinguish a genuine current conflict from
    any future PlanReasonCode reuse across statuses."""
    return frozenset(
        item.destination_category
        for item in items
        if item.status is PlanStatus.CONFLICT
        and item.reason_code is PlanReasonCode.DESTINATION_PARENT_MISSING
        and item.destination_category is not None
    )


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
    protected: int
    """FA-016: count of items whose status is PlanStatus.PROTECTED --
    aggregates BOTH source-side and destination-side structural rejections,
    and every StructuralProtectionKind/inspection-failure cause uniformly."""
    issues: int


@dataclass(frozen=True, slots=True)
class OrganizationPlan:
    id: UUID
    created_at: datetime
    root_path: Path | None
    """The owning ManagedRoot's resolved path -- display/snapshot
    information only. None only in the edge case where every single input
    id failed lineage resolution (no root to display)."""
    managed_root_id: UUID | None
    """FA-015: the single ManagedRoot every input id's lineage agreed on --
    durable lineage reference, resolved fresh from that lineage, never a
    caller-supplied value. None only in the same all-issues edge case as
    root_path."""
    source_policy_decision_ids: tuple[UUID, ...]
    items: tuple[OrganizationPlanItem, ...]
    issues: tuple[PlanIssue, ...]
    summary: OrganizationPlanSummary
