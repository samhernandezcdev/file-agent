"""Validates and records a human's APPROVE/SKIP decision for one REVIEW
PolicyDecision -- strictly a decision record, never execution.

AUTO does not need review (rejected as redundant); BLOCK cannot be
overridden (rejected unconditionally); only REVIEW may receive a decision.
APPROVE requires the underlying FileProposal to carry a logical destination;
SKIP does not. No filesystem I/O, no TransactionEngine dependency. See
docs/SAFETY.md and the FA-009 design plan.
"""

from file_agent.human_review_engine.engine import (
    HumanReviewEngine,
    InvalidHumanReviewError,
    human_review_recorded_event,
    record_human_review,
)
from file_agent.human_review_engine.rules import HUMAN_REVIEW_ENGINE_ID

__all__ = [
    "HUMAN_REVIEW_ENGINE_ID",
    "HumanReviewEngine",
    "InvalidHumanReviewError",
    "human_review_recorded_event",
    "record_human_review",
]
