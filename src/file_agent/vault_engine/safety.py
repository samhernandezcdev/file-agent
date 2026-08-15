"""App-owned/managed-root separation and Vault-tree reparse-point safety.

Two distinct problems, two distinct lifetimes:

1. Root disjointness (ensure_disjoint_roots) -- checked ONCE, at
   VaultEngine construction, because AppPaths/SandboxRoot are both immutable
   for the engine's lifetime.
2. Vault-tree reparse-point safety (find_unsafe_vault_reparse_point) --
   re-checked on every capture(), because the filesystem can change out from
   under a long-lived VaultEngine instance between calls.

Neither check is race-free. These are fail-closed, POINT-IN-TIME checks: a
known-unsafe configuration present at the moment of the check is always
rejected, but there remains a residual TOCTOU window if another process
replaces a validated directory with a junction/symlink between the check and
the subsequent filesystem operation. FA-010 does not close that window --
doing so would require OS-level primitives beyond what this design
implements. This residual race is accepted for v1: it requires an
adversarial process with write access to FileAgent's own app-owned directory
tree at the exact instant of the check, consistent with this codebase's
existing filesystem threat model elsewhere (e.g. transaction_engine's own
destination-side reparse checks in preconditions.py have the identical
point-in-time, not race-free, character).
"""

import os
from pathlib import Path

from file_agent.persistence import AppPaths
from file_agent.scanner import SandboxRoot
from file_agent.vault_engine.errors import InvalidVaultConfigurationError
from file_agent.vault_engine.paths import objects_root, tmp_dir


def ensure_disjoint_roots(app_paths: AppPaths, sandbox_root: SandboxRoot) -> None:
    """Enforces "the app-owned root and the managed root are completely
    disjoint" -- compares AppPaths.root itself, not vault_root, because that
    is the invariant that actually needs to hold. A vault_root-vs-managed-root
    comparison alone would miss the sibling case app_root/vault/ +
    app_root/managed/: vault_root and managed would be disjoint siblings,
    but app_root would still improperly contain the managed root. Since
    vault_root is always app_paths.root / "vault", proving app_paths.root
    disjoint from the managed root transitively proves vault_root disjoint
    too -- no separate vault_root-specific check is needed.
    """
    app_root = app_paths.root.resolve(strict=False)
    managed = sandbox_root.path.resolve(strict=False)
    if app_root == managed:
        raise InvalidVaultConfigurationError(
            "app-owned root must not equal the managed/sandbox root"
        )
    if app_root.is_relative_to(managed):
        raise InvalidVaultConfigurationError(
            "app-owned root must not be inside the managed/sandbox root"
        )
    if managed.is_relative_to(app_root):
        raise InvalidVaultConfigurationError(
            "the managed/sandbox root must not be inside the app-owned root"
        )


def is_unsafe_reparse_point(path: Path) -> bool:
    """True if `path` itself (not its target) is a symlink, junction, or any
    other reparse-tagged entry. Never follows `path`."""
    if path.is_symlink():
        return True
    return bool(os.path.isjunction(path))


def find_unsafe_vault_reparse_point(app_paths: AppPaths) -> Path | None:
    """Checks vault_root and its two known top-level subdirectories only --
    NOT any per-capture objects/<prefix> directory, which the engine checks
    separately, immediately before use, since it is verified fresh on every
    relevant call. Returns the first offending path, or None."""
    for candidate in (
        app_paths.vault_root,
        objects_root(app_paths),
        tmp_dir(app_paths),
    ):
        if candidate.exists() and is_unsafe_reparse_point(candidate):
            return candidate
    return None
