"""Vault directory bootstrap and creation -- the package's mkdir call site(s).

ensure_directory() is also the per-use, immediately-before-write reparse
check for a specific directory (e.g. an objects/<prefix> fan-out directory)
that ensure_vault_layout()'s bootstrap sweep does not cover -- see
safety.py's module docstring for what this check does and does not
guarantee.
"""

from pathlib import Path

from file_agent.persistence import AppPaths
from file_agent.scanner import SandboxRoot
from file_agent.vault_engine.errors import InvalidVaultConfigurationError
from file_agent.vault_engine.paths import objects_root, tmp_dir
from file_agent.vault_engine.safety import (
    ensure_disjoint_roots,
    find_unsafe_vault_reparse_point,
    is_unsafe_reparse_point,
)


def ensure_directory(path: Path) -> None:
    """Creates `path` if it doesn't exist. If it already exists, refuses to
    use it when it is a reparse point -- raises InvalidVaultConfigurationError
    rather than silently writing through a symlink/junction. Point-in-time
    only; see safety.py's module docstring."""
    if path.exists():
        if is_unsafe_reparse_point(path):
            raise InvalidVaultConfigurationError(
                f"vault directory is a reparse point: {path}"
            )
        return
    path.mkdir(parents=True, exist_ok=True)


def ensure_vault_layout(app_paths: AppPaths, sandbox_root: SandboxRoot) -> None:
    """Bootstrap, called once from VaultEngine.__init__. Order matters: root
    disjointness is proven before anything under vault_root is even
    inspected, then the vault tree itself is checked for pre-existing unsafe
    reparse points before any directory is created."""
    ensure_disjoint_roots(app_paths, sandbox_root)
    offender = find_unsafe_vault_reparse_point(app_paths)
    if offender is not None:
        raise InvalidVaultConfigurationError(
            f"vault directory is a reparse point: {offender}"
        )
    ensure_directory(app_paths.vault_root)
    ensure_directory(objects_root(app_paths))
    ensure_directory(tmp_dir(app_paths))
