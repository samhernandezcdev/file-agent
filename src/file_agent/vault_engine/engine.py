"""VaultEngine -- captures a content-addressed, verified backup of a managed
file's bytes into FileAgent's app-owned Vault. See file_agent.vault_engine
and the FA-010 design plan.

Single-call capture() (no prepare()/commit() split, unlike TransactionEngine):
capture is naturally, fully idempotent and safely re-driveable from scratch
at any point, so there is no operationally-ambiguous "was it attempted or
not" state a checkpoint seam would need to resolve, and the publish target is
derived entirely from the verified SHA-256 rather than any caller-supplied
claim, so there is no forgery-style threat a capability token would need to
defend against.
"""

import hashlib
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from file_agent.domain import (
    DiscoveredFile,
    DomainEvent,
    EntityType,
    EventType,
    VaultCaptureRequest,
    VaultCaptureResult,
    VaultCaptureStatus,
    VaultRejectionCode,
)
from file_agent.hasher import FileHasher, HashFailure, HashIssueType
from file_agent.persistence import AppPaths
from file_agent.scanner import SandboxRoot
from file_agent.vault_engine.paths import (
    new_temp_path,
    object_abs_path,
    object_prefix_dir,
    object_relative_path,
)
from file_agent.vault_engine.rules import VAULT_ENGINE_ID
from file_agent.vault_engine.safety import (
    find_unsafe_vault_reparse_point,
    is_unsafe_reparse_point,
)
from file_agent.vault_engine.storage import ensure_vault_layout

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _SourceChangedDuringCapture(Exception):
    """Internal control-flow signal only -- never escapes capture()."""


