"""Errors raised by the Application Service itself.

FA-012 introduces exactly one new exception type. Every other exception a
caller might see already exists in a lower layer (persistence's
DatabaseUnavailableError/IntegrityConstraintError, vault_engine's/
recovery_engine's InvalidVaultConfigurationError/InvalidRecoveryConfigurationError)
and is re-raised as-is, never wrapped.
"""

from file_agent.application.dto import ApplyResult, RestoreResult, UndoResult


class TerminalPersistenceError(Exception):
    """Raised when a managed-file mutation (or recovery/vault operation)
    already completed via commit(), but persisting the terminal audit event
    failed. The operation is NOT rolled back and its real outcome is NOT
    reinterpreted as failure -- this exists solely to surface the audit gap
    distinctly, without silently swallowing it or misreporting what actually
    happened on disk.

    A caller catching this has the accurate, already-computed result (with
    status SUCCEEDED, and the real destination/restored path) via
    `.result` -- never a fabricated REJECTED/FAILED outcome. One shared
    class, not three per-DTO subclasses: `.result` is a union type, and
    `isinstance(exc.result, ApplyResult)` (etc.) is sufficient for a caller
    that needs to discriminate.
    """

    def __init__(
        self,
        result: ApplyResult | UndoResult | RestoreResult,
        cause: Exception,
    ) -> None:
        super().__init__(
            f"terminal event persistence failed after {type(result).__name__} "
            f"completed with status={result.status}: {cause}"
        )
        self.result = result
