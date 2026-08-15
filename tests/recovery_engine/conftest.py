"""Shared fixtures for recovery_engine tests.

Uses real files under a real sandbox and a real, disjoint app-data root
(tmp_path), matching this codebase's established convention -- mocks are
avoided entirely since the whole point of this package is verified
filesystem interaction.
"""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from file_agent.domain import (
    CompletedMoveEvidence,
    RecoveryRequest,
    RecoveryResult,
    RestoreFromVaultRequest,
    ReverseMoveRequest,
    VaultCaptureEvidence,
)
from file_agent.persistence import AppPaths
from file_agent.recovery_engine import RecoveryEngine
from file_agent.scanner import SandboxRoot


@pytest.fixture
def sandbox_root(tmp_path: Path) -> SandboxRoot:
    root = tmp_path / "sandbox"
    root.mkdir()
    return SandboxRoot.from_path(root)


@pytest.fixture
def app_paths(tmp_path: Path) -> AppPaths:
    return AppPaths.from_root(tmp_path / "appdata")


@pytest.fixture
def make_source_file(sandbox_root: SandboxRoot) -> Callable[..., Path]:
    def _make(name: str = "report.txt", content: bytes = b"hello world") -> Path:
        path = sandbox_root.path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    return _make


def sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def make_move_evidence() -> Callable[..., CompletedMoveEvidence]:
    def _make(
        *,
        source_path: Path,
        destination_path: Path,
        content: bytes = b"hello world",
        file_id: UUID | None = None,
        original_transaction_id: UUID | None = None,
    ) -> CompletedMoveEvidence:
        return CompletedMoveEvidence(
            original_transaction_id=original_transaction_id or uuid4(),
            file_id=file_id or uuid4(),
            source_path=source_path,
            destination_path=destination_path,
            verified_sha256=sha256_of(content),
        )

    return _make


@pytest.fixture
def make_reverse_move_request() -> Callable[..., ReverseMoveRequest]:
    def _make(
        evidence: CompletedMoveEvidence,
        *,
        current_path: Path,
        **overrides: object,
    ) -> ReverseMoveRequest:
        st = current_path.stat()
        defaults: dict[str, object] = {
            "evidence": evidence,
            "expected_size": st.st_size,
            "expected_created_at": datetime.fromtimestamp(st.st_ctime, tz=UTC),
            "expected_modified_at": datetime.fromtimestamp(st.st_mtime, tz=UTC),
        }
        defaults.update(overrides)
        return ReverseMoveRequest(**defaults)

    return _make


@pytest.fixture
def make_vault_evidence() -> Callable[..., VaultCaptureEvidence]:
    def _make(
        *,
        source_path: Path,
        content: bytes = b"hello world",
        file_id: UUID | None = None,
    ) -> VaultCaptureEvidence:
        return VaultCaptureEvidence(
            file_id=file_id or uuid4(),
            source_path=source_path,
            verified_sha256=sha256_of(content),
        )

    return _make


@pytest.fixture
def make_restore_request() -> Callable[..., RestoreFromVaultRequest]:
    def _make(
        evidence: VaultCaptureEvidence, **overrides: object
    ) -> RestoreFromVaultRequest:
        defaults: dict[str, object] = {"evidence": evidence}
        defaults.update(overrides)
        return RestoreFromVaultRequest(**defaults)

    return _make


@pytest.fixture
def prepare_and_commit() -> Callable[[RecoveryEngine, RecoveryRequest], RecoveryResult]:
    """Runs prepare() then commit(), asserting prepare() actually succeeded
    (returned something other than a REJECTED RecoveryResult) -- convenience
    for tests whose focus is the commit-time outcome, not the precondition
    chain itself."""

    def _run(engine: RecoveryEngine, request: RecoveryRequest) -> RecoveryResult:
        prepared = engine.prepare(request)
        assert not isinstance(prepared, RecoveryResult), (
            f"expected prepare() to succeed, got REJECTED: {prepared}"
        )
        return engine.commit(prepared)

    return _run
