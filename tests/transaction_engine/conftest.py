"""Shared fixtures for transaction_engine tests.

Uses real files under a real sandbox (tmp_path), matching this codebase's
established convention for filesystem-sensitive behavior (see AGENTS.md
testing expectations) -- mocks are avoided here entirely, since the whole
point of this package is verified filesystem interaction.
"""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from file_agent.destination import PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY
from file_agent.domain import (
    DestinationCategory,
    ExecutionAuthorization,
    FileCategory,
    PolicyDecision,
    PolicyOutcome,
    TransactionRequest,
    TransactionResult,
)
from file_agent.scanner import SandboxRoot
from file_agent.transaction_engine import TransactionEngine


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


def sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def make_request(sandbox_root: SandboxRoot) -> Callable[..., TransactionRequest]:
    def _make(
        source_path: Path,
        *,
        content: bytes = b"hello world",
        destination_category: DestinationCategory = DestinationCategory.DOCUMENTS,
        destination_path: Path | None = None,
        file_id: UUID | None = None,
        proposal_id: UUID | None = None,
        policy_decision_id: UUID | None = None,
        **overrides: object,
    ) -> TransactionRequest:
        st = source_path.stat()
        if destination_path is None:
            physical_dir = PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY[
                destination_category
            ]
            destination_path = sandbox_root.path / physical_dir / source_path.name
        defaults: dict[str, object] = {
            "file_id": file_id or uuid4(),
            "proposal_id": proposal_id or uuid4(),
            "policy_decision_id": policy_decision_id or uuid4(),
            "source_path": source_path,
            "destination_path": destination_path,
            "destination_category": destination_category,
            "expected_size": st.st_size,
            "expected_created_at": datetime.fromtimestamp(st.st_ctime, tz=UTC),
            "expected_modified_at": datetime.fromtimestamp(st.st_mtime, tz=UTC),
            "expected_sha256": sha256_of(content),
        }
        defaults.update(overrides)
        return TransactionRequest(**defaults)

    return _make


@pytest.fixture
def make_policy_decision() -> Callable[..., PolicyDecision]:
    def _make(request: TransactionRequest, **overrides: object) -> PolicyDecision:
        defaults: dict[str, object] = {
            "id": request.policy_decision_id,
            "proposal_id": request.proposal_id,
            "file_id": request.file_id,
            "decision": PolicyOutcome.AUTO,
            "reasons": ("stub reason",),
            "policy_engine_id": "v1",
            "source_category": FileCategory.DOCUMENT,
            "destination_category": request.destination_category,
            "proposal_confidence": 1.0,
            "proposal_engine_id": "rules-v1",
        }
        defaults.update(overrides)
        return PolicyDecision(**defaults)

    return _make


@pytest.fixture
def make_authorization() -> Callable[[PolicyDecision], ExecutionAuthorization]:
    """AUTO-only convenience wrapper -- most transaction_engine tests only
    care about the precondition chain downstream of a genuine authorization,
    not about which of the two authorization kinds produced it. Tests that
    specifically exercise HUMAN_APPROVED build it directly via
    ExecutionAuthorization.from_human_approval."""

    def _make(policy_decision: PolicyDecision) -> ExecutionAuthorization:
        return ExecutionAuthorization.from_policy_auto(policy_decision)

    return _make


@pytest.fixture
def prepare_and_commit() -> Callable[
    [TransactionEngine, TransactionRequest, ExecutionAuthorization], TransactionResult
]:
    """Runs prepare() then commit(), asserting prepare() actually succeeded
    (returned something other than a REJECTED TransactionResult) --
    convenience for tests whose focus is the commit-time outcome, not the
    precondition chain itself."""

    def _run(
        engine: TransactionEngine,
        request: TransactionRequest,
        authorization: ExecutionAuthorization,
    ) -> TransactionResult:
        prepared = engine.prepare(request, authorization)
        assert not isinstance(prepared, TransactionResult), (
            f"expected prepare() to succeed, got REJECTED: {prepared}"
        )
        return engine.commit(prepared)

    return _run
