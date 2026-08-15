"""RESTORE_FROM_VAULT rejections: VaultObject missing/corrupted, target
occupied/outside sandbox/parent missing/reparse escape."""

import hashlib
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from file_agent.domain import (
    RecoveryRejectionCode,
    RecoveryResult,
    RecoveryStatus,
    RestoreFromVaultRequest,
    VaultCaptureEvidence,
    VaultCaptureRequest,
    VaultCaptureStatus,
)
from file_agent.persistence import AppPaths
from file_agent.recovery_engine import RecoveryEngine
from file_agent.scanner import SandboxRoot
from file_agent.vault_engine import VaultEngine
from file_agent.vault_engine.paths import object_abs_path


def _make_junction(link: Path, target: Path) -> None:
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
    )


def test_vault_object_not_found_is_rejected(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_vault_evidence: Callable[..., VaultCaptureEvidence],
    make_restore_request: Callable[..., RestoreFromVaultRequest],
) -> None:
    target = sandbox_root.path / "report.txt"
    evidence = make_vault_evidence(source_path=target, content=b"never captured")
    request = make_restore_request(evidence)

    result = RecoveryEngine(sandbox_root, app_paths).prepare(request)

    assert isinstance(result, RecoveryResult)
    assert result.status is RecoveryStatus.REJECTED
    assert result.rejection_code is RecoveryRejectionCode.VAULT_OBJECT_NOT_FOUND
    assert not target.exists()


def test_vault_object_corrupted_is_rejected(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_vault_evidence: Callable[..., VaultCaptureEvidence],
    make_restore_request: Callable[..., RestoreFromVaultRequest],
) -> None:
    target = sandbox_root.path / "report.txt"
    content = b"claimed content"
    evidence = make_vault_evidence(source_path=target, content=content)
    corrupted_path = object_abs_path(app_paths, evidence.verified_sha256)
    corrupted_path.parent.mkdir(parents=True)
    corrupted_path.write_bytes(b"this is not the claimed content at all")
    request = make_restore_request(evidence)

    result = RecoveryEngine(sandbox_root, app_paths).prepare(request)

    assert isinstance(result, RecoveryResult)
    assert result.status is RecoveryStatus.REJECTED
    assert result.rejection_code is RecoveryRejectionCode.VAULT_OBJECT_CORRUPTED
    assert corrupted_path.read_bytes() == b"this is not the claimed content at all"
    assert not target.exists()


def test_vault_storage_unsafe_is_rejected(
    tmp_path: Path,
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_vault_evidence: Callable[..., VaultCaptureEvidence],
    make_restore_request: Callable[..., RestoreFromVaultRequest],
) -> None:
    target = sandbox_root.path / "report.txt"
    evidence = make_vault_evidence(source_path=target, content=b"x")
    request = make_restore_request(evidence)

    escape_target = tmp_path / "escape"
    escape_target.mkdir()
    app_paths.root.mkdir(parents=True)
    _make_junction(app_paths.vault_root, escape_target)

    result = RecoveryEngine(sandbox_root, app_paths).prepare(request)

    assert isinstance(result, RecoveryResult)
    assert result.status is RecoveryStatus.REJECTED
    assert result.rejection_code is RecoveryRejectionCode.VAULT_STORAGE_UNSAFE
    assert list(escape_target.iterdir()) == []


def test_target_path_occupied_is_rejected(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_vault_evidence: Callable[..., VaultCaptureEvidence],
    make_restore_request: Callable[..., RestoreFromVaultRequest],
) -> None:
    target = make_source_file("report.txt", content=b"already here")
    evidence = make_vault_evidence(source_path=target, content=b"vault content")
    request = make_restore_request(evidence)

    result = RecoveryEngine(sandbox_root, app_paths).prepare(request)

    assert isinstance(result, RecoveryResult)
    assert result.status is RecoveryStatus.REJECTED
    assert result.rejection_code is RecoveryRejectionCode.TARGET_PATH_OCCUPIED
    assert target.read_bytes() == b"already here"


