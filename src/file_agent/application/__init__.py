"""FileAgentApplicationService -- the sole product-facing orchestration
boundary between UI/CLI and every engine below it (Scanner, FileHasher,
FileClassifier, ProposalEngine, PolicyEngine, HumanReviewEngine,
TransactionEngine, VaultEngine, RecoveryEngine, managed_fs, persistence).
See docs/SAFETY.md and the FA-012 design plan.

=== Trust boundary (read before wiring this up to any UI/CLI) ===

Future UI/CLI code must call ONLY the methods on FileAgentApplicationService
below -- never TransactionEngine, RecoveryEngine, VaultEngine, persistence
repositories, or construct any of the following directly:

    TransactionRequest, ReverseMoveRequest, RestoreFromVaultRequest,
    CompletedMoveEvidence, VaultCaptureEvidence, PolicyDecision,
    HumanReviewDecision, or any prepared capability token.

No public method on FileAgentApplicationService accepts any of the above as
a parameter. Every mutating method (apply_item, undo_transaction,
restore_capture, approve_review, skip_review) takes only a stable,
previously-persisted UUID identifier (plus an optional free-text note for
review actions) -- never a path, hash, or evidence object. analyze_scan/
analyze_file are the only methods that touch a filesystem concern at all,
and only as a read-side observation input, never as an authorization claim.

Evidence objects (CompletedMoveEvidence/VaultCaptureEvidence) are
constructed ONLY internally, via their own `from_transaction_result`/
`from_capture_result` factories, fed exclusively by this package's own
`queries.py` reconstructions of genuinely persisted TransactionResult/
VaultCaptureResult records -- never from caller-supplied fields. This is
the literal closing of the trust gap FA-011 documented and explicitly
deferred to "a future FA-012 Application Service."

application/ has zero managed-file mutation primitives of its own: it never
imports file_agent.managed_fs, and performs no raw filesystem mutation --
all mutation happens exclusively via TransactionEngine.prepare()/commit()
and RecoveryEngine.prepare()/commit(), which are themselves the only
callers of managed_fs.

=== ExecutionAuthorization trust boundary (FA-012 authorization correction) ===

1. FileAgentApplicationService IS the product authorization boundary -- the
   only code in this codebase trusted to decide whether an execution is
   authorized.
2. ExecutionAuthorization (file_agent.domain.authorization) is an INTERNAL,
   TRUSTED-INPUT model passed between FileAgentApplicationService and
   TransactionEngine. It is not part of this package's public API.
3. ExecutionAuthorization is a plain, frozen Pydantic BaseModel, not a
   cryptographic or otherwise unforgeable object -- it is not itself proof
   of persisted authorization against arbitrary in-process Python code. See
   its module docstring for the full statement of why this package does
   not add private-constructor/signing machinery to simulate
   unforgeability Python cannot actually provide within one process.
4. UI/CLI/external callers must never construct ExecutionAuthorization,
   deserialize external data into it, or call TransactionEngine directly.
   No public FileAgentApplicationService method accepts it as a parameter
   (enforced by tests/application/test_trust_boundary.py).
5. FileAgentApplicationService constructs ExecutionAuthorization only via
   its two sanctioned factories (from_policy_auto/from_human_approval),
   fed exclusively by genuine persisted facts reconstructed through
   application/queries.py -- never a direct ExecutionAuthorization(...)
   call (enforced by tests/application/test_no_authorization_fabrication.py).
6. TransactionEngine performs only MECHANICAL authorization/request
   lineage checking (does authorization's lineage match this request's?)
   -- it cannot and does not verify persistence authenticity. That
   verification is this package's responsibility alone.

=== OrganizationPlan / preview (FA-013) ===

create_organization_plan(policy_decision_ids) returns an OrganizationPlan --
an immutable, ephemeral (never persisted) product-facing preview snapshot.
PREVIEW IS NOT AUTHORIZATION: a plan never itself authorizes filesystem
mutation, and TransactionEngine always independently re-verifies live state
before any apply_item call actually moves a file. OrganizationPlanner
(application/planner.py) never mutates the filesystem, never imports
managed_fs, never calls TransactionEngine/RecoveryEngine, never constructs
ExecutionAuthorization, and never records a human review. It consumes (never
re-derives) file_agent.destination's shared, read-only
resolve_destination/inspect_destination -- the same functions apply_item and
TransactionEngine itself use -- so preview and execution-time destination
safety can never silently diverge. policy_decision_ids is the plan's
explicit lineage; there is no "latest scan"/"latest for this file_id"
lookup anywhere in this module.
"""

from file_agent.application.dto import (
    AnalysisFailure,
    AnalyzedItem,
    AnalyzedScanResult,
    ApplicationOutcomeStatus,
    ApplicationRejectionReason,
    ApplyResult,
    RestoreResult,
    ReviewActionResult,
    UndoResult,
)
from file_agent.application.errors import (
    DuplicatePolicyDecisionIdError,
    TerminalPersistenceError,
)
from file_agent.application.organization_plan import (
    OrganizationPlan,
    OrganizationPlanItem,
    OrganizationPlanSummary,
    PlanIssue,
    PlanReasonCode,
    PlanStatus,
)
from file_agent.application.service import FileAgentApplicationService

__all__ = [
    "AnalysisFailure",
    "AnalyzedItem",
    "AnalyzedScanResult",
    "ApplicationOutcomeStatus",
    "ApplicationRejectionReason",
    "ApplyResult",
    "DuplicatePolicyDecisionIdError",
    "FileAgentApplicationService",
    "OrganizationPlan",
    "OrganizationPlanItem",
    "OrganizationPlanSummary",
    "PlanIssue",
    "PlanReasonCode",
    "PlanStatus",
    "RestoreResult",
    "ReviewActionResult",
    "TerminalPersistenceError",
    "UndoResult",
]
