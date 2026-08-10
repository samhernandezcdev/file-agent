"""PolicyEngine — deterministic, explainable, default-deny policy evaluation.

Performs no filesystem I/O of any kind and never itself executes anything —
evaluation is a pure, total function over an already-in-memory FileProposal.
See docs/SAFETY.md and the FA-007 design plan's non-goals (no
TransactionEngine, no file movement, no destination-path resolution).
"""

from collections.abc import Callable
from datetime import UTC, datetime

from file_agent.domain import (
    DomainEvent,
    EntityType,
    EventType,
    FileCategory,
    FileProposal,
    PolicyDecision,
    PolicyOutcome,
)
from file_agent.policy_engine.rules import (
    AUTO_CONFIDENCE_THRESHOLD,
    AUTO_ELIGIBLE_PAIRS,
    POLICY_ENGINE_ID,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PolicyEngine:
    """Evaluates a FileProposal against fixed, ordered policy rules.

    Never raises for a well-formed FileProposal — there is no I/O and
    nothing that can fail outside a caller's control. Always returns a
    PolicyDecision; BLOCK is part of the decision vocabulary but no v1 rule
    produces it. Never performs filesystem I/O and never itself executes
    anything, regardless of the decision -- AUTO is eligibility, not
    execution. See docs/SAFETY.md rule 6: confidence != permission.
    """

    def __init__(self, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock

    def evaluate(self, proposal: FileProposal) -> PolicyDecision:
        reasons: tuple[str, ...]
        if proposal.proposed_destination_category is None:
            outcome = PolicyOutcome.REVIEW
            reasons = (
                (
                    f"no logical destination was proposed (category="
                    f"{proposal.category.value}); automatic execution is not eligible"
                ),
            )
        elif proposal.category is FileCategory.EXECUTABLE:
            outcome = PolicyOutcome.REVIEW
            reasons = (
                f"category executable requires review under policy {POLICY_ENGINE_ID}",
                "confidence does not override this category rule",
            )
        elif (
            proposal.category,
            proposal.proposed_destination_category,
        ) not in AUTO_ELIGIBLE_PAIRS:
            outcome = PolicyOutcome.REVIEW
            reasons = (
                (
                    f"category/destination pair ({proposal.category.value}, "
                    f"{proposal.proposed_destination_category.value}) is not on "
                    f"the {POLICY_ENGINE_ID} AUTO-eligible allowlist"
                ),
            )
        elif proposal.confidence >= AUTO_CONFIDENCE_THRESHOLD:
            outcome = PolicyOutcome.AUTO
            reasons = (
                (
                    f"destination category "
                    f"{proposal.proposed_destination_category.value} exists"
                ),
                (
                    f"category/destination pair ({proposal.category.value}, "
                    f"{proposal.proposed_destination_category.value}) is on the "
                    f"{POLICY_ENGINE_ID} AUTO-eligible allowlist"
                ),
                (
                    f"proposal confidence {proposal.confidence:.2f} satisfies the "
                    f"{POLICY_ENGINE_ID} AUTO threshold "
                    f"({AUTO_CONFIDENCE_THRESHOLD:.2f})"
                ),
            )
        else:
            outcome = PolicyOutcome.REVIEW
            reasons = (
                (
                    f"proposal confidence {proposal.confidence:.2f} does not satisfy "
                    f"the {POLICY_ENGINE_ID} AUTO threshold "
                    f"({AUTO_CONFIDENCE_THRESHOLD:.2f})"
                ),
            )

        return PolicyDecision(
            proposal_id=proposal.id,
            file_id=proposal.file_id,
            decision=outcome,
            reasons=reasons,
            evaluated_at=self._clock(),
            policy_engine_id=POLICY_ENGINE_ID,
            source_category=proposal.category,
            destination_category=proposal.proposed_destination_category,
            proposal_confidence=proposal.confidence,
            proposal_engine_id=proposal.proposal_engine_id,
        )


def evaluate_for(proposal: FileProposal) -> PolicyDecision:
    """Convenience entry point: ``PolicyEngine().evaluate(proposal)``."""
    return PolicyEngine().evaluate(proposal)


def policy_decision_event(decision: PolicyDecision) -> DomainEvent:
    """Maps a PolicyDecision to a POLICY_EVALUATED DomainEvent.

    Does not persist anything itself — this package has no dependency on
    file_agent.persistence. A caller passes the returned event straight to
    FileAgentStore.record_event().
    """
    return DomainEvent(
        event_type=EventType.POLICY_EVALUATED,
        entity_type=EntityType.POLICY_DECISION,
        entity_id=decision.id,
        timestamp=decision.evaluated_at,
        payload={
            "proposal_id": str(decision.proposal_id),
            "file_id": str(decision.file_id),
            "decision": decision.decision.value,
            "source_category": decision.source_category.value,
            "destination_category": (
                decision.destination_category.value
                if decision.destination_category is not None
                else None
            ),
            "proposal_confidence": decision.proposal_confidence,
            "proposal_engine_id": decision.proposal_engine_id,
            "policy_engine_id": decision.policy_engine_id,
            "reasons": list(decision.reasons),
        },
    )
