"""Shared fixtures for scanner tests."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from file_agent.scanner import SandboxRoot


@pytest.fixture
def sandbox_dir(tmp_path: Path) -> Path:
    root = tmp_path / "sandbox"
    root.mkdir()
    return root


@pytest.fixture
def sandbox_root(sandbox_dir: Path) -> SandboxRoot:
    return SandboxRoot.from_path(sandbox_dir)


@pytest.fixture
def fixed_clock() -> Callable[[], datetime]:
    """A monotonically-advancing fake clock for deterministic timestamp tests."""
    state = {"now": datetime(2026, 1, 1, tzinfo=UTC)}

    def clock() -> datetime:
        state["now"] += timedelta(seconds=1)
        return state["now"]

    return clock
