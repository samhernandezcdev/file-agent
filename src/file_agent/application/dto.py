"""Product-facing DTOs -- what a future UI/CLI consumes, never an internal
engine object. Plain frozen dataclasses (matching ClassificationResult's own
precedent), not Pydantic: these are output-only, never parsed from external
input.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from uuid import UUID

from file_agent.domain import DestinationCategory, FileCategory, PolicyOutcome
from file_agent.structural_safety import StructuralProtection


class ApplicationOutcomeStatus(str, Enum):
    """One shared vocabulary reused by every result DTO below. Review
    actions only ever produce SUCCEEDED/REJECTED (recording has no
    OS-level failure mode); apply/undo/restore can produce all three."""

    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"


class ApplicationRejectionReason(str, Enum):
    """Application-level-only reasons with no engine equivalent. `reason_code`
    on a result DTO may hold one of these values, or a passed-through
    lower-engine rejection code's own `.value` -- both are plain strings."""

    PROPOSAL_NOT_FOUND = "proposal_not_found"
    POLICY_DECISION_NOT_FOUND = "policy_decision_not_found"
    DISCOVERED_FILE_NOT_FOUND = "discovered_file_not_found"
    TRANSACTION_NOT_FOUND = "transaction_not_found"
    CAPTURE_NOT_FOUND = "capture_not_found"
    AMBIGUOUS_REVIEW_HISTORY = "ambiguous_review_history"
    AMBIGUOUS_TRANSACTION_HISTORY = "ambiguous_transaction_history"
    AMBIGUOUS_CAPTURE_HISTORY = "ambiguous_capture_history"
    REQUESTED_WITHOUT_TERMINAL = "requested_without_terminal"
    MALFORMED_EVENT_PAYLOAD = "malformed_event_payload"
    ORIGINAL_TRANSACTION_NOT_SUCCEEDED = "original_transaction_not_succeeded"
    CAPTURE_NOT_SUCCESSFUL = "capture_not_successful"
    NOT_ELIGIBLE_FOR_REVIEW = "not_eligible_for_review"
    ALREADY_REVIEWED = "already_reviewed"
    POLICY_BLOCK = "policy_block"
    POLICY_REVIEW_WITHOUT_APPROVAL = "policy_review_without_approval"
    REVIEW_OUTCOME_IS_SKIP = "review_outcome_is_skip"
    MANAGED_ROOT_NOT_ACTIVE = "managed_root_not_active"
    """FA-015: the file's owning ManagedRoot is not currently active/live-safe
    -- either removed, or _resolve_safe_managed_root currently fails for it
    (missing/renamed/unsafe, including a since-hijacked ancestor). Used by
    apply_item/apply_items (via _apply_one's per-item re-check) and
    analyze_file."""
    HISTORICAL_ROOT_UNAVAILABLE = "historical_root_unavailable"
    """FA-015: undo_transaction/restore_capture could not resolve a live,
    safe historical root for this file -- no managed_root_id lineage at all
    (legacy pre-FA-015 data), a missing ManagedRootRow, or a currently
    unresolvable/unsafe path. Never distinguished further at this level --
    see _resolve_historical_root."""
    STRUCTURALLY_PROTECTED = "structurally_protected"
    """FA-016: find_structural_protection found the source and/or
    destination structurally protected (a Protected Tree, a hard exclusion,
    or an inconclusive structural inspection -- all three deliberately
    collapse to this single, undifferentiated reason at this level). Used by
    analyze_file, create_organization_plan, and apply_item/apply_items (via
    _apply_one's source and destination live re-checks). Never applied to
    undo_transaction/restore_capture -- structural safety does not gate
    historically-authorized recovery."""


@dataclass(frozen=True, slots=True)
class AnalyzedItem:
    file_id: UUID
    path: Path
    filename: str
    category: FileCategory
    proposed_destination_category: DestinationCategory | None
    proposal_id: UUID
    policy_decision_id: UUID
    policy_outcome: PolicyOutcome
    requires_review: bool
    confidence: float
    reason: str


