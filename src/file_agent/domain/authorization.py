"""ExecutionAuthorization — an explicit, non-fabricated record of why one
specific execution is authorized to proceed.

Never a filesystem action, and never a replacement for PolicyDecision:
PolicyDecision.decision is NEVER rewritten to AUTO to represent a human's
approval of a REVIEW decision -- see docs/SAFETY.md rule 6 (confidence !=
permission). POLICY_AUTO and HUMAN_APPROVED are kept as two distinct,
non-interchangeable authorization kinds precisely so that fact stays
structurally visible: a genuine PolicyEngine AUTO decision and a genuine
human APPROVE of a REVIEW decision are different facts with different
provenance, even though both end up authorizing the same kind of execution.

Trust boundary -- read this before touching this model:

1. FileAgentApplicationService (file_agent.application) is THE product
   authorization boundary. It is the only code in this codebase that is
   trusted to decide whether an execution is authorized.
2. ExecutionAuthorization is an INTERNAL, TRUSTED-INPUT model passed
   between FileAgentApplicationService and TransactionEngine. It is not a
   public API type and is never exposed to a UI/CLI/external caller.
3. ExecutionAuthorization is NOT itself cryptographic or otherwise
   unforgeable proof of persisted authorization against arbitrary
   in-process Python code. It is a plain, frozen Pydantic BaseModel --
   nothing prevents another module inside this same process from calling
   `ExecutionAuthorization(...)` directly, bypassing both factories below.
   This package deliberately does NOT add private-constructor or signing
   machinery to simulate unforgeability that Python cannot actually
   provide within one process -- see FA-012's authorization-correction
   review. The sanctioned construction paths are the two classmethod
   factories below; calling the plain constructor directly is technically
   possible but is outside the trusted FileAgentApplicationService
   contract, exactly as building a TransactionRequest or PolicyDecision by
   hand is technically possible but outside that contract too.
4. UI/CLI/external callers must never: construct ExecutionAuthorization,
   deserialize external data into it, or call TransactionEngine directly.
   FileAgentApplicationService's public API accepts no
   ExecutionAuthorization parameter anywhere (see
   tests/application/test_trust_boundary.py) -- there is no path for an
   external caller to supply one even indirectly.
5. FileAgentApplicationService must construct authorization only from
   genuine persisted facts, reconstructed through
   file_agent.application.queries -- never from caller-supplied claims.
6. TransactionEngine is responsible for MECHANICAL authorization/request
   lineage checking (does this authorization's policy_decision_id/
   proposal_id/file_id/destination_category match this request's?) -- it
   is not, and cannot be, responsible for verifying that the
   authorization's underlying facts were genuinely persisted. That
   verification happens once, upstream, in
   FileAgentApplicationService via the two factories below. A forged but
   internally-consistent ExecutionAuthorization (correct shape, matching
   lineage, never actually derived from a persisted PolicyDecision/
   HumanReviewDecision) is outside TransactionEngine's threat boundary --
   TransactionEngine only rejects a MISMATCHED authorization (wrong
   lineage for this request), never re-derives whether the authorization
   was honestly constructed in the first place.

The two sanctioned construction paths are `from_policy_auto` and
`from_human_approval` below, each of which independently reverifies the
exact rule it embodies before authorizing anything -- mirrors
CompletedMoveEvidence.from_transaction_result and
VaultCaptureEvidence.from_capture_result. Every call site inside
file_agent.application uses only these two factories (enforced by
tests/application/test_no_authorization_fabrication.py); nothing in this
model prevents a DIFFERENT, untrusted call site from bypassing them, which
is exactly why FileAgentApplicationService -- not this model -- is the
actual trust boundary.
"""

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from file_agent.domain.human_review import HumanReviewDecision, HumanReviewOutcome
from file_agent.domain.policy import PolicyDecision, PolicyOutcome
from file_agent.domain.proposal import DestinationCategory


class ExecutionAuthorizationKind(str, Enum):
    """Why one specific execution is authorized -- never inferred, always
    traceable to exactly one of these two genuine, persisted facts."""

    POLICY_AUTO = "policy_auto"
    HUMAN_APPROVED = "human_approved"


