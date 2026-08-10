"""Category override and allowlist gate cannot be bypassed by confidence.

Proves the ordering, not just each rule in isolation: an EXECUTABLE proposal
at the same maximum confidence as a DOCUMENT proposal still lands on REVIEW
while the DOCUMENT proposal reaches AUTO.
"""

from collections.abc import Callable

from file_agent.domain import (
    DestinationCategory,
    FileCategory,
    FileProposal,
    PolicyOutcome,
)
from file_agent.policy_engine import evaluate_for


def test_executable_override_precedes_confidence_check(
    make_proposal: Callable[..., FileProposal],
) -> None:
    executable_proposal = make_proposal(
        category=FileCategory.EXECUTABLE,
        proposed_destination_category=DestinationCategory.EXECUTABLES,
        confidence=1.0,
        source_classification_confidence=1.0,
    )
    document_proposal = make_proposal(
        category=FileCategory.DOCUMENT,
        proposed_destination_category=DestinationCategory.DOCUMENTS,
        confidence=1.0,
        source_classification_confidence=1.0,
    )

    executable_decision = evaluate_for(executable_proposal)
    document_decision = evaluate_for(document_proposal)

    assert executable_decision.decision is PolicyOutcome.REVIEW
    assert document_decision.decision is PolicyOutcome.AUTO


def test_allowlist_gate_precedes_confidence_check(
    make_proposal: Callable[..., FileProposal],
) -> None:
    unapproved_pair_proposal = make_proposal(
        category=FileCategory.OTHER,
        proposed_destination_category=DestinationCategory.DOCUMENTS,
        confidence=1.0,
        source_classification_confidence=1.0,
    )
    approved_pair_proposal = make_proposal(
        category=FileCategory.DOCUMENT,
        proposed_destination_category=DestinationCategory.DOCUMENTS,
        confidence=1.0,
        source_classification_confidence=1.0,
    )

    unapproved_decision = evaluate_for(unapproved_pair_proposal)
    approved_decision = evaluate_for(approved_pair_proposal)

    assert unapproved_decision.decision is PolicyOutcome.REVIEW
    assert approved_decision.decision is PolicyOutcome.AUTO
