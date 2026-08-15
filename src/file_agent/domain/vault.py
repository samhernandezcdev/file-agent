"""VaultCaptureRequest/VaultCaptureResult/VaultObject -- the domain vocabulary
for capturing a content-addressed, verified backup of a managed file's bytes
into FileAgent's app-owned Vault. See file_agent.vault_engine and
docs/SAFETY.md.
"""

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from file_agent.domain._validators import ensure_absolute_path, normalize_to_utc


class VaultCaptureStatus(str, Enum):
    """Terminal outcome of a capture attempt.

    REJECTED: a precondition failed, OR the copy/verify step detected a
    problem, before a VaultObject was ever published -- unlike
    TransactionResult, REJECTED here may still carry started_at/completed_at,
    since Vault I/O (a temp write, or a read of an existing object) may
    already have occurred before the rejection was discovered. FAILED: the
    OS itself returned an error during the copy or publish step. CAPTURED: a
    new VaultObject was published. ALREADY_PRESENT: a valid VaultObject for
    this SHA already existed; nothing new was published.
    """

    CAPTURED = "captured"
    ALREADY_PRESENT = "already_present"
    REJECTED = "rejected"
    FAILED = "failed"


class VaultRejectionCode(str, Enum):
    """Why a capture was REJECTED -- structured, not just prose."""

    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_OUTSIDE_SANDBOX = "source_outside_sandbox"
    SOURCE_IDENTITY_CHANGED = "source_identity_changed"
    SOURCE_HASH_MISMATCH = "source_hash_mismatch"
    SOURCE_CHANGED_DURING_CAPTURE = "source_changed_during_capture"
    EXISTING_VAULT_OBJECT_CORRUPTED = "existing_vault_object_corrupted"
    VAULT_STORAGE_UNSAFE = "vault_storage_unsafe"


