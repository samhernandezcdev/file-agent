"""Individual, ordered precondition checks for one TransactionRequest.

Each function is read-only and returns RejectionCode | None (or, for source
identity, str | RejectionCode). No mutation primitive appears anywhere in
this module -- enforced by both the package-local and repo-wide AST
guardrails. engine.py sequences these calls; this module does not itself
decide the order.
"""

from file_agent.destination import (
    PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY,
    DestinationConflict,
    inspect_destination,
    resolve_for_containment,
)
from file_agent.domain import (
    DiscoveredFile,
    ExecutionAuthorization,
    RejectionCode,
    TransactionRequest,
)
from file_agent.hasher import FileHasher, HashFailure, HashIssueType
from file_agent.scanner import SandboxRoot


def check_authorization_linkage(
    request: TransactionRequest, authorization: ExecutionAuthorization
) -> RejectionCode | None:
    """authorization can only ever have been produced by
    ExecutionAuthorization.from_policy_auto/from_human_approval, each of
    which independently reverified the exact rule it embodies -- this check
    exists solely to catch a MISMATCHED authorization (one built for a
    different policy_decision/proposal/file than this specific request
    references), not to re-decide whether execution is allowed at all."""
    if (
        authorization.policy_decision_id != request.policy_decision_id
        or authorization.proposal_id != request.proposal_id
        or authorization.file_id != request.file_id
    ):
        return RejectionCode.AUTHORIZATION_LINKAGE_MISMATCH
    return None


def check_destination_category_matches_authorization(
    request: TransactionRequest, authorization: ExecutionAuthorization
) -> RejectionCode | None:
    if request.destination_category != authorization.destination_category:
        return RejectionCode.DESTINATION_CATEGORY_MISMATCH
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


_REJECTION_CODE_FOR_CONFLICT: dict[DestinationConflict, RejectionCode] = {
    DestinationConflict.SOURCE_EQUALS_DESTINATION: RejectionCode.SOURCE_EQUALS_DESTINATION,
    DestinationConflict.BASENAME_MISMATCH: RejectionCode.BASENAME_MISMATCH,
    DestinationConflict.OUTSIDE_SANDBOX: RejectionCode.DESTINATION_OUTSIDE_SANDBOX,
    DestinationConflict.UNSAFE_REPARSE_POINT: RejectionCode.DESTINATION_UNSAFE_REPARSE_POINT,
    DestinationConflict.PARENT_MISSING: RejectionCode.DESTINATION_PARENT_MISSING,
    DestinationConflict.ALREADY_OCCUPIED: RejectionCode.DESTINATION_ALREADY_EXISTS,
    DestinationConflict.OBSERVATION_FAILED: RejectionCode.DESTINATION_OBSERVATION_FAILED,
}


def check_destination_readiness(
    request: TransactionRequest, sandbox_root: SandboxRoot
) -> RejectionCode | None:
    """Delegates to the shared, read-only destination.inspect_destination --
    the exact same function OrganizationPlanner calls for preview (FA-013)
    -- so TransactionEngine can never enforce different destination-safety
    semantics than what preview showed for the same filesystem state.
    Folds what were previously five separate preconditions
    (check_source_not_destination, check_basename_preserved,
    check_destination_containment, check_destination_parent_exists,
    check_destination_collision) into one shared call; the fixed check order
    inside inspect_destination itself reproduces their previous relative
    precedence exactly."""
    inspection = inspect_destination(
        sandbox_root, request.source_path, request.destination_path
    )
    if inspection.conflict is DestinationConflict.NONE:
        return None
    return _REJECTION_CODE_FOR_CONFLICT[inspection.conflict]


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
