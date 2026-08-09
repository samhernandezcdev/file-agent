"""Deterministic, explainable destination proposals — strictly informational.

Given a ClassificationResult, answers "what logical destination would File
Agent propose?" using a fixed FileCategory -> DestinationCategory table — no
filesystem I/O, no renaming, no organization-root concept, no authorization.
See docs/SAFETY.md and the FA-006 design plan.
"""

from file_agent.proposal_engine.engine import (
    ProposalEngine,
    proposal_event,
    propose_for,
)
from file_agent.proposal_engine.rules import PROPOSAL_ENGINE_ID

__all__ = [
    "PROPOSAL_ENGINE_ID",
    "ProposalEngine",
    "proposal_event",
    "propose_for",
]
