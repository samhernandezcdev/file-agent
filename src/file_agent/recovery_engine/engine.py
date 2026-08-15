"""RecoveryEngine -- reverses a known-successful MOVE (REVERSE_MOVE) or
reconstructs a file from a verified VaultObject (RESTORE_FROM_VAULT). See
file_agent.recovery_engine and the FA-011 design plan.

RecoveryEngine owns recovery semantics, preconditions, evidence validation,
and strategy -- it has ZERO managed-root mutation call sites of its own.
Every write/rename it needs is a bare function call into managed_fs
(move_no_replace / write_new_file), the single, narrow, audited boundary
also used by TransactionEngine.

Two-method shape (prepare()/commit()), mirroring TransactionEngine exactly,
for two reasons: (1) a durable RECOVERY_REQUESTED checkpoint must be
persisted AFTER preconditions pass and BEFORE mutation is attempted -- this
engine has no persistence dependency, so the split gives the CALLER that
seam; (2) both evidence.destination_path->evidence.source_path (REVERSE_MOVE)
and evidence.source_path (RESTORE_FROM_VAULT's target) are purely
caller-supplied paths authorized only by preconditions -- the same shape of
risk _PreparedMove's capability token was built to close for
TransactionEngine's destination_path.

=== Trust boundary contract (read before calling this engine) ===

RecoveryEngine is NOT an authorization boundary against arbitrary untrusted
in-process Python code -- it assumes its caller is trusted application
code, exactly like every other engine in this codebase. External/UI/CLI
payloads must never be deserialized directly into CompletedMoveEvidence/
VaultCaptureEvidence and handed to this engine. A future "FA-012
Application Service" must load genuine persisted TRANSACTION_SUCCEEDED/
VAULT_CAPTURE_SUCCEEDED records and construct evidence internally (via
CompletedMoveEvidence.from_transaction_result / VaultCaptureEvidence.
from_capture_result, fed by real, persisted TransactionResult/
VaultCaptureResult objects it reconstructs itself) before ever calling
prepare(). Deliberately not added: cryptographic signing of evidence, or
private/hidden evidence constructors -- these would emulate a guarantee
this engine cannot actually provide. Full live-state reverification
(FileHasher for REVERSE_MOVE; vault_engine.verify_vault_object for
RESTORE_FROM_VAULT) is the actual safety mechanism; the contract above is
what makes that mechanism sufficient.

Caller orchestration shape:

    outcome = engine.prepare(request)
    if isinstance(outcome, RecoveryResult):          # REJECTED
        store.record_event(recovery_result_event(outcome))
        return outcome
    store.record_event(recovery_requested_event(request))   # checkpoint
    result = engine.commit(outcome)
    store.record_event(recovery_result_event(result))       # terminal
    return result
"""

import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from file_agent.domain import (
    DomainEvent,
    EntityType,
    EventType,
    RecoveryRejectionCode,
    RecoveryRequest,
    RecoveryResult,
    RecoveryStatus,
    RestoreFromVaultRequest,
    ReverseMoveRequest,
)
from file_agent.managed_fs import move_no_replace, write_new_file
from file_agent.persistence import AppPaths
from file_agent.recovery_engine.errors import (
    InvalidPreparedRecoveryError,
    InvalidRecoveryConfigurationError,
)
from file_agent.recovery_engine.preconditions import (
    check_basename_preserved,
    check_original_parent_exists,
    check_original_path_containment,
    check_original_path_not_occupied,
    check_target_containment,
    check_target_not_occupied,
    check_target_parent_exists,
    verify_current_file_identity,
)
from file_agent.recovery_engine.restore_paths import new_restore_temp_path
from file_agent.recovery_engine.rules import RECOVERY_ENGINE_ID
from file_agent.scanner import SandboxRoot
from file_agent.vault_engine import (
    InvalidVaultConfigurationError,
    VaultLookupStatus,
    VerifiedVaultObject,
    ensure_disjoint_roots,
    verify_vault_object,
)

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class _PreparedRecovery:
    """Opaque, one-shot capability -- identical shape to TransactionEngine's
    _PreparedMove: only a private _token: UUID, not exported from
    __init__.py. commit() resolves everything from the engine's own private
    registry, never from anything read off this object."""

    _token: UUID


@dataclass(frozen=True, slots=True)
class _PendingReverseMove:
    request: ReverseMoveRequest
    verified_sha256: str
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class _PendingRestore:
    request: RestoreFromVaultRequest
    verified_object: VerifiedVaultObject
    evaluated_at: datetime


