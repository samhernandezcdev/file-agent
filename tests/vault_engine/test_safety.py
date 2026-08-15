"""App-owned/managed-root separation and Vault-tree reparse-point safety.
Construction-time (root disjointness, pre-existing unsafe vault tree) and
per-capture (a specific prefix directory swapped for a reparse point) are
tested separately here -- see engine.py/safety.py for why they have
different lifetimes."""

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from file_agent.domain import (
    VaultCaptureRequest,
    VaultCaptureStatus,
    VaultRejectionCode,
)
from file_agent.persistence import AppPaths
from file_agent.scanner import SandboxRoot
from file_agent.vault_engine import InvalidVaultConfigurationError, VaultEngine
from file_agent.vault_engine.safety import ensure_disjoint_roots


def _make_junction(link: Path, target: Path) -> None:
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
    )


def test_equal_roots_rejected(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    sandbox_root = SandboxRoot.from_path(shared)
    app_paths = AppPaths.from_root(shared)

    with pytest.raises(InvalidVaultConfigurationError):
        ensure_disjoint_roots(app_paths, sandbox_root)
    with pytest.raises(InvalidVaultConfigurationError):
        VaultEngine(sandbox_root, app_paths)


def test_app_root_inside_managed_root_rejected(tmp_path: Path) -> None:
    managed = tmp_path / "managed"
    managed.mkdir()
    app_root = managed / "appdata"
    sandbox_root = SandboxRoot.from_path(managed)
    app_paths = AppPaths.from_root(app_root)

    with pytest.raises(InvalidVaultConfigurationError):
        ensure_disjoint_roots(app_paths, sandbox_root)
    with pytest.raises(InvalidVaultConfigurationError):
        VaultEngine(sandbox_root, app_paths)


def test_managed_root_inside_app_root_rejected(tmp_path: Path) -> None:
    app_root = tmp_path / "appdata"
    app_root.mkdir()
    managed = app_root / "managed"
    managed.mkdir()
    sandbox_root = SandboxRoot.from_path(managed)
    app_paths = AppPaths.from_root(app_root)

    with pytest.raises(InvalidVaultConfigurationError):
        ensure_disjoint_roots(app_paths, sandbox_root)
    with pytest.raises(InvalidVaultConfigurationError):
        VaultEngine(sandbox_root, app_paths)


def test_sibling_vault_and_managed_under_shared_app_root_rejected(
    tmp_path: Path,
) -> None:
    """app_root/vault/ and app_root/managed/ are themselves disjoint
    siblings -- a vault_root-vs-managed-root-only comparison would wrongly
    accept this. app_paths.root still improperly CONTAINS the managed root,
    which is what must be rejected (round-2 correction)."""
    app_root = tmp_path / "app_root"
    managed = app_root / "managed"
    managed.mkdir(parents=True)
    sandbox_root = SandboxRoot.from_path(managed)
    app_paths = AppPaths.from_root(app_root)

    assert not app_paths.vault_root.exists()  # not yet bootstrapped
    with pytest.raises(InvalidVaultConfigurationError):
        ensure_disjoint_roots(app_paths, sandbox_root)
    with pytest.raises(InvalidVaultConfigurationError):
        VaultEngine(sandbox_root, app_paths)


def test_disjoint_sibling_roots_are_accepted(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    app_root = tmp_path / "appdata"
    sandbox_root = SandboxRoot.from_path(sandbox)
    app_paths = AppPaths.from_root(app_root)

    ensure_disjoint_roots(app_paths, sandbox_root)  # does not raise
    VaultEngine(sandbox_root, app_paths)  # does not raise


def test_bootstrap_rejects_vault_root_preexisting_as_junction(
    tmp_path: Path, sandbox_root: SandboxRoot
) -> None:
    app_root = tmp_path / "appdata"
    app_root.mkdir()
    escape_target = tmp_path / "escape_target"
    escape_target.mkdir()
    app_paths = AppPaths.from_root(app_root)
    _make_junction(app_paths.vault_root, escape_target)

    with pytest.raises(InvalidVaultConfigurationError):
        VaultEngine(sandbox_root, app_paths)
    assert list(escape_target.iterdir()) == []


def test_per_capture_prefix_dir_reparse_point_is_rejected_not_raised(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., VaultCaptureRequest],
    tmp_path: Path,
) -> None:
    """Distinguishes the per-capture case (REJECTED result, no exception)
    from the bootstrap case (raises) -- see engine.py's _capture and
    errors.py's InvalidVaultConfigurationError docstring."""
    source = make_source_file("report.txt", content=b"escape me")
    request = make_request(source, content=b"escape me")
    engine = VaultEngine(sandbox_root, app_paths)

    from file_agent.vault_engine.paths import object_prefix_dir

    prefix_dir = object_prefix_dir(app_paths, request.expected_sha256)
    escape_target = tmp_path / "escape_target"
    escape_target.mkdir()
    _make_junction(prefix_dir, escape_target)

    result = engine.capture(request)

    assert result.status is VaultCaptureStatus.REJECTED
    assert result.rejection_code is VaultRejectionCode.VAULT_STORAGE_UNSAFE
    assert list(escape_target.iterdir()) == []