@dataclass(frozen=True, slots=True)
class AnalysisFailure:
    file_id: UUID
    path: Path | None
    """None only when file_id itself was never discovered/persisted at all
    (analyze_file on an unknown id) -- otherwise the real, known path of the
    file a later pipeline stage (hashing) failed on."""
    reason_code: str


@dataclass(frozen=True, slots=True)
class AnalyzedScanResult:
    scan_id: UUID
    items: tuple[AnalyzedItem, ...]
    failures: tuple[AnalysisFailure, ...]
    files_discovered: int
    protected_trees: tuple[StructuralProtection, ...]
    """FA-016: propagated from ScanResult.protected_trees -- one entry per
    detected marker-based Protected Tree root this scan found and pruned,
    never one entry per excluded file. Hard exclusions are never
    represented here (they remain silent, matching scan-time convention)."""


@dataclass(frozen=True, slots=True)
class ReviewActionResult:
    policy_decision_id: UUID
    status: ApplicationOutcomeStatus
    reason_code: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class ApplyResult:
    policy_decision_id: UUID
    transaction_id: UUID | None
    status: ApplicationOutcomeStatus
    destination_path: Path | None
    reason_code: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class UndoResult:
    transaction_id: UUID
    recovery_id: UUID | None
    status: ApplicationOutcomeStatus
    restored_path: Path | None
    reason_code: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class RestoreResult:
    capture_id: UUID
    recovery_id: UUID | None
    status: ApplicationOutcomeStatus
    restored_path: Path | None
    reason_code: str | None
    reason: str | None


class BatchStatus(str, Enum):
    """Exactly two values -- no FAILED. COMPLETED means BATCH_APPLY_COMPLETED
    was durably found for this batch_id (the batch reached its normal
    completed checkpoint). INCOMPLETE covers every other case uniformly:
    stopped early because an audit-trail persist failed, or a genuine
    process crash mid-batch -- History never needs to (and never claims to)
    distinguish which of those occurred, only that completion was never
    durably confirmed."""

    COMPLETED = "completed"
    INCOMPLETE = "incomplete"


class BatchApplyItemStatus(str, Enum):
    APPLIED = "applied"
    NOT_APPLIED = "not_applied"
    SKIPPED = "skipped"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class BatchApplyItemResult:
    policy_decision_id: UUID
    input_index: int
    """This id's 0-based position in the caller's original sequence -- the
    same durable ordering key BATCH_ITEM_RECORDED persists."""
    proposal_id: UUID | None
    """None only if PolicyDecision/FileProposal itself couldn't be
    reconstructed."""
    file_id: UUID | None
    filename: str | None
    status: BatchApplyItemStatus
    transaction_id: UUID | None
    """Present iff a TransactionEngine result exists for this id."""
    destination_path: Path | None
    reason_code: str | None
    """None iff status is APPLIED."""
    reason: str | None


@dataclass(frozen=True, slots=True)
class BatchApplySummary:
    selected: int
    processed: int
    applied: int
    not_applied: int
    skipped: int
    invalid: int


@dataclass(frozen=True, slots=True)
class BatchApplyResult:
    batch_id: UUID
    status: BatchStatus
    started_at: datetime
    completed_at: datetime | None
    """None iff status is INCOMPLETE."""
    requested_policy_decision_ids: tuple[UUID, ...]
    items: tuple[BatchApplyItemResult, ...]
    summary: BatchApplySummary
    managed_root_id: UUID | None
    """FA-015: the single ManagedRoot every selected id agreed on, resolved
    once at batch-start from lineage (never a caller-supplied value). None
    only if every selected id failed lineage resolution entirely -- an
    aggregate fact about the caller-selected set, persisted explicitly in
    BATCH_APPLY_STARTED's payload since it is not otherwise re-derivable
    without redoing the same Mixed-root check."""