def _rehash_vault_object(path: Path) -> str:
    """Independently rehashes an EXISTING Vault object's own bytes. Not via
    FileHasher -- FileHasher is scoped to a SandboxRoot and would reject a
    vault path as outside the sandbox by design; this is a small, separate,
    read-only helper over a vault-owned path."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _best_effort_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass  # cleanup is opportunistic, never load-bearing for correctness


class VaultEngine:
    """Evaluates a VaultCaptureRequest and, once source identity and Vault-
    tree safety are both reverified, publishes a content-addressed Vault
    object -- or confirms one already exists. Never mutates, renames, or
    deletes the managed source file.
    """

    def __init__(
        self,
        sandbox_root: SandboxRoot,
        app_paths: AppPaths,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        ensure_vault_layout(app_paths, sandbox_root)
        self._sandbox_root = sandbox_root
        self._app_paths = app_paths
        self._clock = clock

    def capture(self, request: VaultCaptureRequest) -> VaultCaptureResult:
        """Never raises for well-formed input -- every problem becomes a
        VaultCaptureResult, mirroring FileHasher.hash_file's contract."""
        try:
            return self._capture(request)
        except Exception as exc:  # noqa: BLE001 -- defensive: capture() must never raise
            return self._failed(
                request,
                f"internal error: {exc}",
                self._clock(),
                started_at=None,
                completed_at=self._clock(),
            )

    def _capture(self, request: VaultCaptureRequest) -> VaultCaptureResult:
        evaluated_at = self._clock()

        # Steps 1+2: source containment + identity reverification, reusing
        # the existing FileHasher exactly as
        # transaction_engine/preconditions.py::verify_source_identity does.
        synthetic = DiscoveredFile(
            path=request.source_path,
            size_bytes=request.expected_size,
            created_at=request.expected_created_at,
            modified_at=request.expected_modified_at,
        )
        outcome = FileHasher(self._sandbox_root).hash_file(synthetic)
        if isinstance(outcome, HashFailure):
            if outcome.issue.issue_type is HashIssueType.NOT_FOUND:
                return self._rejected(
                    request, VaultRejectionCode.SOURCE_NOT_FOUND, evaluated_at
                )
            if outcome.issue.issue_type in (
                HashIssueType.PATH_OUTSIDE_SANDBOX,
                HashIssueType.UNRESOLVABLE_PATH,
            ):
                return self._rejected(
                    request, VaultRejectionCode.SOURCE_OUTSIDE_SANDBOX, evaluated_at
                )
            return self._rejected(
                request, VaultRejectionCode.SOURCE_IDENTITY_CHANGED, evaluated_at
            )
        if outcome.hashed.sha256 != request.expected_sha256:
            return self._rejected(
                request, VaultRejectionCode.SOURCE_HASH_MISMATCH, evaluated_at
            )
        verified_sha = request.expected_sha256

        # Step 2.5: Vault-tree safety precondition -- before any read or
        # write under vault_root, including the idempotency pre-check below.
        if find_unsafe_vault_reparse_point(self._app_paths) is not None:
            return self._rejected(
                request, VaultRejectionCode.VAULT_STORAGE_UNSAFE, evaluated_at
            )

        final_path = object_abs_path(self._app_paths, verified_sha)
        prefix_dir = object_prefix_dir(self._app_paths, verified_sha)

        # Idempotency pre-check -- optimization only; the actual no-overwrite
        # guarantee comes from the publish step's atomic, non-overwriting
        # rename below, not from this check.
        if final_path.exists():
            started_at = self._clock()
            if _rehash_vault_object(final_path) == verified_sha:
                return self._already_present(
                    request,
                    verified_sha,
                    final_path.stat().st_size,
                    evaluated_at,
                    started_at,
                    self._clock(),
                )
            return self._rejected(
                request,
                VaultRejectionCode.EXISTING_VAULT_OBJECT_CORRUPTED,
                evaluated_at,
                started_at=started_at,
                completed_at=self._clock(),
            )

        # Per-SHA prefix-directory safety, checked immediately before use --
        # this fan-out directory is not covered by find_unsafe_vault_
        # reparse_point's top-level sweep since it is specific to this one
        # digest. A point-in-time check only; see safety.py's module
        # docstring for the accepted residual TOCTOU. No exception is raised
        # here (unlike bootstrap) -- this is a per-request environmental
        # precondition on an already-valid engine, reported as REJECTED.
        if prefix_dir.exists() and is_unsafe_reparse_point(prefix_dir):
            return self._rejected(
                request, VaultRejectionCode.VAULT_STORAGE_UNSAFE, evaluated_at
            )

        # Steps 3+4: stream + hash while copying into app-owned temp storage.
        prefix_dir.mkdir(parents=True, exist_ok=True)
        temp_path = new_temp_path(self._app_paths)
        started_at = self._clock()
        digest = hashlib.sha256()
        bytes_copied = 0
        try:
            if request.source_path.is_symlink() or os.path.isjunction(
                request.source_path
            ):
                raise _SourceChangedDuringCapture(
                    "source became a reparse point before copy began"
                )
            with (
                open(request.source_path, "rb") as src,
                open(temp_path, "wb") as dst,
            ):
                while chunk := src.read(_CHUNK_SIZE):
                    dst.write(chunk)
                    digest.update(chunk)
                    bytes_copied += len(chunk)
        except _SourceChangedDuringCapture:
            _best_effort_unlink(temp_path)
            return self._rejected(
                request,
                VaultRejectionCode.SOURCE_CHANGED_DURING_CAPTURE,
                evaluated_at,
                started_at=started_at,
                completed_at=self._clock(),
            )
        except OSError as exc:
            _best_effort_unlink(temp_path)
            return self._failed(
                request, f"copy failed: {exc}", evaluated_at, started_at, self._clock()
            )

        # Step 5: verify.
        verified_digest = digest.hexdigest()
        if (
            verified_digest != request.expected_sha256
            or bytes_copied != request.expected_size
        ):
            _best_effort_unlink(temp_path)
            return self._rejected(
                request,
                VaultRejectionCode.SOURCE_CHANGED_DURING_CAPTURE,
                evaluated_at,
                started_at=started_at,
                completed_at=self._clock(),
            )

        # Steps 6+7: publish via a single atomic, non-overwriting rename --
        # not a check-then-act pair. See the design plan's "Publication
        # primitive" section for why Path.rename(), not Path.replace(), and
        # what its Windows-specific non-overwrite guarantee is and is not.
        try:
            temp_path.rename(final_path)
        except FileExistsError:
            rehash = _rehash_vault_object(final_path)
            _best_effort_unlink(temp_path)
            if rehash == verified_digest:
                return self._already_present(
                    request,
                    verified_digest,
                    final_path.stat().st_size,
                    evaluated_at,
                    started_at,
                    self._clock(),
                )
            return self._rejected(
                request,
                VaultRejectionCode.EXISTING_VAULT_OBJECT_CORRUPTED,
                evaluated_at,
                started_at=started_at,
                completed_at=self._clock(),
            )
        except OSError as exc:
            _best_effort_unlink(temp_path)
            return self._failed(
                request,
                f"publish failed: {exc}",
                evaluated_at,
                started_at,
                self._clock(),
            )

        return self._captured(
            request,
            verified_digest,
            bytes_copied,
            evaluated_at,
            started_at,
            self._clock(),
        )

    def _rejected(
        self,
        request: VaultCaptureRequest,
        code: VaultRejectionCode,
        evaluated_at: datetime,
        *,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> VaultCaptureResult:
        return VaultCaptureResult(
            request_id=request.id,
            file_id=request.file_id,
            source_path=request.source_path,
            expected_sha256=request.expected_sha256,
            expected_size=request.expected_size,
            status=VaultCaptureStatus.REJECTED,
            rejection_code=code,
            evaluated_at=evaluated_at,
            started_at=started_at,
            completed_at=completed_at,
            vault_engine_id=VAULT_ENGINE_ID,
        )

    def _failed(
        self,
        request: VaultCaptureRequest,
        failure_reason: str,
        evaluated_at: datetime,
        started_at: datetime | None,
        completed_at: datetime,
    ) -> VaultCaptureResult:
        return VaultCaptureResult(
            request_id=request.id,
            file_id=request.file_id,
            source_path=request.source_path,
            expected_sha256=request.expected_sha256,
            expected_size=request.expected_size,
            status=VaultCaptureStatus.FAILED,
            failure_reason=failure_reason,
            evaluated_at=evaluated_at,
            started_at=started_at if started_at is not None else completed_at,
            completed_at=completed_at,
            vault_engine_id=VAULT_ENGINE_ID,
        )

    def _terminal_success(
        self,
        request: VaultCaptureRequest,
        status: VaultCaptureStatus,
        verified_sha256: str,
        verified_size: int,
        evaluated_at: datetime,
        started_at: datetime,
        completed_at: datetime,
    ) -> VaultCaptureResult:
        return VaultCaptureResult(
            request_id=request.id,
            file_id=request.file_id,
            source_path=request.source_path,
            expected_sha256=request.expected_sha256,
            expected_size=request.expected_size,
            status=status,
            verified_sha256=verified_sha256,
            verified_size=verified_size,
            vault_object_path=object_relative_path(verified_sha256),
            evaluated_at=evaluated_at,
            started_at=started_at,
            completed_at=completed_at,
            vault_engine_id=VAULT_ENGINE_ID,
        )

    def _captured(
        self,
        request: VaultCaptureRequest,
        verified_sha256: str,
        verified_size: int,
        evaluated_at: datetime,
        started_at: datetime,
        completed_at: datetime,
    ) -> VaultCaptureResult:
        return self._terminal_success(
            request,
            VaultCaptureStatus.CAPTURED,
            verified_sha256,
            verified_size,
            evaluated_at,
            started_at,
            completed_at,
        )

    def _already_present(
        self,
        request: VaultCaptureRequest,
        verified_sha256: str,
        verified_size: int,
        evaluated_at: datetime,
        started_at: datetime,
        completed_at: datetime,
    ) -> VaultCaptureResult:
        return self._terminal_success(
            request,
            VaultCaptureStatus.ALREADY_PRESENT,
            verified_sha256,
            verified_size,
            evaluated_at,
            started_at,
            completed_at,
        )


def vault_capture_requested_event(request: VaultCaptureRequest) -> DomainEvent:
    """Maps a VaultCaptureRequest to a VAULT_CAPTURE_REQUESTED DomainEvent --
    the durable checkpoint a caller persists BEFORE calling capture(). Does
    not persist anything itself -- this package has no dependency on
    file_agent.persistence.
    """
    return DomainEvent(
        event_type=EventType.VAULT_CAPTURE_REQUESTED,
        entity_type=EntityType.VAULT_CAPTURE,
        entity_id=request.id,
        timestamp=request.requested_at,
        payload={
            "request_id": str(request.id),
            "file_id": str(request.file_id),
            "source_path": str(request.source_path),
            "expected_sha256": request.expected_sha256,
            "expected_size": request.expected_size,
        },
    )


_RESULT_EVENT_TYPE: dict[VaultCaptureStatus, EventType] = {
    VaultCaptureStatus.CAPTURED: EventType.VAULT_CAPTURE_SUCCEEDED,
    VaultCaptureStatus.ALREADY_PRESENT: EventType.VAULT_CAPTURE_SUCCEEDED,
    VaultCaptureStatus.REJECTED: EventType.VAULT_CAPTURE_FAILED,
    VaultCaptureStatus.FAILED: EventType.VAULT_CAPTURE_FAILED,
}


def vault_capture_result_event(result: VaultCaptureResult) -> DomainEvent:
    """Maps a VaultCaptureResult to its terminal DomainEvent
    (VAULT_CAPTURE_SUCCEEDED for CAPTURED/ALREADY_PRESENT,
    VAULT_CAPTURE_FAILED for REJECTED/FAILED -- the finer distinction lives
    in the payload's status/rejection_code/failure_reason). Takes ONLY the
    result -- every field the payload needs already lives on it, so this can
    never be called with a result paired against an unrelated request.
    """
    return DomainEvent(
        event_type=_RESULT_EVENT_TYPE[result.status],
        entity_type=EntityType.VAULT_CAPTURE,
        entity_id=result.request_id,
        timestamp=result.completed_at
        if result.completed_at is not None
        else result.evaluated_at,
        payload={
            "request_id": str(result.request_id),
            "file_id": str(result.file_id),
            "source_path": str(result.source_path),
            "expected_sha256": result.expected_sha256,
            "expected_size": result.expected_size,
            "status": result.status.value,
            "rejection_code": (
                result.rejection_code.value
                if result.rejection_code is not None
                else None
            ),
            "failure_reason": result.failure_reason,
            "verified_sha256": result.verified_sha256,
            "verified_size": result.verified_size,
            "vault_object_path": result.vault_object_path,
            "started_at": result.started_at.isoformat()
            if result.started_at is not None
            else None,
            "completed_at": result.completed_at.isoformat()
            if result.completed_at is not None
            else None,
            "vault_engine_id": result.vault_engine_id,
        },
    )
