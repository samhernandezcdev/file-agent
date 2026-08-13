"""Individual, ordered precondition checks for one TransactionRequest.

Each function is read-only and returns RejectionCode | None (or, for source
identity, str | RejectionCode). No mutation primitive appears anywhere in
this module -- enforced by both the package-local and repo-wide AST
guardrails. engine.py sequences these calls; this module does not itself
decide the order.
"""

import os

from file_agent.domain import (
    DiscoveredFile,
    PolicyDecision,
    PolicyOutcome,
    RejectionCode,
    TransactionRequest,
)
from file_agent.hasher import FileHasher, HashFailure, HashIssueType
from file_agent.scanner import SandboxRoot
from file_agent.transaction_engine._paths import (
    has_unsafe_reparse_ancestor,
    resolve_for_containment,
)
from file_agent.transaction_engine.rules import (
    PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY,
)


def check_authorization_linkage(
    request: TransactionRequest, policy_decision: PolicyDecision
) -> RejectionCode | None:
    if (
        policy_decision.id != request.policy_decision_id
        or policy_decision.proposal_id != request.proposal_id
        or policy_decision.file_id != request.file_id
    ):
        return RejectionCode.AUTHORIZATION_LINKAGE_MISMATCH
    return None


def check_policy_is_auto(policy_decision: PolicyDecision) -> RejectionCode | None:
    if policy_decision.decision is PolicyOutcome.REVIEW:
        return RejectionCode.POLICY_REVIEW
    if policy_decision.decision is PolicyOutcome.BLOCK:
        return RejectionCode.POLICY_BLOCK
    return None


def check_destination_category_matches_policy(
    request: TransactionRequest, policy_decision: PolicyDecision
) -> RejectionCode | None:
    if request.destination_category != policy_decision.destination_category:
        return RejectionCode.DESTINATION_CATEGORY_MISMATCH
    return None


def check_source_not_destination(request: TransactionRequest) -> RejectionCode | None:
    source_resolved = resolve_for_containment(request.source_path)
    destination_resolved = resolve_for_containment(request.destination_path)
    if (
        source_resolved is not None
        and destination_resolved is not None
        and source_resolved == destination_resolved
    ):
        return RejectionCode.SOURCE_EQUALS_DESTINATION
    return None


def check_basename_preserved(request: TransactionRequest) -> RejectionCode | None:
    if request.source_path.name != request.destination_path.name:
        return RejectionCode.BASENAME_MISMATCH
    return None


def check_destination_category_physical_path(
    request: TransactionRequest, sandbox_root: SandboxRoot
) -> RejectionCode | None:
    configured = PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY.get(
        request.destination_category
    )
    if configured is None:
        return RejectionCode.DESTINATION_CATEGORY_PATH_MISMATCH
    expected_parent = resolve_for_containment(sandbox_root.path / configured)
    actual_parent = resolve_for_containment(request.destination_path.parent)
    if (
        expected_parent is None
        or actual_parent is None
        or actual_parent != expected_parent
    ):
        return RejectionCode.DESTINATION_CATEGORY_PATH_MISMATCH
    return None


def check_destination_containment(
    request: TransactionRequest, sandbox_root: SandboxRoot
) -> RejectionCode | None:
    resolved = resolve_for_containment(request.destination_path)
    if resolved is None or not resolved.is_relative_to(sandbox_root.path):
        return RejectionCode.DESTINATION_OUTSIDE_SANDBOX
    if has_unsafe_reparse_ancestor(request.destination_path.parent, sandbox_root.path):
        return RejectionCode.DESTINATION_UNSAFE_REPARSE_POINT
    return None


def check_destination_parent_exists(
    request: TransactionRequest,
) -> RejectionCode | None:
    if not request.destination_path.parent.is_dir():
        return RejectionCode.DESTINATION_PARENT_MISSING
    return None


def check_destination_collision(request: TransactionRequest) -> RejectionCode | None:
    destination = request.destination_path
    if (
        destination.exists()
        or destination.is_symlink()
        or os.path.isjunction(destination)
    ):
        return RejectionCode.DESTINATION_ALREADY_EXISTS
    return None


def verify_source_identity(
    request: TransactionRequest, sandbox_root: SandboxRoot
) -> str | RejectionCode:
    """Reconstructs a synthetic DiscoveredFile from the request's expected
    metadata and reverifies it via the existing, unmodified FileHasher --
    a full re-read, reusing FA-003's entire three-checkpoint identity chain
    (pre-open metadata match, open-vs-pre-open identity, post-read-vs-
    post-open identity). This also transitively proves source-side
    containment and reparse safety -- FileHasher independently re-validates
    both -- so no separate source-side check is duplicated here. Returns
    the freshly verified sha256 on success, or the RejectionCode explaining
    why the source could not be trusted.
    """
    synthetic = DiscoveredFile(
        path=request.source_path,
        size_bytes=request.expected_size,
        created_at=request.expected_created_at,
        modified_at=request.expected_modified_at,
    )
    outcome = FileHasher(sandbox_root).hash_file(synthetic)
    if isinstance(outcome, HashFailure):
        if outcome.issue.issue_type is HashIssueType.NOT_FOUND:
            return RejectionCode.SOURCE_NOT_FOUND
        return RejectionCode.SOURCE_IDENTITY_CHANGED
    if outcome.hashed.sha256 != request.expected_sha256:
        return RejectionCode.SOURCE_HASH_MISMATCH
    assert outcome.hashed.sha256 is not None, (
        "HashSuccess always carries a computed sha256"
    )
    return outcome.hashed.sha256