class ExecutionAuthorization(BaseModel):
    """Proof that one specific (policy_decision_id, proposal_id, file_id)
    triple is authorized to execute, and why. Carries no path/hash/evidence
    of its own -- TransactionEngine still independently reverifies the live
    file via TransactionRequest/FileHasher; this model only settles the
    authorization question, never the identity question.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_decision_id: UUID
    proposal_id: UUID
    file_id: UUID
    destination_category: DestinationCategory
    authorization_kind: ExecutionAuthorizationKind
    human_review_decision_id: UUID | None = None

    @model_validator(mode="after")
    def _validate_kind_consistency(self) -> "ExecutionAuthorization":
        if self.authorization_kind is ExecutionAuthorizationKind.POLICY_AUTO:
            if self.human_review_decision_id is not None:
                raise ValueError(
                    "POLICY_AUTO authorization must not carry a "
                    "human_review_decision_id"
                )
        elif self.human_review_decision_id is None:
            raise ValueError(
                "HUMAN_APPROVED authorization requires a human_review_decision_id"
            )
        return self

    @classmethod
    def from_policy_auto(
        cls, policy_decision: PolicyDecision
    ) -> "ExecutionAuthorization":
        """The sanctioned construction path for a POLICY_AUTO authorization
        (direct ExecutionAuthorization(...) construction is technically
        possible but outside the trusted FileAgentApplicationService
        contract -- see the module docstring). Refuses any PolicyDecision
        whose decision is not genuinely AUTO."""
        if policy_decision.decision is not PolicyOutcome.AUTO:
            raise ValueError(
                "from_policy_auto requires policy_decision.decision == AUTO, "
                f"got {policy_decision.decision!r}"
            )
        if policy_decision.destination_category is None:
            raise ValueError("AUTO policy_decision must carry a destination_category")
        return cls(
            policy_decision_id=policy_decision.id,
            proposal_id=policy_decision.proposal_id,
            file_id=policy_decision.file_id,
            destination_category=policy_decision.destination_category,
            authorization_kind=ExecutionAuthorizationKind.POLICY_AUTO,
            human_review_decision_id=None,
        )

    @classmethod
    def from_human_approval(
        cls, policy_decision: PolicyDecision, review: HumanReviewDecision
    ) -> "ExecutionAuthorization":
        """The sanctioned construction path for a HUMAN_APPROVED
        authorization (direct ExecutionAuthorization(...) construction is
        technically possible but outside the trusted
        FileAgentApplicationService contract -- see the module docstring).
        Refuses unless policy_decision is genuinely REVIEW, review is
        genuinely APPROVE, and every lineage field matches. Never rewrites
        policy_decision.decision -- the persisted PolicyDecision stays
        REVIEW forever; this is a separate authorization fact layered on
        top of it, not a replacement for it."""
        if policy_decision.decision is not PolicyOutcome.REVIEW:
            raise ValueError(
                "from_human_approval requires policy_decision.decision == "
                f"REVIEW, got {policy_decision.decision!r}"
            )
        if review.outcome is not HumanReviewOutcome.APPROVE:
            raise ValueError(
                "from_human_approval requires review.outcome == APPROVE, "
                f"got {review.outcome!r}"
            )
        if review.policy_decision_id != policy_decision.id:
            raise ValueError(
                "review.policy_decision_id does not match policy_decision.id"
            )
        if review.proposal_id != policy_decision.proposal_id:
            raise ValueError(
                "review.proposal_id does not match policy_decision.proposal_id"
            )
        if review.file_id != policy_decision.file_id:
            raise ValueError("review.file_id does not match policy_decision.file_id")
        if review.destination_category != policy_decision.destination_category:
            raise ValueError(
                "review.destination_category does not match "
                "policy_decision.destination_category"
            )
        if policy_decision.destination_category is None:
            raise ValueError(
                "REVIEW policy_decision must carry a destination_category to authorize"
            )
        return cls(
            policy_decision_id=policy_decision.id,
            proposal_id=policy_decision.proposal_id,
            file_id=policy_decision.file_id,
            destination_category=policy_decision.destination_category,
            authorization_kind=ExecutionAuthorizationKind.HUMAN_APPROVED,
            human_review_decision_id=review.id,
        )
