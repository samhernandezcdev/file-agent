"""TransactionEngine — the sole boundary through which a managed user file
may be mutated. MOVE only, sandbox-to-sandbox, fail-closed. See
docs/SAFETY.md and the FA-008 design plan.

prepare() takes an ExecutionAuthorization (file_agent.domain.authorization),
not a PolicyDecision -- the engine never inspects PolicyDecision.decision or
HumanReviewDecision itself; it only mechanically checks that
authorization's own lineage (policy_decision_id/proposal_id/file_id/
destination_category) matches this request's. It does not and cannot verify
that the authorization was genuinely derived from persisted facts -- that is
FileAgentApplicationService's responsibility (via
ExecutionAuthorization.from_policy_auto/from_human_approval), not this
engine's. See file_agent.domain.authorization's module docstring for the
full trust-boundary statement, and FA-012's correction for why
PolicyDecision.decision must never be rewritten to AUTO to represent a
human's approval.

Caller orchestration shape (this package has no persistence dependency):

    outcome = engine.prepare(request, authorization)
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
from file_agent.transaction_engine.preconditions import verify_source_identity
from file_agent.transaction_engine.rules import TRANSACTION_ENGINE_ID

__all__ = [
    "TRANSACTION_ENGINE_ID",
    "InvalidPreparedMoveError",
    "TransactionEngine",
    "transaction_requested_event",
    "transaction_result_event",
    "verify_source_identity",
]
