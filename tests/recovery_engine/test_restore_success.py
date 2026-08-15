"""RESTORE_FROM_VAULT: successful restore, Vault unchanged after, reserved
restore-temp naming convention honored."""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from file_agent.domain import (
    RecoveryResult,
    RecoveryStatus,
    RestoreFromVaultRequest,
    VaultCaptureEvidence,
    VaultCaptureRequest,
    VaultCaptureStatus,
)
from file_agent.persistence import AppPaths
from file_agent.recovery_engine import RecoveryEngine
from file_agent.reserved_artifacts import is_file_agent_internal_artifact
from file_agent.scanner import SandboxRoot
from file_agent.vault_engine import VaultEngine
from file_agent.vault_engine.paths import object_abs_path


def _capture(
    sandbox_root: SandboxRoot, app_paths: AppPaths, source: Path, content: bytes
) -> str:
    st = source.stat()
    request = VaultCaptureRequest(
        file_id=uuid4(),
        source_path=source,
        expected_size=st.st_size,
        expected_created_at=datetime.fromtimestamp(st.st_ctime, tz=UTC),
        expected_modified_at=datetime.fromtimestamp(st.st_mtime, tz=UTC),
        expected_sha256=hashlib.sha256(content).hexdigest(),
    )
    result = VaultEngine(sandbox_root, app_paths).capture(request)
    assert result.status is VaultCaptureStatus.CAPTURED
    assert result.verified_sha256 is not None
    return result.verified_sha256


def test_successful_restore_recreates_target_byte_identically(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_vault_evidence: Callable[..., VaultCaptureEvidence],
    make_restore_request: Callable[..., RestoreFromVaultRequest],
    prepare_and_commit: Callable[..., RecoveryResult],
) -> None:
    content = b"vault-backed content"
    source = make_source_file("Documents/report.txt", content=content)
    sha = _capture(sandbox_root, app_paths, source, content)
    source.unlink()  # simulate the original file being gone -- restore recreates it

    evidence = make_vault_evidence(source_path=source, content=content)
    assert evidence.verified_sha256 == sha
    request = make_restore_request(evidence)

    vault_object_before = object_abs_path(app_paths, sha).read_bytes()

    result = prepare_and_commit(RecoveryEngine(sandbox_root, app_paths), request)

    assert result.status is RecoveryStatus.SUCCEEDED
    assert result.verified_sha256 == sha
    assert result.destination_path == source
    assert result.source_path is None
    assert source.read_bytes() == content
    assert (
        object_abs_path(app_paths, sha).read_bytes() == vault_object_before
    )  # Vault unchanged


def test_no_stray_restore_temp_left_after_success(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_vault_evidence: Callable[..., VaultCaptureEvidence],
    make_restore_request: Callable[..., RestoreFromVaultRequest],
    prepare_and_commit: Callable[..., RecoveryResult],
) -> None:
    content = b"clean up via rename, not delete"
    source = make_source_file("Documents/report.txt", content=content)
    _capture(sandbox_root, app_paths, source, content)
    source.unlink()

    evidence = make_vault_evidence(source_path=source, content=content)
    request = make_restore_request(evidence)

    prepare_and_commit(RecoveryEngine(sandbox_root, app_paths), request)

    remaining = [
        entry.name
        for entry in source.parent.iterdir()
        if is_file_agent_internal_artifact(entry.name)
    ]
    assert remaining == []
