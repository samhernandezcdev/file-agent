"""Shared fixtures for proposal_engine tests."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from file_agent.domain import DiscoveredFile


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
def fixed_clock() -> Callable[[], datetime]:
    """A clock that always returns the same fixed UTC timestamp.

    Used to prove full-result determinism (including `created_at`):
    proposing from the same ClassificationResult through two independent
    ProposalEngine instances that share this clock must yield an identical
    FileProposal.
    """
    fixed_time = datetime(2026, 1, 1, tzinfo=UTC)

    def clock() -> datetime:
        return fixed_time

    return clock
