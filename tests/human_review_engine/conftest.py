"""Shared fixtures for human_review_engine tests."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from file_agent.domain import (
    DestinationCategory,
    FileCategory,
    FileProposal,
    PolicyDecision,
    PolicyOutcome,
)


@pytest.fixture
def make_proposal() -> Callable[..., FileProposal]:
    def _make(**overrides: object) -> FileProposal:
        defaults: dict[str, object] = {
            "file_id": uuid4(),
            "proposed_name": None,
            "proposed_destination": None,
            "proposed_destination_category": DestinationCategory.DOCUMENTS,
            "category": FileCategory.DOCUMENT,
            "confidence": 1.0,
            "source_classification_confidence": 1.0,
            "source_classifier_id": "rules-v1",
            "reasons": ("stub reason",),
            "created_at": datetime.now(UTC),
            "proposal_engine_id": "rules-v1",
        }
        defaults.update(overrides)
        return FileProposal(**defaults)

    return _make


@pytest.fixture
def make_policy_decision() -> Callable[..., PolicyDecision]:
    def _make(proposal: FileProposal, **overrides: object) -> PolicyDecision:
        defaults: dict[str, object] = {
            "proposal_id": proposal.id,
            "file_id": proposal.file_id,
            "decision": PolicyOutcome.REVIEW,
            "reasons": ("stub reason",),
            "policy_engine_id": "policy-v1",
            "source_category": proposal.category,
            "destination_category": proposal.proposed_destination_category,
            "proposal_confidence": proposal.confidence,
            "proposal_engine_id": proposal.proposal_engine_id,
        }
        defaults.update(overrides)
        return PolicyDecision(**defaults)

    return _make


@pytest.fixture
def fixed_clock() -> Callable[[], datetime]:
    fixed_time = datetime(2026, 1, 1, tzinfo=UTC)

    def clock() -> datetime:
        return fixed_time

    return clock
