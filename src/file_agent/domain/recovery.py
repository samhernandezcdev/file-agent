"""RecoveryRequest/RecoveryResult -- the domain vocabulary for reversing a
completed MOVE (REVERSE_MOVE) or reconstructing a file from a verified
VaultObject (RESTORE_FROM_VAULT). See file_agent.recovery_engine and
docs/SAFETY.md.

Every fact a recovery request acts on is derived from ONE evidence artifact
(CompletedMoveEvidence / VaultCaptureEvidence) rather than restated as
independent, potentially-divergent fields -- see recovery_engine's module
docstring for the full trust-boundary rationale.
"""

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from file_agent.domain._validators import ensure_absolute_path, normalize_to_utc
from file_agent.domain.transaction import TransactionResult, TransactionStatus
from file_agent.domain.vault import VaultCaptureResult, VaultCaptureStatus


class RecoveryOperation(str, Enum):
    REVERSE_MOVE = "reverse_move"
    RESTORE_FROM_VAULT = "restore_from_vault"


class RecoveryStatus(str, Enum):
    """Terminal outcome of a recovery attempt. No ALREADY_*/idempotent-hit
    status (unlike VaultCaptureStatus) -- a retry after genuine success is
    always and only reported as an ordinary REJECTED outcome via the same
    preconditions that would reject any other conflicting state. Recovery
    operations are not naturally repeatable the way content-addressed
    capture is, so this design does not pretend otherwise.
    """

    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"


class RecoveryRejectionCode(str, Enum):
    """Why a recovery attempt was REJECTED -- structured, not just prose."""

    CURRENT_FILE_MISSING = "current_file_missing"
    CURRENT_FILE_CHANGED = "current_file_changed"
    ORIGINAL_PATH_OCCUPIED = "original_path_occupied"
    ORIGINAL_PATH_OUTSIDE_SANDBOX = "original_path_outside_sandbox"
    ORIGINAL_PATH_UNSAFE_REPARSE_POINT = "original_path_unsafe_reparse_point"
    ORIGINAL_PARENT_MISSING = "original_parent_missing"
    BASENAME_MISMATCH = "basename_mismatch"
    VAULT_OBJECT_NOT_FOUND = "vault_object_not_found"
    VAULT_OBJECT_CORRUPTED = "vault_object_corrupted"
    VAULT_STORAGE_UNSAFE = "vault_storage_unsafe"
    TARGET_PATH_OCCUPIED = "target_path_occupied"
    TARGET_PATH_OUTSIDE_SANDBOX = "target_path_outside_sandbox"
    TARGET_PATH_UNSAFE_REPARSE_POINT = "target_path_unsafe_reparse_point"
    TARGET_PARENT_MISSING = "target_parent_missing"
    RESTORED_BYTES_HASH_MISMATCH = "restored_bytes_hash_mismatch"


