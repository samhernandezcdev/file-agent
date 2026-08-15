"""Product-facing DTOs -- what a future UI/CLI consumes, never an internal
engine object. Plain frozen dataclasses (matching ClassificationResult's own
precedent), not Pydantic: these are output-only, never parsed from external
input.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from uuid import UUID

from file_agent.domain import DestinationCategory, FileCategory, PolicyOutcome


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
