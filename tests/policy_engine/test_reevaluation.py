"""The same proposal may be evaluated multiple times -- fresh identity each
time, never an update to a prior decision."""

from collections.abc import Callable

from file_agent.domain import FileProposal
from file_agent.policy_engine import evaluate_for


def test_repeated_evaluation_produces_fresh_identity(
    make_proposal: Callable[..., FileProposal],
) -> None:
    proposal = make_proposal()

    first = evaluate_for(proposal)
    second = evaluate_for(proposal)

    assert first.id != second.id
    assert first.proposal_id == second.proposal_id == proposal.id
    assert first.decision == second.decision
