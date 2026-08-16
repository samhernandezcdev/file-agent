"""TransactionEngine — the sole boundary through which a managed user file
may be moved. See docs/SAFETY.md, the FA-008 design plan, and FA-012's
ExecutionAuthorization correction (file_agent.domain.authorization).

Two-method shape (prepare()/commit()), not one execute(): the crash-window
analysis in the design plan requires a durable TRANSACTION_REQUESTED
checkpoint persisted between "preconditions passed" and "mutation
attempted" -- but this engine has no persistence dependency (matching every
other engine in this codebase). Splitting prepare()/commit() gives the
CALLER the natural seam to persist that checkpoint in between, without the
engine ever touching a Session. See __init__.py's module docstring for the
caller-orchestration shape.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from file_agent.domain import (
    DomainEvent,
    EntityType,
    EventType,
    ExecutionAuthorization,
    RejectionCode,
    TransactionRequest,
    TransactionResult,
    TransactionStatus,
)
from file_agent.managed_fs import move_no_replace
from file_agent.scanner import SandboxRoot
from file_agent.transaction_engine.errors import InvalidPreparedMoveError
from file_agent.transaction_engine.preconditions import (
    check_authorization_linkage,
    check_destination_category_matches_authorization,
    check_destination_category_physical_path,
    check_destination_readiness,
    verify_source_identity,
)
from file_agent.transaction_engine.rules import TRANSACTION_ENGINE_ID


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class _PreparedMove:
    """Opaque, one-shot capability proving every precondition passed for one
    specific TransactionEngine instance. Not exported from __init__.py --
    intentionally not part of the public API surface. Deliberately carries
    no caller-inspectable transaction data of its own -- commit() resolves
    the actual move using the issuing engine's own internal record, keyed by
    this capability's token, so a hand-built or copied-and-tampered instance
    cannot influence what actually gets moved. Construct only via
    TransactionEngine.prepare(); never inspect or reuse a token across
    engine instances.
    """

    _token: UUID


class TransactionEngine:
    """Evaluates a TransactionRequest against fixed, ordered preconditions
    and, once authorized, performs exactly one same-volume MOVE.

    Never mutates the filesystem in prepare(). commit() is only reachable
    with a _PreparedMove, which only prepare() can produce -- and only on
    the success path, so a rejected preparation can never yield a
    committable capability. See docs/SAFETY.md rule 6: AUTO is eligibility,
    not execution -- this engine still requires an explicit, separate
    commit() call even after prepare() succeeds.
    """

    def __init__(
        self, sandbox_root: SandboxRoot, *, clock: Callable[[], datetime] = _utc_now
    ) -> None:
        self._sandbox_root = sandbox_root
        self._clock = clock
        self._pending: dict[UUID, tuple[TransactionRequest, str, datetime]] = {}
        # Private, per-instance registry: token -> (request, verified_sha256,
        # evaluated_at) for every _PreparedMove issued and not yet consumed.
        # This IS the enforcement mechanism -- not documentation, not
        # convention. Single-threaded/synchronous usage is assumed, matching
        # every other engine in this codebase; not designed for concurrent
        # commit() calls racing on the same token.

    def prepare(
        self, request: TransactionRequest, authorization: ExecutionAuthorization
    ) -> "_PreparedMove | TransactionResult":
        """Runs every precondition in order. Returns a REJECTED
        TransactionResult if anything fails -- registering nothing in
        self._pending in that case, so a rejected prepare() can never yield
        a committable capability. On success, mints a fresh token, records
        (request, verified_sha256, evaluated_at) keyed by it, and returns
        the opaque capability. Never mutates the filesystem.

        authorization is expected to be a genuine ExecutionAuthorization,
        built via ExecutionAuthorization.from_policy_auto/from_human_approval
        by the trusted caller (FileAgentApplicationService) -- this engine
        never inspects a PolicyDecision or HumanReviewDecision itself, and
        never re-decides whether execution is allowed. It only performs
        MECHANICAL authorization/request lineage checking: does
        authorization's policy_decision_id/proposal_id/file_id/
        destination_category match this request's? A MISMATCHED
        authorization (wrong lineage for this request) is rejected here
        (AUTHORIZATION_LINKAGE_MISMATCH / DESTINATION_CATEGORY_MISMATCH). A
        forged-but-internally-consistent authorization -- correct shape,
        matching lineage, but never actually derived from a genuinely
        persisted PolicyDecision/HumanReviewDecision -- is outside this
        engine's threat boundary; verifying that persisted-authenticity
        question is FileAgentApplicationService's responsibility, not this
        engine's. See file_agent.domain.authorization's module docstring
        for the full trust-boundary statement.
        """
        evaluated_at = self._clock()

        precondition_checks: tuple[Callable[[], RejectionCode | None], ...] = (
            lambda: check_authorization_linkage(request, authorization),
            lambda: check_destination_category_matches_authorization(
                request, authorization
            ),
            lambda: check_destination_category_physical_path(
                request, self._sandbox_root
            ),
            lambda: check_destination_readiness(request, self._sandbox_root),
        )
        for check in precondition_checks:
            code = check()
            if code is not None:
                return self._rejected(request, code, evaluated_at)

        identity = verify_source_identity(request, self._sandbox_root)
        if isinstance(identity, RejectionCode):
            return self._rejected(request, identity, evaluated_at)

        token = uuid4()
        self._pending[token] = (request, identity, evaluated_at)
        return _PreparedMove(_token=token)

    def commit(self, prepared: "_PreparedMove") -> TransactionResult:
        """Looks up prepared._token via .pop() -- one-shot consumption. If
        not found (forged token, a token from a different engine instance,
        or an already-committed token), raises InvalidPreparedMoveError
        without touching the filesystem. Otherwise performs the actual
        Path.rename() using ONLY the engine's own stored data -- never
        anything read off `prepared` itself, which carries no other data
        anyway. Returns SUCCEEDED or FAILED.
        """
        entry = self._pending.pop(prepared._token, None)
        if entry is None:
            raise InvalidPreparedMoveError(
                "prepared move is forged, belongs to a different TransactionEngine "
                "instance, or was already committed"
            )
        request, verified_sha256, evaluated_at = entry
        started_at = self._clock()
        try:
            move_no_replace(request.source_path, request.destination_path)
        except OSError as exc:
            return self._terminal(
                request,
                status=TransactionStatus.FAILED,
                evaluated_at=evaluated_at,
                started_at=started_at,
                completed_at=self._clock(),
                verified_sha256=verified_sha256,
                failure_reason=str(exc),
            )
        return self._terminal(
            request,
            status=TransactionStatus.SUCCEEDED,
            evaluated_at=evaluated_at,
            started_at=started_at,
            completed_at=self._clock(),
            verified_sha256=verified_sha256,
        )

    def _rejected(
        self, request: TransactionRequest, code: RejectionCode, evaluated_at: datetime
    ) -> TransactionResult:
        return TransactionResult(
            request_id=request.id,
            file_id=request.file_id,
            proposal_id=request.proposal_id,
            policy_decision_id=request.policy_decision_id,
            operation=request.operation,
            source_path=request.source_path,
            destination_path=request.destination_path,
            destination_category=request.destination_category,
            expected_sha256=request.expected_sha256,
            expected_size=request.expected_size,
            status=TransactionStatus.REJECTED,
            rejection_code=code,
            evaluated_at=evaluated_at,
            transaction_engine_id=TRANSACTION_ENGINE_ID,
        )

    def _terminal(
        self,
        request: TransactionRequest,
        *,
        status: TransactionStatus,
        evaluated_at: datetime,
        started_at: datetime,
        completed_at: datetime,
        verified_sha256: str,
        failure_reason: str | None = None,
    ) -> TransactionResult:
        return TransactionResult(
            request_id=request.id,
            file_id=request.file_id,
            proposal_id=request.proposal_id,
            policy_decision_id=request.policy_decision_id,
            operation=request.operation,
            source_path=request.source_path,
            destination_path=request.destination_path,
            destination_category=request.destination_category,
            expected_sha256=request.expected_sha256,
            expected_size=request.expected_size,
            status=status,
            failure_reason=failure_reason,
            verified_sha256=verified_sha256,
            evaluated_at=evaluated_at,
            started_at=started_at,
            completed_at=completed_at,
            transaction_engine_id=TRANSACTION_ENGINE_ID,
        )


def transaction_requested_event(request: TransactionRequest) -> DomainEvent:
    """Maps a TransactionRequest to a TRANSACTION_REQUESTED DomainEvent --
    the durable checkpoint a caller persists AFTER prepare() succeeds and
    BEFORE calling commit(). Does not persist anything itself -- this
    package has no dependency on file_agent.persistence.
    """
    return DomainEvent(
        event_type=EventType.TRANSACTION_REQUESTED,
        entity_type=EntityType.TRANSACTION,
        entity_id=request.id,
        timestamp=request.requested_at,
        payload={
            "transaction_id": str(request.id),
            "file_id": str(request.file_id),
            "proposal_id": str(request.proposal_id),
            "policy_decision_id": str(request.policy_decision_id),
            "operation": request.operation.value,
            "source_path": str(request.source_path),
            "destination_path": str(request.destination_path),
            "destination_category": request.destination_category.value,
            "expected_sha256": request.expected_sha256,
            "expected_size": request.expected_size,
            "transaction_engine_id": TRANSACTION_ENGINE_ID,
        },
    )


_RESULT_EVENT_TYPE: dict[TransactionStatus, EventType] = {
    TransactionStatus.REJECTED: EventType.TRANSACTION_REJECTED,
    TransactionStatus.SUCCEEDED: EventType.TRANSACTION_SUCCEEDED,
    TransactionStatus.FAILED: EventType.TRANSACTION_FAILED,
}


def transaction_result_event(result: TransactionResult) -> DomainEvent:
    """Maps a TransactionResult to its terminal DomainEvent
    (TRANSACTION_REJECTED / TRANSACTION_SUCCEEDED / TRANSACTION_FAILED,
    chosen from result.status). Does not persist anything itself. Carries
    the complete structured authorization lineage -- not reconstructable
    only from prose -- regardless of status.
    """
    return DomainEvent(
        event_type=_RESULT_EVENT_TYPE[result.status],
        entity_type=EntityType.TRANSACTION,
        entity_id=result.request_id,
        timestamp=result.completed_at
        if result.completed_at is not None
        else result.evaluated_at,
        payload={
            "transaction_id": str(result.request_id),
            "file_id": str(result.file_id),
            "proposal_id": str(result.proposal_id),
            "policy_decision_id": str(result.policy_decision_id),
            "operation": result.operation.value,
            "source_path": str(result.source_path),
            "destination_path": str(result.destination_path),
            "destination_category": result.destination_category.value,
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
            "evaluated_at": result.evaluated_at.isoformat(),
            "started_at": result.started_at.isoformat()
            if result.started_at is not None
            else None,
            "completed_at": (
                result.completed_at.isoformat()
                if result.completed_at is not None
                else None
            ),
            "transaction_engine_id": result.transaction_engine_id,
        },
    )
