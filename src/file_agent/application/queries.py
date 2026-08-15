"""Centralized event-payload reconstruction. service.py never touches
event.payload directly -- every `_parse_*` function lives here, and is the
only place a persisted payload dict is turned back into a typed domain
object. This is what "avoid scattering event-payload parsing throughout
application methods" means concretely.

No new persistence tables -- only one small, justified query addition
(FileAgentStore.list_events_by_type), used exactly once below, for exactly
the gap that motivates it: HUMAN_REVIEW_RECORDED events are keyed by the
review's own id, never by policy_decision_id, so "the review(s) for this
PolicyDecision" cannot be found via list_events(entity_type, entity_id)
alone.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import ValidationError

from file_agent.domain import (
    DestinationCategory,
    DomainEvent,
    EntityType,
    EventType,
    FileCategory,
    FileProposal,
    HumanReviewDecision,
    HumanReviewOutcome,
    PolicyDecision,
    PolicyOutcome,
    RecoveryOperation,
    RecoveryRejectionCode,
    RecoveryResult,
    RecoveryStatus,
    RejectionCode,
    ReviewSource,
    TransactionOperation,
    TransactionResult,
    TransactionStatus,
    VaultCaptureResult,
    VaultCaptureStatus,
    VaultRejectionCode,
)
from file_agent.persistence import FileAgentStore


class LookupStatus(str, Enum):
    NOT_FOUND = "not_found"
    MALFORMED = "malformed"
    AMBIGUOUS = "ambiguous"
    INCOMPLETE = "incomplete"
    """Distinct from AMBIGUOUS: a REQUESTED event exists with no terminal
    event yet -- not conflicting history, just not (yet) resolved. Both fail
    closed identically, but callers can tell the difference in reason_code."""


@dataclass(frozen=True, slots=True)
class LookupFailure:
    status: LookupStatus
    detail: str


def _malformed(entity_id: UUID, exc: Exception) -> LookupFailure:
    return LookupFailure(
        LookupStatus.MALFORMED,
        f"failed to reconstruct event payload for {entity_id}: {exc}",
    )


# --- FileProposal ------------------------------------------------------------


def _parse_proposal(event: DomainEvent) -> FileProposal:
    payload = event.payload
    return FileProposal(
        id=event.entity_id,
        file_id=UUID(str(payload["file_id"])),
        proposed_name=payload["proposed_name"],
        proposed_destination=None,
        proposed_destination_category=(
            DestinationCategory(payload["proposed_destination_category"])
            if payload["proposed_destination_category"] is not None
            else None
        ),
        category=FileCategory(payload["category"]),
        confidence=payload["confidence"],
        source_classification_confidence=payload["source_classification_confidence"],
        source_classifier_id=payload["source_classifier_id"],
        reasons=tuple(payload["reasons"]),
        created_at=event.timestamp,
        proposal_engine_id=payload["proposal_engine_id"],
        expected_size=payload["expected_size"],
        expected_created_at=datetime.fromisoformat(str(payload["expected_created_at"])),
        expected_modified_at=datetime.fromisoformat(
            str(payload["expected_modified_at"])
        ),
        sha256=payload["sha256"],
    )


def find_proposal(
    store: FileAgentStore, proposal_id: UUID
) -> FileProposal | LookupFailure:
    events = store.list_events(EntityType.PROPOSAL, proposal_id)
    if not events:
        return LookupFailure(
            LookupStatus.NOT_FOUND, f"no proposal with id={proposal_id}"
        )
    try:
        return _parse_proposal(events[0])
    except (KeyError, ValueError, TypeError, ValidationError) as exc:
        return _malformed(proposal_id, exc)


# --- PolicyDecision ------------------------------------------------------------


def _parse_policy_decision(event: DomainEvent) -> PolicyDecision:
    payload = event.payload
    return PolicyDecision(
        id=event.entity_id,
        proposal_id=UUID(str(payload["proposal_id"])),
        file_id=UUID(str(payload["file_id"])),
        decision=PolicyOutcome(payload["decision"]),
        reasons=tuple(payload["reasons"]),
        evaluated_at=event.timestamp,
        policy_engine_id=payload["policy_engine_id"],
        source_category=FileCategory(payload["source_category"]),
        destination_category=(
            DestinationCategory(payload["destination_category"])
            if payload["destination_category"] is not None
            else None
        ),
        proposal_confidence=payload["proposal_confidence"],
        proposal_engine_id=payload["proposal_engine_id"],
    )


def find_policy_decision(
    store: FileAgentStore, policy_decision_id: UUID
) -> PolicyDecision | LookupFailure:
    events = store.list_events(EntityType.POLICY_DECISION, policy_decision_id)
    if not events:
        return LookupFailure(
            LookupStatus.NOT_FOUND, f"no policy decision with id={policy_decision_id}"
        )
    try:
        return _parse_policy_decision(events[0])
    except (KeyError, ValueError, TypeError, ValidationError) as exc:
        return _malformed(policy_decision_id, exc)


# --- HumanReviewDecision -------------------------------------------------------


def _parse_human_review(event: DomainEvent) -> HumanReviewDecision:
    payload = event.payload
    return HumanReviewDecision(
        id=UUID(str(payload["review_id"])),
        policy_decision_id=UUID(str(payload["policy_decision_id"])),
        proposal_id=UUID(str(payload["proposal_id"])),
        file_id=UUID(str(payload["file_id"])),
        outcome=HumanReviewOutcome(payload["outcome"]),
        destination_category=(
            DestinationCategory(payload["destination_category"])
            if payload["destination_category"] is not None
            else None
        ),
        reviewed_at=event.timestamp,
        review_source=ReviewSource(payload["review_source"]),
        note=payload["note"],
        policy_engine_id=payload["policy_engine_id"],
        proposal_engine_id=payload["proposal_engine_id"],
        human_review_engine_id=payload["human_review_engine_id"],
    )


def find_effective_human_review(
    store: FileAgentStore, policy_decision_id: UUID
) -> HumanReviewDecision | LookupFailure | None:
    """None means "no review yet" -- a valid, common state, not a failure.
    More than one matching event -> AMBIGUOUS, always: this is the direct
    enforcement of "one effective review per PolicyDecision" -- no
    timestamp-wins, no UUID-ordering-as-authority."""
    events = store.list_events_by_type(EventType.HUMAN_REVIEW_RECORDED)
    matching = [
        event
        for event in events
        if event.payload.get("policy_decision_id") == str(policy_decision_id)
    ]
    if not matching:
        return None
    if len(matching) > 1:
        return LookupFailure(
            LookupStatus.AMBIGUOUS,
            f"{len(matching)} HUMAN_REVIEW_RECORDED events found for "
            f"policy_decision_id={policy_decision_id}",
        )
    try:
        return _parse_human_review(matching[0])
    except (KeyError, ValueError, TypeError, ValidationError) as exc:
        return _malformed(policy_decision_id, exc)


# --- TransactionResult / VaultCaptureResult ------------------------------------
# Share one algorithm: both entities follow the identical REQUESTED-then-
# one-terminal shape.


def _parse_transaction_result(event: DomainEvent) -> TransactionResult:
    payload = event.payload
    return TransactionResult(
        request_id=event.entity_id,
        file_id=UUID(str(payload["file_id"])),
        proposal_id=UUID(str(payload["proposal_id"])),
        policy_decision_id=UUID(str(payload["policy_decision_id"])),
        operation=TransactionOperation(payload["operation"]),
        source_path=payload["source_path"],
        destination_path=payload["destination_path"],
        destination_category=DestinationCategory(payload["destination_category"]),
        expected_sha256=payload["expected_sha256"],
        expected_size=payload["expected_size"],
        status=TransactionStatus(payload["status"]),
        rejection_code=(
            RejectionCode(payload["rejection_code"])
            if payload["rejection_code"] is not None
            else None
        ),
        failure_reason=payload["failure_reason"],
        verified_sha256=payload["verified_sha256"],
        evaluated_at=datetime.fromisoformat(str(payload["evaluated_at"])),
        started_at=(
            datetime.fromisoformat(str(payload["started_at"]))
            if payload["started_at"] is not None
            else None
        ),
        completed_at=(
            datetime.fromisoformat(str(payload["completed_at"]))
            if payload["completed_at"] is not None
            else None
        ),
        transaction_engine_id=payload["transaction_engine_id"],
    )


def _parse_capture_result(event: DomainEvent) -> VaultCaptureResult:
    payload = event.payload
    return VaultCaptureResult(
        request_id=event.entity_id,
        file_id=UUID(str(payload["file_id"])),
        source_path=payload["source_path"],
        expected_sha256=payload["expected_sha256"],
        expected_size=payload["expected_size"],
        status=VaultCaptureStatus(payload["status"]),
        rejection_code=(
            VaultRejectionCode(payload["rejection_code"])
            if payload["rejection_code"] is not None
            else None
        ),
        failure_reason=payload["failure_reason"],
        verified_sha256=payload["verified_sha256"],
        verified_size=payload["verified_size"],
        vault_object_path=payload["vault_object_path"],
        evaluated_at=datetime.fromisoformat(str(payload["evaluated_at"])),
        started_at=(
            datetime.fromisoformat(str(payload["started_at"]))
            if payload["started_at"] is not None
            else None
        ),
        completed_at=(
            datetime.fromisoformat(str(payload["completed_at"]))
            if payload["completed_at"] is not None
            else None
        ),
        vault_engine_id=payload["vault_engine_id"],
    )


def _find_requested_and_terminal(
    store: FileAgentStore,
    entity_type: EntityType,
    entity_id: UUID,
    requested_type: EventType,
    terminal_types: frozenset[EventType],
    terminal_types_not_requiring_requested: frozenset[EventType] = frozenset(),
) -> DomainEvent | LookupFailure:
    """Returns the (single) terminal event on success, or a LookupFailure
    covering every ambiguous-history case the design requires: no events at
    all; more than one REQUESTED; a REQUESTED with no terminal yet
    (INCOMPLETE, not AMBIGUOUS); more than one terminal (conflicting);
    or a terminal with no REQUESTED at all.

    That last case is only suspicious for engines whose orchestration
    contract persists REQUESTED unconditionally before ever attempting the
    operation (e.g. VaultEngine). For prepare()/commit()-style engines
    (TransactionEngine, RecoveryEngine), a REJECTED terminal legitimately
    has NO corresponding REQUESTED event -- prepare() rejecting means
    nothing was ever going to mutate, so the caller's orchestration never
    reaches the "persist REQUESTED" step at all. Callers pass the
    REJECTED-shaped terminal type(s) via terminal_types_not_requiring_requested
    to exempt that normal, expected shape from the AMBIGUOUS check.
    """
    events = store.list_events(entity_type, entity_id)
    if not events:
        return LookupFailure(LookupStatus.NOT_FOUND, f"no events for id={entity_id}")

    requested = [e for e in events if e.event_type is requested_type]
    terminal = [e for e in events if e.event_type in terminal_types]

    if len(requested) > 1:
        return LookupFailure(
            LookupStatus.AMBIGUOUS,
            f"{len(requested)} REQUESTED events for id={entity_id}",
        )
    if not terminal:
        return LookupFailure(
            LookupStatus.INCOMPLETE,
            f"REQUESTED without a terminal event for id={entity_id}",
        )
    if len(terminal) > 1:
        return LookupFailure(
            LookupStatus.AMBIGUOUS,
            f"{len(terminal)} conflicting terminal events for id={entity_id}",
        )
    if (
        not requested
        and terminal[0].event_type not in terminal_types_not_requiring_requested
    ):
        return LookupFailure(
            LookupStatus.AMBIGUOUS,
            f"terminal event without a REQUESTED event for id={entity_id}",
        )
    return terminal[0]


_TRANSACTION_TERMINAL_TYPES = frozenset(
    {
        EventType.TRANSACTION_SUCCEEDED,
        EventType.TRANSACTION_REJECTED,
        EventType.TRANSACTION_FAILED,
    }
)
# TransactionEngine.prepare() persists no REQUESTED checkpoint before a
# REJECTED outcome -- that is the normal, expected shape (see
# _find_requested_and_terminal's docstring), not suspicious history.
_TRANSACTION_TERMINAL_NOT_REQUIRING_REQUESTED = frozenset(
    {EventType.TRANSACTION_REJECTED}
)
_CAPTURE_TERMINAL_TYPES = frozenset(
    {EventType.VAULT_CAPTURE_SUCCEEDED, EventType.VAULT_CAPTURE_FAILED}
)


def find_transaction_result(
    store: FileAgentStore, transaction_id: UUID
) -> TransactionResult | LookupFailure:
    outcome = _find_requested_and_terminal(
        store,
        EntityType.TRANSACTION,
        transaction_id,
        EventType.TRANSACTION_REQUESTED,
        _TRANSACTION_TERMINAL_TYPES,
        _TRANSACTION_TERMINAL_NOT_REQUIRING_REQUESTED,
    )
    if isinstance(outcome, LookupFailure):
        return outcome
    try:
        return _parse_transaction_result(outcome)
    except (KeyError, ValueError, TypeError, ValidationError) as exc:
        return _malformed(transaction_id, exc)


def find_capture_result(
    store: FileAgentStore, capture_id: UUID
) -> VaultCaptureResult | LookupFailure:
    outcome = _find_requested_and_terminal(
        store,
        EntityType.VAULT_CAPTURE,
        capture_id,
        EventType.VAULT_CAPTURE_REQUESTED,
        _CAPTURE_TERMINAL_TYPES,
    )
    if isinstance(outcome, LookupFailure):
        return outcome
    try:
        return _parse_capture_result(outcome)
    except (KeyError, ValueError, TypeError, ValidationError) as exc:
        return _malformed(capture_id, exc)


# --- RecoveryResult (not directly queried by service.py today, but kept for
# completeness / future reconciliation use, mirroring the other two) ----------

_RECOVERY_TERMINAL_TYPES = frozenset(
    {
        EventType.RECOVERY_SUCCEEDED,
        EventType.RECOVERY_REJECTED,
        EventType.RECOVERY_FAILED,
    }
)
# RecoveryEngine mirrors TransactionEngine's prepare()/commit() split -- a
# REJECTED outcome from prepare() likewise persists no REQUESTED checkpoint.
_RECOVERY_TERMINAL_NOT_REQUIRING_REQUESTED = frozenset({EventType.RECOVERY_REJECTED})


def _parse_recovery_result(event: DomainEvent) -> RecoveryResult:
    payload = event.payload
    return RecoveryResult(
        request_id=event.entity_id,
        operation=RecoveryOperation(payload["operation"]),
        file_id=UUID(str(payload["file_id"])),
        original_transaction_id=(
            UUID(str(payload["original_transaction_id"]))
            if payload["original_transaction_id"] is not None
            else None
        ),
        source_path=payload["source_path"],
        destination_path=payload["destination_path"],
        expected_sha256=payload["expected_sha256"],
        vault_object_path=payload["vault_object_path"],
        status=RecoveryStatus(payload["status"]),
        rejection_code=(
            RecoveryRejectionCode(payload["rejection_code"])
            if payload["rejection_code"] is not None
            else None
        ),
        failure_reason=payload["failure_reason"],
        verified_sha256=payload["verified_sha256"],
        evaluated_at=datetime.fromisoformat(str(payload["evaluated_at"])),
        started_at=(
            datetime.fromisoformat(str(payload["started_at"]))
            if payload["started_at"] is not None
            else None
        ),
        completed_at=(
            datetime.fromisoformat(str(payload["completed_at"]))
            if payload["completed_at"] is not None
            else None
        ),
        recovery_engine_id=payload["recovery_engine_id"],
    )


def find_recovery_result(
    store: FileAgentStore, recovery_id: UUID
) -> RecoveryResult | LookupFailure:
    outcome = _find_requested_and_terminal(
        store,
        EntityType.RECOVERY,
        recovery_id,
        EventType.RECOVERY_REQUESTED,
        _RECOVERY_TERMINAL_TYPES,
        _RECOVERY_TERMINAL_NOT_REQUIRING_REQUESTED,
    )
    if isinstance(outcome, LookupFailure):
        return outcome
    try:
        return _parse_recovery_result(outcome)
    except (KeyError, ValueError, TypeError, ValidationError) as exc:
        return _malformed(recovery_id, exc)
