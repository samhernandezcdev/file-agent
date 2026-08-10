"""Deterministic policy evaluation — decision only, never filesystem mutation.

Given a FileProposal, answers "what does policy permit us to do with this
proposal?" using fixed, ordered rules with default-deny AUTO eligibility —
no filesystem I/O, no execution, no TransactionEngine. confidence != permission:
see docs/SAFETY.md rule 6 and the FA-007 design plan.
"""

from file_agent.policy_engine.engine import (
    PolicyEngine,
    evaluate_for,
    policy_decision_event,
)
from file_agent.policy_engine.rules import POLICY_ENGINE_ID

__all__ = [
    "POLICY_ENGINE_ID",
    "PolicyEngine",
    "evaluate_for",
    "policy_decision_event",
]