class CompletedMoveEvidence(BaseModel):
    """The narrow, trusted subset of a completed, SUCCEEDED MOVE transaction
    that recovery needs to reverse it. Every field REVERSE_MOVE authorizes
    against is derived from this single object -- there is no second,
    independently-settable field on ReverseMoveRequest that could diverge
    from it.

    Directly constructing this model (rather than via from_transaction_result)
    is not, by itself, authorization evidence -- see recovery_engine's module
    docstring for the full trust-boundary contract. Domain models stay
    permissive (constructible for any test scenario); engines enforce.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    original_transaction_id: UUID
    file_id: UUID
    source_path: Path
    destination_path: Path
    verified_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    _validate_source_path = field_validator("source_path")(ensure_absolute_path)
    _validate_destination_path = field_validator("destination_path")(
        ensure_absolute_path
    )

    @classmethod
    def from_transaction_result(
        cls, result: TransactionResult
    ) -> "CompletedMoveEvidence":
        """The sanctioned construction path: derives evidence directly from
        a real TransactionResult, refusing to manufacture evidence for
        anything that wasn't a genuinely SUCCEEDED move. Still does not
        prove `result` itself is a trustworthy, persisted record -- that
        remains the caller's responsibility (see recovery_engine's trust
        boundary docs).
        """
        if result.status is not TransactionStatus.SUCCEEDED:
            raise ValueError(
                "cannot derive move evidence from a non-SUCCEEDED TransactionResult"
            )
        assert result.verified_sha256 is not None, (
            "SUCCEEDED TransactionResult always carries verified_sha256"
        )
        return cls(
            original_transaction_id=result.request_id,
            file_id=result.file_id,
            source_path=result.source_path,
            destination_path=result.destination_path,
            verified_sha256=result.verified_sha256,
        )


class VaultCaptureEvidence(BaseModel):
    """The narrow, trusted subset of a completed, verified Vault capture
    that recovery needs to restore from it. RESTORE_FROM_VAULT's target
    path is always evidence.source_path -- restore can only ever write back
    to the exact original captured location, never an arbitrary caller-
    chosen empty managed path. Restoring to a different location is out of
    scope for v1 (see recovery_engine's non-goals)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file_id: UUID
    source_path: Path
    verified_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    _validate_source_path = field_validator("source_path")(ensure_absolute_path)

    @classmethod
    def from_capture_result(cls, result: VaultCaptureResult) -> "VaultCaptureEvidence":
        if result.status not in (
            VaultCaptureStatus.CAPTURED,
            VaultCaptureStatus.ALREADY_PRESENT,
        ):
            raise ValueError(
                "cannot derive vault evidence from a non-successful VaultCaptureResult"
            )
        assert result.verified_sha256 is not None, (
            "a successful VaultCaptureResult always carries verified_sha256"
        )
        return cls(
            file_id=result.file_id,
            source_path=result.source_path,
            verified_sha256=result.verified_sha256,
        )


class ReverseMoveRequest(BaseModel):
    """A request to reverse one specific, evidenced MOVE. current_path,
    original_path, file_id, and expected_sha256 are never independent
    fields here -- they are read directly off `evidence`
    (evidence.destination_path / evidence.source_path / evidence.file_id /
    evidence.verified_sha256)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    operation: Literal[RecoveryOperation.REVERSE_MOVE] = RecoveryOperation.REVERSE_MOVE
    evidence: CompletedMoveEvidence
    expected_size: int = Field(ge=0)
    expected_created_at: datetime
    expected_modified_at: datetime
    """The caller's freshly-observed belief about the CURRENT state of
    evidence.destination_path (a fresh stat taken immediately before
    constructing this request) -- needed only for FileHasher's synthetic-
    reconstruction reverification. Not authorization-bearing: lying here
    just causes a clean CURRENT_FILE_CHANGED rejection. The one
    authorization-bearing fact, verified_sha256, comes only from
    `evidence`."""
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    _validate_expected_created_at = field_validator("expected_created_at")(
        normalize_to_utc
    )
    _validate_expected_modified_at = field_validator("expected_modified_at")(
        normalize_to_utc
    )
    _validate_requested_at = field_validator("requested_at")(normalize_to_utc)


class RestoreFromVaultRequest(BaseModel):
    """A request to restore one specific, evidenced Vault capture. No
    independent target_path, file_id, or expected_sha256 -- all derive from
    `evidence`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    operation: Literal[RecoveryOperation.RESTORE_FROM_VAULT] = (
        RecoveryOperation.RESTORE_FROM_VAULT
    )
    evidence: VaultCaptureEvidence
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    _validate_requested_at = field_validator("requested_at")(normalize_to_utc)


RecoveryRequest = ReverseMoveRequest | RestoreFromVaultRequest


class RecoveryResult(BaseModel):
    """An immutable, terminal record of one recovery attempt. Keyed by
    `request_id` (no independent id of its own), same rationale as
    TransactionResult/VaultCaptureResult."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: UUID
    operation: RecoveryOperation
    file_id: UUID
    original_transaction_id: UUID | None
    """From evidence.original_transaction_id for REVERSE_MOVE; always None
    for RESTORE_FROM_VAULT (FA-010 captures are not transaction-linked)."""
    source_path: Path | None
    """evidence.destination_path (B) for REVERSE_MOVE; always None for
    RESTORE_FROM_VAULT."""
    destination_path: Path
    """evidence.source_path (A) for REVERSE_MOVE; evidence.source_path
    (== the restore target) for RESTORE_FROM_VAULT."""
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    vault_object_path: str | None = None
    """Relative to vault_root; RESTORE_FROM_VAULT only."""
    status: RecoveryStatus
    rejection_code: RecoveryRejectionCode | None = None
    failure_reason: str | None = Field(default=None, min_length=1)
    verified_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evaluated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    recovery_engine_id: str = Field(min_length=1)

    _validate_source_path = field_validator("source_path")(
        lambda v: v if v is None else ensure_absolute_path(v)
    )
    _validate_destination_path = field_validator("destination_path")(
        ensure_absolute_path
    )
    _validate_evaluated_at = field_validator("evaluated_at")(normalize_to_utc)
    _validate_started_at = field_validator("started_at")(
        lambda v: v if v is None else normalize_to_utc(v)
    )
    _validate_completed_at = field_validator("completed_at")(
        lambda v: v if v is None else normalize_to_utc(v)
    )

    @model_validator(mode="after")
    def _validate_status_invariants(self) -> "RecoveryResult":
        """Enforces exactly the per-status field requirements. REJECTED
        permits optional (not forbidden) timestamps -- RESTORED_BYTES_
        HASH_MISMATCH is discovered only after commit()'s stage-write
        already ran. verified_sha256 stays unconstrained for REJECTED/FAILED
        (matching TransactionResult/VaultCaptureResult's own precedent).
        vault_object_path is required exactly when SUCCEEDED and the
        operation is RESTORE_FROM_VAULT; forbidden otherwise.
        """
        if (
            self.source_path is None
            and self.operation is not RecoveryOperation.RESTORE_FROM_VAULT
        ):
            raise ValueError("source_path is only None for RESTORE_FROM_VAULT")
        if (
            self.source_path is not None
            and self.operation is RecoveryOperation.RESTORE_FROM_VAULT
        ):
            raise ValueError("RESTORE_FROM_VAULT must not have a source_path")

        if self.status is RecoveryStatus.REJECTED:
            if self.rejection_code is None:
                raise ValueError("REJECTED requires rejection_code")
            if self.failure_reason is not None:
                raise ValueError("REJECTED must not have failure_reason")
            if self.vault_object_path is not None:
                raise ValueError("REJECTED must not have vault_object_path")
        elif self.status is RecoveryStatus.FAILED:
            if self.rejection_code is not None:
                raise ValueError("FAILED must not have rejection_code")
            if self.failure_reason is None:
                raise ValueError("FAILED requires failure_reason")
            if self.vault_object_path is not None:
                raise ValueError("FAILED must not have vault_object_path")
            if self.started_at is None or self.completed_at is None:
                raise ValueError("FAILED requires started_at and completed_at")
        elif self.status is RecoveryStatus.SUCCEEDED:
            if self.rejection_code is not None:
                raise ValueError("SUCCEEDED must not have rejection_code")
            if self.failure_reason is not None:
                raise ValueError("SUCCEEDED must not have failure_reason")
            if self.verified_sha256 is None:
                raise ValueError("SUCCEEDED requires verified_sha256")
            if self.verified_sha256 != self.expected_sha256:
                raise ValueError(
                    "SUCCEEDED requires verified_sha256 == expected_sha256"
                )
            if self.started_at is None or self.completed_at is None:
                raise ValueError("SUCCEEDED requires started_at and completed_at")
            if self.operation is RecoveryOperation.RESTORE_FROM_VAULT:
                if self.vault_object_path is None:
                    raise ValueError(
                        "SUCCEEDED RESTORE_FROM_VAULT requires vault_object_path"
                    )
            elif self.vault_object_path is not None:
                raise ValueError(
                    "SUCCEEDED REVERSE_MOVE must not have vault_object_path"
                )

        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.started_at > self.completed_at
        ):
            raise ValueError("started_at must be <= completed_at")
        return self
