"""TransactionRequest/TransactionResult — the sole domain vocabulary for a
managed-file MOVE. See file_agent.transaction_engine and docs/SAFETY.md."""

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from file_agent.domain._validators import ensure_absolute_path, normalize_to_utc
from file_agent.domain.proposal import DestinationCategory


class TransactionOperation(str, Enum):
    """The kind of managed-file mutation a transaction performs.

    A single-member enum, not a bare constant, so a future operation can be
    added without changing every signature that carries this type. No
    DELETE/COPY/RENAME/QUARANTINE/RESTORE -- not even stubbed.
    """

    MOVE = "move"


class TransactionStatus(str, Enum):
    """Terminal outcome of a transaction attempt.

    REJECTED: a precondition failed before any OS mutation call was issued
    -- zero filesystem risk, purely a decision not to act. FAILED: every
    precondition passed, the OS mutation call was actually issued, and the
    OS returned an error -- residual environmental risk, not explained by
    our own logic. SUCCEEDED: the mutation call returned successfully.
    """

    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"


class RejectionCode(str, Enum):
    """Why a transaction was REJECTED -- structured, not just prose."""

    AUTHORIZATION_LINKAGE_MISMATCH = "authorization_linkage_mismatch"
    DESTINATION_CATEGORY_MISMATCH = "destination_category_mismatch"
    DESTINATION_CATEGORY_PATH_MISMATCH = "destination_category_path_mismatch"
    SOURCE_EQUALS_DESTINATION = "source_equals_destination"
    BASENAME_MISMATCH = "basename_mismatch"
    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_IDENTITY_CHANGED = "source_identity_changed"
    SOURCE_HASH_MISMATCH = "source_hash_mismatch"
    DESTINATION_OUTSIDE_SANDBOX = "destination_outside_sandbox"
    DESTINATION_ALREADY_EXISTS = "destination_already_exists"
    DESTINATION_PARENT_MISSING = "destination_parent_missing"
    DESTINATION_UNSAFE_REPARSE_POINT = "destination_unsafe_reparse_point"


class TransactionRequest(BaseModel):
    """An explicit request to move one managed file from one sandbox path to
    another. Constructible for any source/destination pair -- sandbox
    containment, collision, basename, and identity rules are engine
    preconditions (file_agent.transaction_engine), not domain validators, so
    tests can build a request for any rejection scenario without fighting a
    domain-level exception.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    file_id: UUID
    proposal_id: UUID
    policy_decision_id: UUID
    operation: TransactionOperation = TransactionOperation.MOVE
    source_path: Path
    destination_path: Path
    destination_category: DestinationCategory
    """The caller's own claim about which logical destination this request
    serves -- checked against PolicyDecision.destination_category and
    against the configured physical directory for that category."""
    expected_size: int = Field(ge=0)
    expected_created_at: datetime
    expected_modified_at: datetime
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    """Together with expected_size/expected_created_at/expected_modified_at,
    exactly the fields needed to reconstruct a synthetic DiscoveredFile and
    reverify identity via the existing FileHasher immediately before move."""
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    _validate_source_path = field_validator("source_path")(ensure_absolute_path)
    _validate_destination_path = field_validator("destination_path")(
        ensure_absolute_path
    )
    _validate_expected_created_at = field_validator("expected_created_at")(
        normalize_to_utc
    )
    _validate_expected_modified_at = field_validator("expected_modified_at")(
        normalize_to_utc
    )
    _validate_requested_at = field_validator("requested_at")(normalize_to_utc)


class TransactionResult(BaseModel):
    """An immutable, terminal record of one transaction attempt. Keyed by
    `request_id` (no independent id of its own) -- transaction attempts are
    idempotent-by-request-id, not freely repeatable the way pure evaluation
    is; see file_agent.transaction_engine for why.

    Cross-field invariants are enforced below so this model can never
    represent an impossible transaction history (e.g. SUCCEEDED without a
    verified_sha256, or REJECTED with a failure_reason).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: UUID
    file_id: UUID
    proposal_id: UUID
    policy_decision_id: UUID
    operation: TransactionOperation
    source_path: Path
    destination_path: Path
    destination_category: DestinationCategory
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_size: int = Field(ge=0)
    status: TransactionStatus
    rejection_code: RejectionCode | None = None
    failure_reason: str | None = Field(default=None, min_length=1)
    verified_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evaluated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    transaction_engine_id: str = Field(min_length=1)

    _validate_evaluated_at = field_validator("evaluated_at")(normalize_to_utc)
    _validate_started_at = field_validator("started_at")(
        lambda v: v if v is None else normalize_to_utc(v)
    )
    _validate_completed_at = field_validator("completed_at")(
        lambda v: v if v is None else normalize_to_utc(v)
    )

    @model_validator(mode="after")
    def _validate_status_invariants(self) -> "TransactionResult":
        """Enforces exactly the per-status field requirements -- no more, no
        less (e.g. verified_sha256 is deliberately left unconstrained for
        REJECTED, since a SOURCE_HASH_MISMATCH rejection legitimately wants
        to record the actually-observed hash)."""
        if self.status is TransactionStatus.REJECTED:
            if self.rejection_code is None:
                raise ValueError("REJECTED requires rejection_code")
            if self.failure_reason is not None:
                raise ValueError("REJECTED must not have failure_reason")
            if self.started_at is not None or self.completed_at is not None:
                raise ValueError("REJECTED must not have started_at/completed_at")
        elif self.status is TransactionStatus.FAILED:
            if self.rejection_code is not None:
                raise ValueError("FAILED must not have rejection_code")
            if self.failure_reason is None:
                raise ValueError("FAILED requires failure_reason")
            if self.started_at is None or self.completed_at is None:
                raise ValueError("FAILED requires started_at and completed_at")
        elif self.status is TransactionStatus.SUCCEEDED:
            if self.rejection_code is not None:
                raise ValueError("SUCCEEDED must not have rejection_code")
            if self.failure_reason is not None:
                raise ValueError("SUCCEEDED must not have failure_reason")
            if self.started_at is None or self.completed_at is None:
                raise ValueError("SUCCEEDED requires started_at and completed_at")
            if self.verified_sha256 is None:
                raise ValueError("SUCCEEDED requires verified_sha256")

        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.started_at > self.completed_at
        ):
            raise ValueError("started_at must be <= completed_at")
        return self
