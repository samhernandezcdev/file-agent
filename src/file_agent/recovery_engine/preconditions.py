"""Individual, ordered precondition checks for one RecoveryRequest.

Each function is read-only and returns RecoveryRejectionCode | None (or,
for current-file identity, str | RecoveryRejectionCode). No mutation
primitive appears anywhere in this module. engine.py sequences these calls
in the order the design requires -- containment/safety BEFORE any
existence/stat/open/hash call on a caller-supplied path -- this module does
not itself decide the order.
"""

import os

from file_agent.domain import (
    CompletedMoveEvidence,
    DiscoveredFile,
    RecoveryRejectionCode,
    ReverseMoveRequest,
    VaultCaptureEvidence,
)
from file_agent.hasher import FileHasher, HashFailure, HashIssueType
from file_agent.recovery_engine._paths import (
    has_unsafe_reparse_ancestor,
    resolve_for_containment,
)
from file_agent.scanner import SandboxRoot


def check_basename_preserved(
    evidence: CompletedMoveEvidence,
) -> RecoveryRejectionCode | None:
    if evidence.source_path.name != evidence.destination_path.name:
        return RecoveryRejectionCode.BASENAME_MISMATCH
    return None


def check_original_path_containment(
    evidence: CompletedMoveEvidence, sandbox_root: SandboxRoot
) -> RecoveryRejectionCode | None:
    resolved = resolve_for_containment(evidence.source_path)
    if resolved is None or not resolved.is_relative_to(sandbox_root.path):
        return RecoveryRejectionCode.ORIGINAL_PATH_OUTSIDE_SANDBOX
    if has_unsafe_reparse_ancestor(evidence.source_path.parent, sandbox_root.path):
        return RecoveryRejectionCode.ORIGINAL_PATH_UNSAFE_REPARSE_POINT
    return None


def check_original_path_not_occupied(
    evidence: CompletedMoveEvidence,
) -> RecoveryRejectionCode | None:
    destination = evidence.source_path
    if (
        destination.exists()
        or destination.is_symlink()
        or os.path.isjunction(destination)
    ):
        return RecoveryRejectionCode.ORIGINAL_PATH_OCCUPIED
    return None


def check_original_parent_exists(
    evidence: CompletedMoveEvidence,
) -> RecoveryRejectionCode | None:
    if not evidence.source_path.parent.is_dir():
        return RecoveryRejectionCode.ORIGINAL_PARENT_MISSING
    return None


def verify_current_file_identity(
    request: ReverseMoveRequest, sandbox_root: SandboxRoot
) -> str | RecoveryRejectionCode:
    """Reconstructs a synthetic DiscoveredFile from the request's expected
    metadata and reverifies it via the existing, unmodified FileHasher at
    evidence.destination_path (B) -- the fourth reuse of this exact idiom in
    the codebase (transaction_engine, vault_engine x2, now recovery_engine).
    This also transitively proves B-side containment and reparse safety --
    FileHasher independently re-validates both -- so no separate check is
    duplicated here. Collapses to exactly 2 codes (not 3, unlike
    transaction_engine/vault_engine's own source-identity checks): NOT_FOUND
    maps to CURRENT_FILE_MISSING; everything else, including a hash
    mismatch, collapses to CURRENT_FILE_CHANGED.
    """
    synthetic = DiscoveredFile(
        path=request.evidence.destination_path,
        size_bytes=request.expected_size,
        created_at=request.expected_created_at,
        modified_at=request.expected_modified_at,
    )
    outcome = FileHasher(sandbox_root).hash_file(synthetic)
    if isinstance(outcome, HashFailure):
        if outcome.issue.issue_type is HashIssueType.NOT_FOUND:
            return RecoveryRejectionCode.CURRENT_FILE_MISSING
        return RecoveryRejectionCode.CURRENT_FILE_CHANGED
    if outcome.hashed.sha256 != request.evidence.verified_sha256:
        return RecoveryRejectionCode.CURRENT_FILE_CHANGED
    assert outcome.hashed.sha256 is not None, (
        "HashSuccess always carries a computed sha256"
    )
    return outcome.hashed.sha256


def check_target_containment(
    evidence: VaultCaptureEvidence, sandbox_root: SandboxRoot
) -> RecoveryRejectionCode | None:
    resolved = resolve_for_containment(evidence.source_path)
    if resolved is None or not resolved.is_relative_to(sandbox_root.path):
        return RecoveryRejectionCode.TARGET_PATH_OUTSIDE_SANDBOX
    if has_unsafe_reparse_ancestor(evidence.source_path.parent, sandbox_root.path):
        return RecoveryRejectionCode.TARGET_PATH_UNSAFE_REPARSE_POINT
    return None


def check_target_not_occupied(
    evidence: VaultCaptureEvidence,
) -> RecoveryRejectionCode | None:
    target = evidence.source_path
    if target.exists() or target.is_symlink() or os.path.isjunction(target):
        return RecoveryRejectionCode.TARGET_PATH_OCCUPIED
    return None


def check_target_parent_exists(
    evidence: VaultCaptureEvidence,
) -> RecoveryRejectionCode | None:
    if not evidence.source_path.parent.is_dir():
        return RecoveryRejectionCode.TARGET_PARENT_MISSING
    return None