def _read_chunks(path: Path, chunk_size: int = _CHUNK_SIZE) -> Iterator[bytes]:
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_size):
            yield chunk


def _rehash_file(path: Path) -> str:
    """Full rehash of a file's on-disk bytes -- used to verify the
    RESTORE_FROM_VAULT staged temp file AFTER it is closed, proving the
    actual on-disk bytes match, not merely what was handed to write() calls
    in memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _file_id(request: RecoveryRequest) -> UUID:
    return request.evidence.file_id


def _original_transaction_id(request: RecoveryRequest) -> UUID | None:
    if isinstance(request, ReverseMoveRequest):
        return request.evidence.original_transaction_id
    return None


def _source_path(request: RecoveryRequest) -> Path | None:
    if isinstance(request, ReverseMoveRequest):
        return request.evidence.destination_path
    return None


def _destination_path(request: RecoveryRequest) -> Path:
    """evidence.source_path for BOTH operations: A (the reverse-move
    destination) for REVERSE_MOVE, the restore target for
    RESTORE_FROM_VAULT."""
    return request.evidence.source_path


def _expected_sha256(request: RecoveryRequest) -> str:
    return request.evidence.verified_sha256


class RecoveryEngine:
    """Evaluates a RecoveryRequest against fixed, ordered preconditions
    (containment/safety before any existence/stat/open/hash call on a
    caller-supplied path) and, once authorized, performs exactly one
    REVERSE_MOVE or RESTORE_FROM_VAULT via managed_fs's shared primitives.

    Never mutates the filesystem in prepare(). commit() is only reachable
    with a _PreparedRecovery, which only prepare() can produce -- and only
    on the success path, so a rejected preparation can never yield a
    committable capability.
    """

    def __init__(
        self,
        sandbox_root: SandboxRoot,
        app_paths: AppPaths,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        try:
            ensure_disjoint_roots(app_paths, sandbox_root)
        except InvalidVaultConfigurationError as exc:
            raise InvalidRecoveryConfigurationError(str(exc)) from exc
        self._sandbox_root = sandbox_root
        self._app_paths = app_paths
        self._clock = clock
        self._pending: dict[UUID, _PendingReverseMove | _PendingRestore] = {}

    def prepare(self, request: RecoveryRequest) -> "_PreparedRecovery | RecoveryResult":
        evaluated_at = self._clock()
        if isinstance(request, ReverseMoveRequest):
            return self._prepare_reverse_move(request, evaluated_at)
        return self._prepare_restore(request, evaluated_at)

    def _prepare_reverse_move(
        self, request: ReverseMoveRequest, evaluated_at: datetime
    ) -> "_PreparedRecovery | RecoveryResult":
        evidence = request.evidence
        precondition_checks: tuple[Callable[[], RecoveryRejectionCode | None], ...] = (
            lambda: check_basename_preserved(evidence),
            lambda: check_original_path_containment(evidence, self._sandbox_root),
            lambda: check_original_path_not_occupied(evidence),
            lambda: check_original_parent_exists(evidence),
        )
        for check in precondition_checks:
            code = check()
            if code is not None:
                return self._rejected(request, code, evaluated_at)

        identity = verify_current_file_identity(request, self._sandbox_root)
        if isinstance(identity, RecoveryRejectionCode):
            return self._rejected(request, identity, evaluated_at)

        token = uuid4()
        self._pending[token] = _PendingReverseMove(
            request=request, verified_sha256=identity, evaluated_at=evaluated_at
        )
        return _PreparedRecovery(_token=token)

    def _prepare_restore(
        self, request: RestoreFromVaultRequest, evaluated_at: datetime
    ) -> "_PreparedRecovery | RecoveryResult":
        evidence = request.evidence
        precondition_checks: tuple[Callable[[], RecoveryRejectionCode | None], ...] = (
            lambda: check_target_containment(evidence, self._sandbox_root),
            lambda: check_target_not_occupied(evidence),
            lambda: check_target_parent_exists(evidence),
        )
        for check in precondition_checks:
            code = check()
            if code is not None:
                return self._rejected(request, code, evaluated_at)

        lookup = verify_vault_object(self._app_paths, evidence.verified_sha256)
        if isinstance(lookup, VerifiedVaultObject):
            token = uuid4()
            self._pending[token] = _PendingRestore(
                request=request, verified_object=lookup, evaluated_at=evaluated_at
            )
            return _PreparedRecovery(_token=token)
        if lookup.status is VaultLookupStatus.NOT_FOUND:
            return self._rejected(
                request, RecoveryRejectionCode.VAULT_OBJECT_NOT_FOUND, evaluated_at
            )
        if lookup.status is VaultLookupStatus.CORRUPTED:
            return self._rejected(
                request, RecoveryRejectionCode.VAULT_OBJECT_CORRUPTED, evaluated_at
            )
        return self._rejected(
            request, RecoveryRejectionCode.VAULT_STORAGE_UNSAFE, evaluated_at
        )

    def commit(self, prepared: "_PreparedRecovery") -> RecoveryResult:
        entry = self._pending.pop(prepared._token, None)
        if entry is None:
            raise InvalidPreparedRecoveryError(
                "prepared recovery is forged, belongs to a different RecoveryEngine "
                "instance, or was already committed"
            )
        if isinstance(entry, _PendingReverseMove):
            return self._commit_reverse_move(entry)
        return self._commit_restore(entry)

    def _commit_reverse_move(self, entry: _PendingReverseMove) -> RecoveryResult:
        request = entry.request
        started_at = self._clock()
        try:
            move_no_replace(
                request.evidence.destination_path, request.evidence.source_path
            )
        except OSError as exc:
            return self._failed(
                request,
                f"reverse move failed: {exc}",
                entry.evaluated_at,
                started_at,
                self._clock(),
            )
        return self._succeeded(
            request,
            entry.verified_sha256,
            entry.evaluated_at,
            started_at,
            self._clock(),
        )

    def _commit_restore(self, entry: _PendingRestore) -> RecoveryResult:
        """Sequence: exclusive-create temp in target's parent -> close ->
        full rehash from disk -> only then non-overwrite publish. No
        cleanup/unlink on any failure path -- managed_fs has no delete
        primitive, and none is added here. A hash mismatch or a failed
        write/publish leaves the reserved .file_agent_restore.* artifact in
        place; it is inert (never trusted by identity) and, once FA-011.1
        lands, invisible to organization scanning."""
        request = entry.request
        started_at = self._clock()
        temp_path = new_restore_temp_path(request.evidence.source_path)

        try:
            write_new_file(temp_path, _read_chunks(entry.verified_object.abs_path))
        except OSError as exc:
            return self._failed(
                request,
                f"stage write failed: {exc}",
                entry.evaluated_at,
                started_at,
                self._clock(),
            )

        rehashed = _rehash_file(temp_path)
        if rehashed != request.evidence.verified_sha256:
            return self._rejected(
                request,
                RecoveryRejectionCode.RESTORED_BYTES_HASH_MISMATCH,
                entry.evaluated_at,
                started_at=started_at,
                completed_at=self._clock(),
            )

        try:
            move_no_replace(temp_path, request.evidence.source_path)
        except OSError as exc:
            return self._failed(
                request,
                f"publish failed: {exc}",
                entry.evaluated_at,
                started_at,
                self._clock(),
            )

        return self._succeeded(
            request,
            rehashed,
            entry.evaluated_at,
            started_at,
            self._clock(),
            vault_object_path=entry.verified_object.relative_path,
        )

    def _rejected(
        self,
        request: RecoveryRequest,
        code: RecoveryRejectionCode,
        evaluated_at: datetime,
        *,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> RecoveryResult:
        return RecoveryResult(
            request_id=request.id,
            operation=request.operation,
            file_id=_file_id(request),
            original_transaction_id=_original_transaction_id(request),
            source_path=_source_path(request),
            destination_path=_destination_path(request),
            expected_sha256=_expected_sha256(request),
            status=RecoveryStatus.REJECTED,
            rejection_code=code,
            evaluated_at=evaluated_at,
            started_at=started_at,
            completed_at=completed_at,
            recovery_engine_id=RECOVERY_ENGINE_ID,
        )

    def _failed(
        self,
        request: RecoveryRequest,
        failure_reason: str,
        evaluated_at: datetime,
        started_at: datetime,
        completed_at: datetime,
    ) -> RecoveryResult:
        return RecoveryResult(
            request_id=request.id,
            operation=request.operation,
            file_id=_file_id(request),
            original_transaction_id=_original_transaction_id(request),
            source_path=_source_path(request),
            destination_path=_destination_path(request),
            expected_sha256=_expected_sha256(request),
            status=RecoveryStatus.FAILED,
            failure_reason=failure_reason,
            evaluated_at=evaluated_at,
            started_at=started_at,
            completed_at=completed_at,
            recovery_engine_id=RECOVERY_ENGINE_ID,
        )

    def _succeeded(
        self,
        request: RecoveryRequest,
        verified_sha256: str,
        evaluated_at: datetime,
        started_at: datetime,
        completed_at: datetime,
        *,
        vault_object_path: str | None = None,
    ) -> RecoveryResult:
        return RecoveryResult(
            request_id=request.id,
            operation=request.operation,
            file_id=_file_id(request),
            original_transaction_id=_original_transaction_id(request),
            source_path=_source_path(request),
            destination_path=_destination_path(request),
            expected_sha256=_expected_sha256(request),
            vault_object_path=vault_object_path,
            status=RecoveryStatus.SUCCEEDED,
            verified_sha256=verified_sha256,
            evaluated_at=evaluated_at,
            started_at=started_at,
            completed_at=completed_at,
            recovery_engine_id=RECOVERY_ENGINE_ID,
        )


def recovery_requested_event(request: RecoveryRequest) -> DomainEvent:
    """Maps a RecoveryRequest to a RECOVERY_REQUESTED DomainEvent -- the
    durable checkpoint a caller persists AFTER prepare() succeeds and
    BEFORE calling commit(). Does not persist anything itself -- this
    package has no dependency on file_agent.persistence.
    """
    if isinstance(request, ReverseMoveRequest):
        payload: dict[str, object] = {
            "request_id": str(request.id),
            "operation": request.operation.value,
            "original_transaction_id": str(request.evidence.original_transaction_id),
            "file_id": str(request.evidence.file_id),
            "current_path": str(request.evidence.destination_path),
            "original_path": str(request.evidence.source_path),
            "expected_sha256": request.evidence.verified_sha256,
            "expected_size": request.expected_size,
            "expected_created_at": request.expected_created_at.isoformat(),
            "expected_modified_at": request.expected_modified_at.isoformat(),
        }
    else:
        payload = {
            "request_id": str(request.id),
            "operation": request.operation.value,
            "file_id": str(request.evidence.file_id),
            "target_path": str(request.evidence.source_path),
            "expected_sha256": request.evidence.verified_sha256,
        }
    return DomainEvent(
        event_type=EventType.RECOVERY_REQUESTED,
        entity_type=EntityType.RECOVERY,
        entity_id=request.id,
        timestamp=request.requested_at,
        payload=payload,
    )


_RESULT_EVENT_TYPE: dict[RecoveryStatus, EventType] = {
    RecoveryStatus.SUCCEEDED: EventType.RECOVERY_SUCCEEDED,
    RecoveryStatus.REJECTED: EventType.RECOVERY_REJECTED,
    RecoveryStatus.FAILED: EventType.RECOVERY_FAILED,
}


def recovery_result_event(result: RecoveryResult) -> DomainEvent:
    """Maps a RecoveryResult to its terminal DomainEvent (RECOVERY_SUCCEEDED
    / RECOVERY_REJECTED / RECOVERY_FAILED, chosen from result.status). Takes
    ONLY the result -- every field the payload needs already lives on it.
    """
    return DomainEvent(
        event_type=_RESULT_EVENT_TYPE[result.status],
        entity_type=EntityType.RECOVERY,
        entity_id=result.request_id,
        timestamp=result.completed_at
        if result.completed_at is not None
        else result.evaluated_at,
        payload={
            "request_id": str(result.request_id),
            "operation": result.operation.value,
            "file_id": str(result.file_id),
            "original_transaction_id": (
                str(result.original_transaction_id)
                if result.original_transaction_id is not None
                else None
            ),
            "source_path": (
                str(result.source_path) if result.source_path is not None else None
            ),
            "destination_path": str(result.destination_path),
            "expected_sha256": result.expected_sha256,
            "vault_object_path": result.vault_object_path,
            "status": result.status.value,
            "rejection_code": (
                result.rejection_code.value
                if result.rejection_code is not None
                else None
            ),
            "failure_reason": result.failure_reason,
            "verified_sha256": result.verified_sha256,
            "started_at": result.started_at.isoformat()
            if result.started_at is not None
            else None,
            "completed_at": result.completed_at.isoformat()
            if result.completed_at is not None
            else None,
            "recovery_engine_id": result.recovery_engine_id,
        },
    )
