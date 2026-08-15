"""The ONE shared, safety-checked definition of "a trusted Vault object" --
used by VaultEngine's own idempotency checks and by RecoveryEngine's
RESTORE_FROM_VAULT. Read-only: never writes, deletes, or repairs anything,
preserving VaultEngine's capture-only invariant.

Order matters, mirroring FileHasher's containment-before-I/O discipline:
vault-tree safety (vault_root/objects/tmp, then the specific sha-prefix
directory) is fully checked BEFORE this module ever stats or opens the
object file itself.
"""

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from file_agent.persistence import AppPaths
from file_agent.vault_engine.paths import (
    object_abs_path,
    object_prefix_dir,
    object_relative_path,
)
from file_agent.vault_engine.safety import (
    find_unsafe_vault_reparse_point,
    is_unsafe_reparse_point,
)

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


class VaultLookupStatus(str, Enum):
    NOT_FOUND = "not_found"
    CORRUPTED = "corrupted"
    UNSAFE = "unsafe"


@dataclass(frozen=True, slots=True)
class VerifiedVaultObject:
    """A Vault object freshly, fully confirmed trustworthy -- safety-checked
    AND rehashed -- at the instant this was returned. Not a durable claim;
    a caller holding this across further I/O accepts the same residual
    TOCTOU every engine in this codebase already accepts between its own
    verification step and its later use of that verification."""

    sha256: str
    abs_path: Path
    relative_path: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class VaultLookupFailure:
    status: VaultLookupStatus
    detail: Path | None = None  # which directory was unsafe, when status is UNSAFE


VaultLookupOutcome = VerifiedVaultObject | VaultLookupFailure


def rehash_vault_object(path: Path) -> str:
    """Independently rehashes an EXISTING Vault object's own bytes. Not via
    FileHasher -- FileHasher is scoped to a SandboxRoot and would reject a
    vault path as outside the sandbox by design; this is a small, separate,
    read-only helper over a vault-owned path."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def verify_vault_object(
    app_paths: AppPaths, expected_sha256: str
) -> VaultLookupOutcome:
    """The ONE shared definition of a trusted Vault object. Safety-checks
    the Vault tree (top-level, then the specific sha-prefix directory)
    before ever touching the object file; only then locates and rehashes it.
    """
    offender = find_unsafe_vault_reparse_point(app_paths)
    if offender is not None:
        return VaultLookupFailure(VaultLookupStatus.UNSAFE, detail=offender)

    prefix_dir = object_prefix_dir(app_paths, expected_sha256)
    if prefix_dir.exists() and is_unsafe_reparse_point(prefix_dir):
        return VaultLookupFailure(VaultLookupStatus.UNSAFE, detail=prefix_dir)

    abs_path = object_abs_path(app_paths, expected_sha256)
    if not abs_path.exists():
        return VaultLookupFailure(VaultLookupStatus.NOT_FOUND)

    rehashed = rehash_vault_object(abs_path)
    if rehashed != expected_sha256:
        return VaultLookupFailure(VaultLookupStatus.CORRUPTED)

    return VerifiedVaultObject(
        sha256=expected_sha256,
        abs_path=abs_path,
        relative_path=object_relative_path(expected_sha256),
        size_bytes=abs_path.stat().st_size,
    )
