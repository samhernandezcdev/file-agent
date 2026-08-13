"""HumanReviewDecision — an immutable record of a human's APPROVE/SKIP
decision for one REVIEW PolicyDecision."""

from datetime import UTC, datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from file_agent.domain._validators import normalize_to_utc
from file_agent.domain.proposal import DestinationCategory


class HumanReviewOutcome(str, Enum):
    """A human's decision about one REVIEW PolicyDecision.

    APPROVE means the user explicitly approves the existing proposal for
    future execution -- it is NOT execution itself; no field anywhere in
    this domain triggers a mutation. SKIP means no execution should occur
    for this review decision.
    """

    APPROVE = "approve"
    SKIP = "skip"


class ReviewSource(str, Enum):
    """Small, fixed vocabulary for who/what produced a HumanReviewDecision.

    Only USER today -- no AI/system approval source until a concrete need
    exists (kept as an enum, not a bare literal, purely so a future source
    can be added without changing every signature that carries this type,
    mirroring TransactionOperation's single-member precedent).
    """

    USER = "user"


class HumanReviewDecision(BaseModel):
    """An immutable record of a human's decision about one REVIEW
    PolicyDecision. Never a filesystem action -- APPROVE is eligibility for
    a future execution step, not execution itself. Structural linkage
    (policy_decision_id/proposal_id/file_id) and outcome validity (AUTO/
    BLOCK rejection, APPROVE-requires-destination) are engine concerns
    (human_review_engine), not validated by this model itself -- same
    layering PolicyDecision and TransactionRequest already use: the domain
    model stays constructible for any combination a test needs; the engine
    decides what's actually allowed.

    Self-contained for provenance: policy_engine_id/proposal_engine_id/
    human_review_engine_id are copied in by HumanReviewEngine.record() after
    linkage validation, so a fully-formed HumanReviewDecision never needs
    its source PolicyDecision/FileProposal again to be persisted or
    explained -- mirroring how PolicyDecision itself is self-contained
    relative to FileProposal.

    ``id`` is a fresh UUID per instance because every HumanReviewDecision is
    its own auditable domain fact, the same identity convention FileProposal
    and PolicyDecision use. This does NOT imply that recording a second,
    contradictory review for the same policy_decision_id is valid FA-009
    behavior: v1 permits exactly one *effective* review per PolicyDecision.
    Fresh identity is about what a review IS (a distinct historical record),
    not a license for multiple effective reviews to coexist -- enforcing
    that limit is an application/orchestration-layer responsibility this
    package does not implement (see human_review_engine's module docstring).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    policy_decision_id: UUID
    proposal_id: UUID
    file_id: UUID
    outcome: HumanReviewOutcome
    destination_category: DestinationCategory | None
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    review_source: ReviewSource = ReviewSource.USER
    note: str | None = Field(default=None, min_length=1)
    policy_engine_id: str = Field(min_length=1)
    proposal_engine_id: str = Field(min_length=1)
    human_review_engine_id: str = Field(min_length=1)
    """This decision's own producer -- distinct from policy_engine_id/
    proposal_engine_id above, which identify the source PolicyDecision's and
    FileProposal's producers, copied in verbatim for structured lineage."""

    _validate_reviewed_at = field_validator("reviewed_at")(normalize_to_utc)
