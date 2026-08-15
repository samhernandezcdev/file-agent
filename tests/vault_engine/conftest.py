"""Shared fixtures for vault_engine tests.

Uses real files under a real sandbox and a real, disjoint app-data root
(tmp_path), matching this codebase's established convention for
filesystem-sensitive behavior -- mocks are avoided entirely, since the whole
point of this package is verified filesystem interaction.
"""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from file_agent.domain import VaultCaptureRequest
from file_agent.persistence import AppPaths
from file_agent.scanner import SandboxRoot


@pytest.fixture
def sandbox_root(tmp_path: Path) -> SandboxRoot:
    root = tmp_path / "sandbox"
    root.mkdir()
    return SandboxRoot.from_path(root)


@pytest.fixture
def app_paths(tmp_path: Path) -> AppPaths:
    # Sibling of "sandbox" under tmp_path -- disjoint from sandbox_root, but
    # deliberately NOT nested under it or vice versa.
    root = tmp_path / "appdata"
    return AppPaths.from_root(root)


@pytest.fixture
def make_source_file(sandbox_root: SandboxRoot) -> Callable[..., Path]:
    def _make(name: str = "report.txt", content: bytes = b"hello world") -> Path:
        path = sandbox_root.path / name
        path.write_bytes(content)
        return path

    return _make


def sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def make_request() -> Callable[..., VaultCaptureRequest]:
    def _make(
        source_path: Path,
        *,
        content: bytes = b"hello world",
        file_id: UUID | None = None,
        **overrides: object,
    ) -> VaultCaptureRequest:
        st = source_path.stat()
        defaults: dict[str, object] = {
            "file_id": file_id or uuid4(),
            "source_path": source_path,
            "expected_size": st.st_size,
            "expected_created_at": datetime.fromtimestamp(st.st_ctime, tz=UTC),
            "expected_modified_at": datetime.fromtimestamp(st.st_mtime, tz=UTC),
            "expected_sha256": sha256_of(content),
        }
        defaults.update(overrides)
        return VaultCaptureRequest(**defaults)

    return _make
