"""Shared fixtures for policy_engine tests."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from file_agent.domain import (
    DestinationCategory,
    DiscoveredFile,
    FileCategory,
    FileProposal,
)


@pytest.fixture
def make_discovered_file() -> Callable[..., DiscoveredFile]:
    def _make(path: str, **overrides: object) -> DiscoveredFile:
        now = datetime.now(UTC)
        defaults: dict[str, object] = {
            "path": Path(path),
            "size_bytes": 10,
            "created_at": now,
            "modified_at": now,
            "sha256": "a" * 64,
        }
        defaults.update(overrides)
        return DiscoveredFile(**defaults)

    return _make


@pytest.fixture
def make_proposal() -> Callable[..., FileProposal]:
    """Builds a FileProposal directly, independent of ProposalEngine.

    Lets tests construct category/destination_category combinations FA-006
    would never itself produce (e.g. OTHER + DOCUMENTS) -- exactly the
    hand-constructed/hypothetical inputs the FA-007 default-deny allowlist
    must defend against.
    """

    def _make(**overrides: object) -> FileProposal:
        now = datetime.now(UTC)
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
            "created_at": now,
            "proposal_engine_id": "rules-v1",
            "expected_size": 10,
            "expected_created_at": now,
            "expected_modified_at": now,
            "sha256": "a" * 64,
        }
        defaults.update(overrides)
        return FileProposal(**defaults)

    return _make


@pytest.fixture
def fixed_clock() -> Callable[[], datetime]:
    """A clock that always returns the same fixed UTC timestamp.

    Used to prove full-result determinism (including `evaluated_at`): two
    independent PolicyEngine instances that share this clock and evaluate
    the same FileProposal must produce an identical PolicyDecision.
    """
    fixed_time = datetime(2026, 1, 1, tzinfo=UTC)

    def clock() -> datetime:
        return fixed_time

    return clock
