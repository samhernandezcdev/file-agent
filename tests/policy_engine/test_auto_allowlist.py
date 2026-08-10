"""Default-deny AUTO eligibility (correction round 2).

AUTO must mean policy explicitly recognized the (category, destination) pair
as eligible -- not merely that no earlier rule rejected it. These tests
hand-construct FileProposals that FA-006 would never itself produce, proving
such combinations still cannot reach AUTO.
"""

from collections.abc import Callable

from file_agent.domain import (
    DestinationCategory,
    FileCategory,
    FileProposal,
    PolicyOutcome,
)
from file_agent.policy_engine import evaluate_for


def test_other_category_with_documents_destination_is_review(
    make_proposal: Callable[..., FileProposal],
) -> None:
    proposal = make_proposal(
        category=FileCategory.OTHER,
        proposed_destination_category=DestinationCategory.DOCUMENTS,
        confidence=1.0,
        source_classification_confidence=1.0,
    )

    decision = evaluate_for(proposal)

    assert decision.decision is PolicyOutcome.REVIEW
    assert any("allowlist" in reason for reason in decision.reasons)


def test_unknown_category_with_documents_destination_is_review(
    make_proposal: Callable[..., FileProposal],
) -> None:
    proposal = make_proposal(
        category=FileCategory.UNKNOWN,
        proposed_destination_category=DestinationCategory.DOCUMENTS,
        confidence=1.0,
        source_classification_confidence=1.0,
    )

    decision = evaluate_for(proposal)

    assert decision.decision is PolicyOutcome.REVIEW
    assert any("allowlist" in reason for reason in decision.reasons)


def test_document_category_with_executables_destination_is_review(
    make_proposal: Callable[..., FileProposal],
) -> None:
    """A DOCUMENT proposal that somehow points at the EXECUTABLES destination
    -- not producible by FA-006's own mapping table, but not structurally
    forbidden by FileProposal either. Must not reach AUTO just because the
    category itself isn't EXECUTABLE."""
    proposal = make_proposal(
        category=FileCategory.DOCUMENT,
        proposed_destination_category=DestinationCategory.EXECUTABLES,
        confidence=1.0,
        source_classification_confidence=1.0,
    )

    decision = evaluate_for(proposal)

    assert decision.decision is PolicyOutcome.REVIEW
    assert any("allowlist" in reason for reason in decision.reasons)


def test_unapproved_pair_cannot_fall_through_to_auto(
    make_proposal: Callable[..., FileProposal],
) -> None:
    """Stands in for a future/unapproved category or destination: any pair
    absent from AUTO_ELIGIBLE_PAIRS must land on REVIEW, not AUTO, purely by
    virtue of not being explicitly allowlisted -- default-deny, not
    default-allow."""
    proposal = make_proposal(
        category=FileCategory.ARCHIVE,
        proposed_destination_category=DestinationCategory.IMAGES,
        confidence=1.0,
        source_classification_confidence=1.0,
    )

    decision = evaluate_for(proposal)

    assert decision.decision is PolicyOutcome.REVIEW


def test_approved_pair_at_full_confidence_still_reaches_auto(
    make_proposal: Callable[..., FileProposal],
) -> None:
    """Positive control alongside the negative cases above: the allowlist
    rejects unapproved pairs without breaking the approved ones."""
    proposal = make_proposal(
        category=FileCategory.DOCUMENT,
        proposed_destination_category=DestinationCategory.DOCUMENTS,
        confidence=1.0,
        source_classification_confidence=1.0,
    )

    decision = evaluate_for(proposal)

    assert decision.decision is PolicyOutcome.AUTO
