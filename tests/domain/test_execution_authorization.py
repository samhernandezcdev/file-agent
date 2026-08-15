"""Tests for ExecutionAuthorization -- the only sanctioned way to authorize
a TransactionEngine execution. POLICY_AUTO and HUMAN_APPROVED must never be
interchangeable, and neither factory may ever be satisfied by anything less
than a genuine, matching PolicyDecision/HumanReviewDecision pair."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from file_agent.domain import (
    DestinationCategory,
    ExecutionAuthorization,
    ExecutionAuthorizationKind,
    FileCategory,
    HumanReviewDecision,
    HumanReviewOutcome,
    PolicyDecision,
    PolicyOutcome,
    ReviewSource,
)

_NOW = datetime.now(UTC)


def _policy_decision(**overrides: object) -> PolicyDecision:
    defaults: dict[str, object] = {
        "proposal_id": uuid4(),
        "file_id": uuid4(),
        "decision": PolicyOutcome.AUTO,
        "reasons": ("stub reason",),
        "evaluated_at": _NOW,
        "policy_engine_id": "rules-v1",
        "source_category": FileCategory.DOCUMENT,
        "destination_category": DestinationCategory.DOCUMENTS,
        "proposal_confidence": 0.9,
        "proposal_engine_id": "rules-v1",
    }
    defaults.update(overrides)
    return PolicyDecision(**defaults)


def _review(
    policy_decision: PolicyDecision, **overrides: object
) -> HumanReviewDecision:
    defaults: dict[str, object] = {
        "policy_decision_id": policy_decision.id,
        "proposal_id": policy_decision.proposal_id,
        "file_id": policy_decision.file_id,
        "outcome": HumanReviewOutcome.APPROVE,
        "destination_category": policy_decision.destination_category,
        "reviewed_at": _NOW,
        "review_source": ReviewSource.USER,
        "policy_engine_id": "rules-v1",
        "proposal_engine_id": "rules-v1",
        "human_review_engine_id": "rules-v1",
    }
    defaults.update(overrides)
    return HumanReviewDecision(**defaults)


# --- POLICY_AUTO -------------------------------------------------------------


def test_from_policy_auto_succeeds_for_genuine_auto_decision() -> None:
    policy_decision = _policy_decision(decision=PolicyOutcome.AUTO)

    authorization = ExecutionAuthorization.from_policy_auto(policy_decision)

    assert authorization.authorization_kind is ExecutionAuthorizationKind.POLICY_AUTO
    assert authorization.policy_decision_id == policy_decision.id
    assert authorization.proposal_id == policy_decision.proposal_id
    assert authorization.file_id == policy_decision.file_id
    assert authorization.destination_category == policy_decision.destination_category
    assert authorization.human_review_decision_id is None


def test_from_policy_auto_rejects_review_decision() -> None:
    policy_decision = _policy_decision(decision=PolicyOutcome.REVIEW)

    with pytest.raises(ValueError, match="AUTO"):
        ExecutionAuthorization.from_policy_auto(policy_decision)


def test_from_policy_auto_rejects_block_decision() -> None:
    policy_decision = _policy_decision(
        decision=PolicyOutcome.BLOCK, destination_category=None
    )

    with pytest.raises(ValueError, match="AUTO"):
        ExecutionAuthorization.from_policy_auto(policy_decision)


# --- HUMAN_APPROVED ----------------------------------------------------------


def test_from_human_approval_succeeds_for_genuine_review_and_approve() -> None:
    policy_decision = _policy_decision(decision=PolicyOutcome.REVIEW)
    review = _review(policy_decision, outcome=HumanReviewOutcome.APPROVE)

    authorization = ExecutionAuthorization.from_human_approval(policy_decision, review)

    assert authorization.authorization_kind is ExecutionAuthorizationKind.HUMAN_APPROVED
    assert authorization.policy_decision_id == policy_decision.id
    assert authorization.proposal_id == policy_decision.proposal_id
    assert authorization.file_id == policy_decision.file_id
    assert authorization.destination_category == policy_decision.destination_category
    assert authorization.human_review_decision_id == review.id


def test_from_human_approval_rejects_non_review_policy_decision() -> None:
    policy_decision = _policy_decision(decision=PolicyOutcome.AUTO)
    review = _review(policy_decision, outcome=HumanReviewOutcome.APPROVE)

    with pytest.raises(ValueError, match="REVIEW"):
        ExecutionAuthorization.from_human_approval(policy_decision, review)


def test_from_human_approval_rejects_block_policy_decision() -> None:
    policy_decision = _policy_decision(
        decision=PolicyOutcome.BLOCK, destination_category=None
    )
    review = _review(
        policy_decision,
        outcome=HumanReviewOutcome.APPROVE,
        destination_category=None,
    )

    with pytest.raises(ValueError, match="REVIEW"):
        ExecutionAuthorization.from_human_approval(policy_decision, review)


def test_from_human_approval_rejects_skip_outcome() -> None:
    policy_decision = _policy_decision(decision=PolicyOutcome.REVIEW)
    review = _review(policy_decision, outcome=HumanReviewOutcome.SKIP)

    with pytest.raises(ValueError, match="APPROVE"):
        ExecutionAuthorization.from_human_approval(policy_decision, review)


@pytest.mark.parametrize(
    "field",
    ["policy_decision_id", "proposal_id", "file_id", "destination_category"],
)
def test_from_human_approval_rejects_mismatched_lineage(field: str) -> None:
    policy_decision = _policy_decision(decision=PolicyOutcome.REVIEW)
    overrides: dict[str, object] = {}
    if field == "policy_decision_id":
        overrides["policy_decision_id"] = uuid4()
    elif field == "proposal_id":
        overrides["proposal_id"] = uuid4()
    elif field == "file_id":
        overrides["file_id"] = uuid4()
    else:
        overrides["destination_category"] = DestinationCategory.IMAGES
    review = _review(policy_decision, outcome=HumanReviewOutcome.APPROVE, **overrides)

    with pytest.raises(ValueError):
        ExecutionAuthorization.from_human_approval(policy_decision, review)


def test_from_human_approval_rejects_missing_destination_category() -> None:
    policy_decision = _policy_decision(
        decision=PolicyOutcome.REVIEW, destination_category=None
    )
    review = _review(
        policy_decision,
        outcome=HumanReviewOutcome.APPROVE,
        destination_category=None,
    )

    with pytest.raises(ValueError, match="destination_category"):
        ExecutionAuthorization.from_human_approval(policy_decision, review)


# --- Internal consistency (defense in depth against a hand-built instance) --


def test_kind_consistency_policy_auto_rejects_human_review_decision_id() -> None:
    with pytest.raises(ValidationError):
        ExecutionAuthorization(
            policy_decision_id=uuid4(),
            proposal_id=uuid4(),
            file_id=uuid4(),
            destination_category=DestinationCategory.DOCUMENTS,
            authorization_kind=ExecutionAuthorizationKind.POLICY_AUTO,
            human_review_decision_id=uuid4(),
        )


def test_kind_consistency_human_approved_requires_human_review_decision_id() -> None:
    with pytest.raises(ValidationError):
        ExecutionAuthorization(
            policy_decision_id=uuid4(),
            proposal_id=uuid4(),
            file_id=uuid4(),
            destination_category=DestinationCategory.DOCUMENTS,
            authorization_kind=ExecutionAuthorizationKind.HUMAN_APPROVED,
            human_review_decision_id=None,
        )


# --- Trust-boundary demonstration -------------------------------------------


def test_direct_construction_is_technically_possible_but_not_persisted_proof() -> None:
    """ExecutionAuthorization is a plain, frozen Pydantic BaseModel -- NOT a
    private-constructor or cryptographically signed type. This test exists
    to demonstrate, explicitly, that nothing in the model itself prevents
    building a shape-valid, internally-consistent HUMAN_APPROVED
    authorization for a policy_decision_id/human_review_decision_id that
    were never genuinely evaluated, never genuinely approved, and may not
    even exist anywhere in persistence.

    This is NOT a bug to fix by adding signing/private-constructor
    machinery (see the module docstring's trust-boundary statement) -- it
    is why FileAgentApplicationService, not ExecutionAuthorization, is the
    actual authorization boundary: FileAgentApplicationService is the only
    code trusted to call the two sanctioned factories with genuinely
    persisted facts (enforced by
    tests/application/test_no_authorization_fabrication.py), and
    TransactionEngine only ever receives what FileAgentApplicationService
    constructs -- an untrusted caller has no path to it at all (enforced by
    tests/application/test_trust_boundary.py). This model's own shape
    validation cannot and does not distinguish this fabricated instance
    from a genuine one; that distinction exists only at the call-site
    discipline layer, one level up.
    """
    fabricated = ExecutionAuthorization(
        policy_decision_id=uuid4(),
        proposal_id=uuid4(),
        file_id=uuid4(),
        destination_category=DestinationCategory.DOCUMENTS,
        authorization_kind=ExecutionAuthorizationKind.HUMAN_APPROVED,
        human_review_decision_id=uuid4(),
    )

    assert fabricated.authorization_kind is ExecutionAuthorizationKind.HUMAN_APPROVED
