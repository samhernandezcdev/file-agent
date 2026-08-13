"""Documents the repeated-decision gap explicitly -- does not exercise
persistence at all, so this is not presented as supported integration
behavior. HumanReviewEngine has no persistence dependency and therefore
cannot itself enforce "one effective review per PolicyDecision" across
separate calls; that limit is a documented obligation of a future
application/orchestration layer (see human_review_engine's module
docstring), not implemented or tested here as something the engine, the
domain model, or persistence resolves.
"""

from collections.abc import Callable

from file_agent.domain import FileProposal, HumanReviewOutcome, PolicyDecision
from file_agent.human_review_engine import record_human_review


def test_engine_has_no_memory_across_calls_for_the_same_policy_decision(
    make_proposal: Callable[..., FileProposal],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    """A second, contradictory call for the same policy_decision_id is not
    rejected by the engine -- proving the engine is stateless/pure and
    genuinely cannot enforce cross-record uniqueness itself, exactly as
    documented. This is the gap, not a feature: production/application
    orchestration MUST reject a second effective review for the same
    policy_decision_id until explicit revoke/supersede semantics exist --
    the engine's silence here is why that external enforcement is required.
    """
    proposal = make_proposal()
    policy_decision = make_policy_decision(proposal)

    first = record_human_review(policy_decision, proposal, HumanReviewOutcome.APPROVE)
    second = record_human_review(policy_decision, proposal, HumanReviewOutcome.SKIP)

    assert first.id != second.id
    assert first.policy_decision_id == second.policy_decision_id == policy_decision.id
    assert first.outcome is HumanReviewOutcome.APPROVE
    assert second.outcome is HumanReviewOutcome.SKIP
    # No assertion, and no code path anywhere in this package, claims either
    # of these is "the effective" decision -- that determination belongs to
    # the orchestration layer this ticket does not implement.
