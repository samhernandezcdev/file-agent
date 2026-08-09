"""Shared fixtures for hasher tests."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from file_agent.domain import DiscoveredFile
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


@pytest.fixture
def discovered_file_factory() -> Callable[[Path], DiscoveredFile]:
    """Build a DiscoveredFile whose recorded metadata matches `path`'s current real stat."""

    def _make(path: Path) -> DiscoveredFile:
        st = path.stat()
        return DiscoveredFile(
            path=path,
            size_bytes=st.st_size,
            created_at=datetime.fromtimestamp(st.st_ctime, tz=UTC),
            modified_at=datetime.fromtimestamp(st.st_mtime, tz=UTC),
        )

    return _make
