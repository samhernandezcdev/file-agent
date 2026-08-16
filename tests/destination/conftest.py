"""Shared fixtures for destination package tests."""

from collections.abc import Callable
from pathlib import Path

import pytest

from file_agent.destination import PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY
from file_agent.scanner import SandboxRoot


@pytest.fixture
def sandbox_root(tmp_path: Path) -> SandboxRoot:
    root = tmp_path / "sandbox"
    root.mkdir()
    for directory in PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY.values():
        (root / directory).mkdir()
    return SandboxRoot.from_path(root)


@pytest.fixture
def make_source_file(sandbox_root: SandboxRoot) -> Callable[..., Path]:
    def _make(name: str = "report.txt", content: bytes = b"hello world") -> Path:
        path = sandbox_root.path / name
        path.write_bytes(content)
        return path

    return _make
