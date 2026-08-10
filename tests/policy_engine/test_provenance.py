"""Structured proposal provenance on the resulting PolicyDecision."""

from collections.abc import Callable

from file_agent.domain import FileProposal
from file_agent.policy_engine import POLICY_ENGINE_ID, evaluate_for


def test_provenance_fields_match_source_proposal(
    make_proposal: Callable[..., FileProposal],
) -> None:
    proposal = make_proposal(
        proposal_engine_id="rules-v2-experimental",
    )

    decision = evaluate_for(proposal)

    assert decision.proposal_id == proposal.id
    assert decision.file_id == proposal.file_id
    assert decision.source_category is proposal.category
    assert decision.destination_category == proposal.proposed_destination_category
    assert decision.proposal_confidence == proposal.confidence
    assert decision.proposal_engine_id == "rules-v2-experimental"
    assert decision.policy_engine_id == POLICY_ENGINE_ID