class VaultCaptureRequest(BaseModel):
    """An explicit request to capture one managed file's bytes into the
    Vault. Constructible for any source/expected-metadata combination --
    sandbox containment, identity reverification, and vault-tree safety are
    engine preconditions (file_agent.vault_engine), not domain validators,
    matching TransactionRequest's own layering.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    file_id: UUID
    source_path: Path
    expected_size: int = Field(ge=0)
    expected_created_at: datetime
    expected_modified_at: datetime
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    """Together with expected_size/expected_created_at/expected_modified_at,
    exactly the fields needed to reconstruct a synthetic DiscoveredFile and
    reverify identity via the existing FileHasher before capture."""
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    _validate_source_path = field_validator("source_path")(ensure_absolute_path)
    _validate_expected_created_at = field_validator("expected_created_at")(
        normalize_to_utc
    )
    _validate_expected_modified_at = field_validator("expected_modified_at")(
        normalize_to_utc
    )
    _validate_requested_at = field_validator("requested_at")(normalize_to_utc)


class VaultCaptureResult(BaseModel):
    """An immutable, terminal record of one capture attempt. Keyed by
    `request_id` (no independent id of its own) -- same rationale as
    TransactionResult: a capture attempt is idempotent-by-request-id, not
    freely repeatable the way pure evaluation is.

    Carries the complete per-attempt provenance (source file/path, expected
    vs. verified identity, timestamps, outcome) -- deliberately NOT baked
    into VaultObject, which is only the physical object's own bare identity.
    See VaultObject's docstring for why that separation matters.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: UUID
    file_id: UUID
    source_path: Path
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_size: int = Field(ge=0)
    status: VaultCaptureStatus
    rejection_code: VaultRejectionCode | None = None
    failure_reason: str | None = Field(default=None, min_length=1)
    verified_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    verified_size: int | None = Field(default=None, ge=0)
    vault_object_path: str | None = None
    """Relative to vault_root, e.g. "objects/ab/ab12...ef" -- the reference
    to the physical VaultObject this capture published or confirmed. Never
    absolute -- an absolute path would leak the current machine's app-data
    root into a durable/portable audit record."""
    evaluated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    vault_engine_id: str = Field(min_length=1)

    _validate_evaluated_at = field_validator("evaluated_at")(normalize_to_utc)
    _validate_started_at = field_validator("started_at")(
        lambda v: v if v is None else normalize_to_utc(v)
    )
    _validate_completed_at = field_validator("completed_at")(
        lambda v: v if v is None else normalize_to_utc(v)
    )

    @model_validator(mode="after")
    def _validate_status_invariants(self) -> "VaultCaptureResult":
        """Enforces exactly the per-status field requirements. Deliberately
        diverges from TransactionResult for REJECTED: TransactionResult
        forbids started_at/completed_at for REJECTED because a rejected
        transaction never risks any I/O. A rejected capture MAY have already
        performed Vault I/O (e.g. EXISTING_VAULT_OBJECT_CORRUPTED is only
        discoverable after reading an existing object, or after the copy
        loop already ran) -- so those two fields are optional, not forbidden,
        for REJECTED here. verified_sha256/verified_size are likewise left
        unconstrained (not forbidden) for REJECTED/FAILED, matching
        TransactionResult's own precedent -- e.g. a SOURCE_CHANGED_DURING_
        CAPTURE rejection or a publish-time FAILED legitimately wants to
        record whatever hash/size was actually observed. vault_object_path
        IS forbidden for both, unconditionally: no VaultObject was ever
        published or confirmed valid on either path.
        """
        if self.status is VaultCaptureStatus.REJECTED:
            if self.rejection_code is None:
                raise ValueError("REJECTED requires rejection_code")
            if self.failure_reason is not None:
                raise ValueError("REJECTED must not have failure_reason")
            if self.vault_object_path is not None:
                raise ValueError("REJECTED must not have vault_object_path")
        elif self.status is VaultCaptureStatus.FAILED:
            if self.rejection_code is not None:
                raise ValueError("FAILED must not have rejection_code")
            if self.failure_reason is None:
                raise ValueError("FAILED requires failure_reason")
            if self.vault_object_path is not None:
                raise ValueError("FAILED must not have vault_object_path")
            if self.started_at is None or self.completed_at is None:
                raise ValueError("FAILED requires started_at and completed_at")
        elif self.status in (
            VaultCaptureStatus.CAPTURED,
            VaultCaptureStatus.ALREADY_PRESENT,
        ):
            if self.rejection_code is not None:
                raise ValueError(f"{self.status} must not have rejection_code")
            if self.failure_reason is not None:
                raise ValueError(f"{self.status} must not have failure_reason")
            if self.verified_sha256 is None or self.verified_size is None:
                raise ValueError(
                    f"{self.status} requires verified_sha256/verified_size"
                )
            if self.verified_sha256 != self.expected_sha256:
                raise ValueError(
                    f"{self.status} requires verified_sha256 == expected_sha256"
                )
            if self.vault_object_path is None:
                raise ValueError(f"{self.status} requires vault_object_path")
            if self.started_at is None or self.completed_at is None:
                raise ValueError(f"{self.status} requires started_at and completed_at")

        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.started_at > self.completed_at
        ):
            raise ValueError("started_at must be <= completed_at")
        return self


class VaultObject(BaseModel):
    """The PHYSICAL Vault object's own identity -- deliberately carries no
    provenance about any particular capture. Content-addressing means the
    same VaultObject may legitimately be the target of captures from
    multiple different source files/paths/times (e.g. two unrelated files
    that happen to have identical bytes) -- baking source-file/path/time
    provenance into VaultObject would falsely imply a 1:1 relationship
    between an object and "the" capture that produced it, when in fact many
    captures may reference one object. That per-capture provenance belongs
    entirely to VaultCaptureResult/its recorded event, never to the object
    itself. This separation (physical object identity vs. capture/recovery
    provenance) is deliberately preserved for a future Restore/Undo ticket,
    which will need to look up "the object for this SHA" independent of
    which capture(s) ever referenced it.

    Not returned by VaultEngine.capture() (VaultCaptureResult already
    carries verified_sha256/verified_size/vault_object_path) and not backed
    by any persistence table -- reconstructable from a VAULT_CAPTURE_SUCCEEDED
    event's payload by a future consumer. No reconstruction helper or query
    is implemented yet; only the model shape.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    vault_relative_path: str
    vault_engine_id: str = Field(min_length=1)