def test_target_path_outside_sandbox_is_rejected(
    tmp_path: Path,
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_vault_evidence: Callable[..., VaultCaptureEvidence],
    make_restore_request: Callable[..., RestoreFromVaultRequest],
) -> None:
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    target = outside_dir / "report.txt"
    evidence = make_vault_evidence(source_path=target, content=b"x")
    request = make_restore_request(evidence)

    result = RecoveryEngine(sandbox_root, app_paths).prepare(request)

    assert isinstance(result, RecoveryResult)
    assert result.status is RecoveryStatus.REJECTED
    assert result.rejection_code is RecoveryRejectionCode.TARGET_PATH_OUTSIDE_SANDBOX
    assert not target.exists()


def test_target_parent_missing_is_rejected(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_vault_evidence: Callable[..., VaultCaptureEvidence],
    make_restore_request: Callable[..., RestoreFromVaultRequest],
) -> None:
    target = sandbox_root.path / "NoSuchDir" / "report.txt"
    evidence = make_vault_evidence(source_path=target, content=b"x")
    request = make_restore_request(evidence)

    result = RecoveryEngine(sandbox_root, app_paths).prepare(request)

    assert isinstance(result, RecoveryResult)
    assert result.status is RecoveryStatus.REJECTED
    assert result.rejection_code is RecoveryRejectionCode.TARGET_PARENT_MISSING


def test_target_parent_replaced_by_escaping_junction_is_rejected(
    tmp_path: Path,
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_vault_evidence: Callable[..., VaultCaptureEvidence],
    make_restore_request: Callable[..., RestoreFromVaultRequest],
) -> None:
    outside_target = tmp_path / "outside_docs"
    outside_target.mkdir()
    target_dir = sandbox_root.path / "TargetDir"
    _make_junction(target_dir, outside_target)
    target = target_dir / "report.txt"

    evidence = make_vault_evidence(source_path=target, content=b"x")
    request = make_restore_request(evidence)

    result = RecoveryEngine(sandbox_root, app_paths).prepare(request)

    assert isinstance(result, RecoveryResult)
    assert result.status is RecoveryStatus.REJECTED
    assert result.rejection_code in (
        RecoveryRejectionCode.TARGET_PATH_OUTSIDE_SANDBOX,
        RecoveryRejectionCode.TARGET_PATH_UNSAFE_REPARSE_POINT,
    )
    assert not (outside_target / "report.txt").exists()


def test_retry_after_successful_restore_rejects_rather_than_duplicates(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_vault_evidence: Callable[..., VaultCaptureEvidence],
    make_restore_request: Callable[..., RestoreFromVaultRequest],
    prepare_and_commit: Callable[..., RecoveryResult],
) -> None:
    content = b"restore then retry"
    source = make_source_file("report.txt", content=content)

    st = source.stat()
    capture_request = VaultCaptureRequest(
        file_id=uuid4(),
        source_path=source,
        expected_size=st.st_size,
        expected_created_at=datetime.fromtimestamp(st.st_ctime, tz=UTC),
        expected_modified_at=datetime.fromtimestamp(st.st_mtime, tz=UTC),
        expected_sha256=hashlib.sha256(content).hexdigest(),
    )
    capture_result = VaultEngine(sandbox_root, app_paths).capture(capture_request)
    assert capture_result.status is VaultCaptureStatus.CAPTURED
    source.unlink()

    evidence = make_vault_evidence(source_path=source, content=content)
    request = make_restore_request(evidence)
    engine = RecoveryEngine(sandbox_root, app_paths)

    first = prepare_and_commit(engine, request)
    assert first.status is RecoveryStatus.SUCCEEDED

    retry_request = make_restore_request(evidence)
    second = engine.prepare(retry_request)

    assert isinstance(second, RecoveryResult)
    assert second.status is RecoveryStatus.REJECTED
    assert second.rejection_code is RecoveryRejectionCode.TARGET_PATH_OCCUPIED
    assert source.read_bytes() == content  # untouched by the retry
