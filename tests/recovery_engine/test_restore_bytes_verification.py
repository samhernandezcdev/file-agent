"""RESTORE_FROM_VAULT: post-close rehash-from-disk verification (not the
write-time digest), and the "no cleanup primitive" rule -- a hash mismatch
or a failed write/read after temp creation leaves the reserved
.file_agent_restore.* artifact in place; recovery_engine never unlinks
anything."""

import ast
from collections.abc import Callable
from pathlib import Path

from file_agent.domain import (
    RecoveryRejectionCode,
    RecoveryResult,
    RecoveryStatus,
    RestoreFromVaultRequest,
    VaultCaptureEvidence,
)
from file_agent.persistence import AppPaths
from file_agent.recovery_engine import RecoveryEngine
from file_agent.reserved_artifacts import is_file_agent_internal_artifact
from file_agent.scanner import SandboxRoot
from file_agent.vault_engine.paths import object_abs_path

from .test_restore_success import _capture

RECOVERY_ENGINE_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "file_agent" / "recovery_engine"
)


def _partials(directory: Path) -> list[str]:
    return [
        p.name for p in directory.iterdir() if is_file_agent_internal_artifact(p.name)
    ]


def test_hash_mismatch_between_prepare_and_commit_leaves_partial_artifact(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_vault_evidence: Callable[..., VaultCaptureEvidence],
    make_restore_request: Callable[..., RestoreFromVaultRequest],
) -> None:
    content = b"verified at prepare time"
    source = make_source_file("report.txt", content=content)
    _capture(sandbox_root, app_paths, source, content)
    source.unlink()

    evidence = make_vault_evidence(source_path=source, content=content)
    request = make_restore_request(evidence)
    engine = RecoveryEngine(sandbox_root, app_paths)

    prepared = engine.prepare(request)
    assert not isinstance(prepared, RecoveryResult)

    # Simulate the vault object changing between prepare()'s verification
    # and commit()'s copy -- the accepted, documented residual TOCTOU.
    vault_object_path = object_abs_path(app_paths, evidence.verified_sha256)
    vault_object_path.write_bytes(b"corrupted between prepare and commit")

    result = engine.commit(prepared)

    assert result.status is RecoveryStatus.REJECTED
    assert result.rejection_code is RecoveryRejectionCode.RESTORED_BYTES_HASH_MISMATCH
    assert result.started_at is not None
    assert result.completed_at is not None
    assert not source.exists()  # never published

    partials = _partials(source.parent)
    assert len(partials) == 1, (
        f"expected exactly one reserved partial, found {partials}"
    )


def test_read_failure_after_temp_creation_leaves_partial_and_returns_failed(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_vault_evidence: Callable[..., VaultCaptureEvidence],
    make_restore_request: Callable[..., RestoreFromVaultRequest],
) -> None:
    content = b"vault object removed mid-flight"
    source = make_source_file("report.txt", content=content)
    _capture(sandbox_root, app_paths, source, content)
    source.unlink()

    evidence = make_vault_evidence(source_path=source, content=content)
    request = make_restore_request(evidence)
    engine = RecoveryEngine(sandbox_root, app_paths)

    prepared = engine.prepare(request)
    assert not isinstance(prepared, RecoveryResult)

    # Force a read failure mid-copy, AFTER the exclusive-create temp file
    # already exists.
    object_abs_path(app_paths, evidence.verified_sha256).unlink()

    result = engine.commit(prepared)

    assert result.status is RecoveryStatus.FAILED
    assert result.failure_reason is not None
    assert "stage write failed" in result.failure_reason
    assert not source.exists()

    partials = _partials(source.parent)
    assert len(partials) == 1, (
        f"expected exactly one stale reserved partial, found {partials}"
    )


def test_recovery_engine_never_unlinks_anything() -> None:
    """recovery_engine has no delete/unlink/cleanup primitive of any kind --
    managed_fs stays limited to move_no_replace/write_new_file. AST scan,
    not a literal string grep, so it also catches os.remove/os.unlink."""
    forbidden_dotted = {("os", "remove"), ("os", "unlink"), ("shutil", "rmtree")}
    forbidden_methods = {"unlink", "rmdir"}

    def _dotted_name(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = _dotted_name(node.value)
            return f"{base}.{node.attr}" if base else None
        return None

    offenders: list[str] = []
    for path in sorted(RECOVERY_ENGINE_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            dotted = _dotted_name(node.func)
            if dotted:
                parts = dotted.split(".")
                if len(parts) >= 2 and (parts[-2], parts[-1]) in forbidden_dotted:
                    offenders.append(f"{path.name}: {dotted}(")
            if node.func.attr in forbidden_methods:
                offenders.append(f"{path.name}: .{node.func.attr}(")

    assert not offenders, f"recovery_engine must never delete/unlink: {offenders}"
