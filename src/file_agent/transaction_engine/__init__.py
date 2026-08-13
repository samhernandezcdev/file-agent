"""TransactionEngine — the sole boundary through which a managed user file
may be mutated. MOVE only, sandbox-to-sandbox, AUTO-only, fail-closed. See
docs/SAFETY.md and the FA-008 design plan.

Caller orchestration shape (this package has no persistence dependency):

    outcome = engine.prepare(request, policy_decision)
    if isinstance(outcome, TransactionResult):          # REJECTED
        store.record_event(transaction_result_event(outcome))
        return outcome
    store.record_event(transaction_requested_event(request))   # checkpoint
    result = engine.commit(outcome)
    store.record_event(transaction_result_event(result))       # terminal
    return result
"""

from file_agent.transaction_engine.engine import (
    TransactionEngine,
    transaction_requested_event,
    transaction_result_event,
)
from file_agent.transaction_engine.errors import InvalidPreparedMoveError
from file_agent.transaction_engine.rules import TRANSACTION_ENGINE_ID

__all__ = [
    "TRANSACTION_ENGINE_ID",
    "InvalidPreparedMoveError",
    "TransactionEngine",
    "transaction_requested_event",
    "transaction_result_event",
]
