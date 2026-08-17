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
restore_capture, approve_review, skip_review, remove_managed_root) takes
only a stable, previously-persisted UUID identifier (plus an optional
free-text note for review actions) -- never a path, hash, or evidence
object. The one deliberate exception is add_managed_root, the sole public
method anywhere that accepts a raw filesystem path (see "Managed Roots"
below). analyze_managed_root/analyze_file are the only methods that touch a
filesystem concern for an already-registered root, and only as a read-side
observation input, never as an authorization claim.

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

=== Batch apply / history (FA-014) ===

apply_items(policy_decision_ids) orchestrates the exact same trusted
per-item path apply_item already walks (_apply_one), once per selected id,
in caller order -- BATCH INTENT IS NOT BATCH AUTHORIZATION. Atomicity is
best-effort/per-item: a normal business rejection continues the batch; only
an unreliable audit trail (a durability failure, never a business outcome)
stops it early, for the remaining unprocessed ids only. There is no batch
rollback. A durable, event-sourced batch history
(BATCH_APPLY_STARTED/BATCH_ITEM_RECORDED/BATCH_APPLY_COMPLETED, no new SQL
table) records each item's outcome as it becomes durably trustworthy, so a
crash mid-batch never loses already-known results. get_batch_history and
list_recent_batch_history (application/history.py) share one internal
reconstruction path, so a list row is never less authoritative than the
detail view -- only less verbose; a malformed/ambiguous historical batch
renders as UnavailableBatchHistoryRow rather than fabricated counts or a
silently dropped row.

=== Managed Roots (FA-015) -- the filesystem authority boundary ===

FileAgent may only analyze/organize files inside an explicitly registered,
currently-active ManagedRoot. add_managed_root(path) is the ONLY public
method anywhere in this package that accepts a raw filesystem path; every
other method (analyze_managed_root, create_organization_plan, apply_item,
apply_items, remove_managed_root, list_managed_roots, undo_transaction,
restore_capture) takes only a previously-persisted UUID and re-derives its
own root authority from that id -- a caller-supplied path can never
substitute for a persisted ManagedRoot lookup during any authorization or
mutation decision.

file_agent.application.managed_roots._resolve_safe_managed_root is the ONE
shared primitive that turns a persisted ManagedRoot.path into an
operational SandboxRoot, used identically by every one of the call sites
above (see that module's own docstring for the full call-site table and the
live-reinspection rationale). Registration-time success only proves a path
was safe ONCE; every later use re-derives that proof FRESH, because an
ancestor directory of an already-registered root can be turned into a
symlink/junction after registration, silently redirecting authority to a
different physical tree -- a bare, cached, or registration-time-only check
would miss exactly that. tests/application/test_managed_root_ast_guardrail.py
is the structural guardrail proving no application code outside that one
function ever calls SandboxRoot.from_path directly on a ManagedRoot-derived
path.

Residual TOCTOU window (documented here per the same convention as
transaction_engine's and vault_engine's own accepted-race notes; full detail
in managed_roots.py's module docstring): _resolve_safe_managed_root's checks
are fail-closed and point-in-time, not an atomic filesystem snapshot. FA-015
does not introduce Windows File IDs, directory handles held open across the
check-then-use sequence, USN-journal tracking, or a global filesystem lock
to close this window -- doing so is explicitly out of scope, consistent with
every other residual race already accepted elsewhere in this codebase.

Undo/restore remain governed by RecoveryEngine's own independent live
re-verification regardless of a root's current registration state -- a
removed-but-still-resolvable historical root does not itself authorize
undo/restore; RecoveryEngine still independently re-checks hash/size/
containment before reversing anything.
"""

from file_agent.application.dto import (
    AnalysisFailure,
    AnalyzedItem,
    AnalyzedScanResult,
    ApplicationOutcomeStatus,
    ApplicationRejectionReason,
    ApplyResult,
    BatchApplyItemResult,
    BatchApplyItemStatus,
    BatchApplyResult,
    BatchApplySummary,
    BatchStatus,
    RestoreResult,
    ReviewActionResult,
    UndoResult,
)
from file_agent.application.errors import (
    DuplicatePolicyDecisionIdError,
    EmptyBatchSelectionError,
    TerminalPersistenceError,
)
from file_agent.application.history import (
    BatchHistoryEntry,
    BatchHistoryItem,
    UnavailableBatchHistoryRow,
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
    "BatchApplyItemResult",
    "BatchApplyItemStatus",
    "BatchApplyResult",
    "BatchApplySummary",
    "BatchHistoryEntry",
    "BatchHistoryItem",
    "BatchStatus",
    "DuplicatePolicyDecisionIdError",
    "EmptyBatchSelectionError",
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
    "UnavailableBatchHistoryRow",
    "UndoResult",
]
