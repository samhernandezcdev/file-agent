"""VaultEngine -- the sole primitive for capturing a content-addressed,
verified backup of a managed file's bytes into FileAgent's app-owned Vault.
Does not implement Undo/Restore. See docs/SAFETY.md and the FA-010 design plan.

Caller orchestration shape (this package has no persistence dependency):

    request = VaultCaptureRequest(file_id=..., source_path=..., expected_size=...,
                                   expected_created_at=..., expected_modified_at=...,
                                   expected_sha256=...)
    store.record_event(vault_capture_requested_event(request))   # checkpoint
    result = VaultEngine(sandbox_root, app_paths).capture(request)
    store.record_event(vault_capture_result_event(result))       # terminal
"""

from file_agent.vault_engine.engine import (
    VaultEngine,
    vault_capture_requested_event,
    vault_capture_result_event,
)
from file_agent.vault_engine.errors import InvalidVaultConfigurationError
from file_agent.vault_engine.lookup import (
    VaultLookupFailure,
    VaultLookupOutcome,
    VaultLookupStatus,
    VerifiedVaultObject,
    rehash_vault_object,
    verify_vault_object,
)
from file_agent.vault_engine.rules import VAULT_ENGINE_ID
from file_agent.vault_engine.safety import ensure_disjoint_roots

__all__ = [
    "VAULT_ENGINE_ID",
    "InvalidVaultConfigurationError",
    "VaultEngine",
    "VaultLookupFailure",
    "VaultLookupOutcome",
    "VaultLookupStatus",
    "VerifiedVaultObject",
    "ensure_disjoint_roots",
    "rehash_vault_object",
    "vault_capture_requested_event",
    "vault_capture_result_event",
    "verify_vault_object",
]
