"""RecoveryEngine -- reverses a known-successful MOVE (REVERSE_MOVE) or
reconstructs a file from a verified VaultObject (RESTORE_FROM_VAULT).
Zero managed-root mutation call sites of its own -- all mutation goes
through file_agent.managed_fs, the boundary shared with TransactionEngine.
See docs/SAFETY.md and the FA-011 design plan.

RecoveryEngine is NOT an authorization boundary against arbitrary untrusted
input -- see engine.py's module docstring for the full trust-boundary
contract before wiring this up to anything caller-facing.

Caller orchestration shape (this package has no persistence dependency):

    outcome = engine.prepare(request)
    if isinstance(outcome, RecoveryResult):          # REJECTED
        store.record_event(recovery_result_event(outcome))
        return outcome
    store.record_event(recovery_requested_event(request))   # checkpoint
    result = engine.commit(outcome)
    store.record_event(recovery_result_event(result))       # terminal
"""

from file_agent.recovery_engine.engine import (
    RecoveryEngine,
    recovery_requested_event,
    recovery_result_event,
)
from file_agent.recovery_engine.errors import (
    InvalidPreparedRecoveryError,
    InvalidRecoveryConfigurationError,
)
from file_agent.recovery_engine.rules import RECOVERY_ENGINE_ID

__all__ = [
    "RECOVERY_ENGINE_ID",
    "InvalidPreparedRecoveryError",
    "InvalidRecoveryConfigurationError",
    "RecoveryEngine",
    "recovery_requested_event",
    "recovery_result_event",
]
