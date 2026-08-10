"""Same FileProposal + same policy version + same clock -> identical decision
content, excluding the deliberately fresh `id`."""

from collections.abc import Callable
from datetime import datetime

from file_agent.domain import FileProposal
from file_agent.policy_engine import PolicyEngine, evaluate_for


def test_repeated_calls_produce_identical_results(
    make_proposal: Callable[..., FileProposal],
) -> None:
    proposal = make_proposal()

    first = evaluate_for(proposal)
    second = evaluate_for(proposal)

    assert first.decision == second.decision
    assert first.reasons == second.reasons
    assert first.source_category == second.source_category
    assert first.destination_category == second.destination_category


def test_full_result_is_deterministic_with_fixed_clock(
    make_proposal: Callable[..., FileProposal],
    fixed_clock: Callable[[], datetime],
) -> None:
    proposal = make_proposal()

    first = PolicyEngine(clock=fixed_clock).evaluate(proposal)
    second = PolicyEngine(clock=fixed_clock).evaluate(proposal)

    assert first.evaluated_at == second.evaluated_at == fixed_clock()
    assert first.model_dump(exclude={"id"}) == second.model_dump(exclude={"id"})
    assert first.id != second.id


def test_fresh_engine_instances_agree(
    make_proposal: Callable[..., FileProposal],
) -> None:
    proposal = make_proposal()
    results = [PolicyEngine().evaluate(proposal) for _ in range(5)]
    decisions = {r.decision for r in results}
    reasons = {r.reasons for r in results}
    assert len(decisions) == 1
    assert len(reasons) == 1
