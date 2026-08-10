"""No logical destination -> REVIEW, for a constructed no-destination
proposal and for real UNKNOWN/OTHER proposal-engine output."""

from collections.abc import Callable
from datetime import UTC, datetime

from file_agent.classifier import ClassificationResult
from file_agent.domain import DiscoveredFile, FileCategory, FileProposal, PolicyOutcome
from file_agent.policy_engine import evaluate_for
from file_agent.proposal_engine import propose_for


def test_no_destination_category_is_review(
    make_proposal: Callable[..., FileProposal],
) -> None:
    proposal = make_proposal(
        proposed_destination_category=None,
        category=FileCategory.OTHER,
        confidence=0.0,
        source_classification_confidence=0.0,
    )

    decision = evaluate_for(proposal)

    assert decision.decision is PolicyOutcome.REVIEW
    assert any("no logical destination" in reason for reason in decision.reasons)


def test_real_unknown_proposal_is_review(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    classification = ClassificationResult(
        discovered_file=make_discovered_file("C:/sandbox/whatever.unknownext"),
        category=FileCategory.UNKNOWN,
        confidence=0.0,
        reasons=("no rule matched",),
        classified_at=datetime.now(UTC),
        classifier_id="rules-v1",
    )
    proposal = propose_for(classification)
    assert proposal.proposed_destination_category is None

    decision = evaluate_for(proposal)

    assert decision.decision is PolicyOutcome.REVIEW


def test_real_other_proposal_is_review(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    classification = ClassificationResult(
        discovered_file=make_discovered_file("C:/sandbox/.env"),
        category=FileCategory.OTHER,
        confidence=1.0,
        reasons=("dotfile convention",),
        classified_at=datetime.now(UTC),
        classifier_id="rules-v1",
    )
    proposal = propose_for(classification)
    assert proposal.proposed_destination_category is None

    decision = evaluate_for(proposal)

    assert decision.decision is PolicyOutcome.REVIEW
