"""PolicyDecision — an immutable record of what policy permits for a proposal."""

from datetime import UTC, datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from file_agent.domain._validators import normalize_to_utc
from file_agent.domain.proposal import DestinationCategory, FileCategory


class PolicyOutcome(str, Enum):
    """The result of evaluating a FileProposal against policy.

    AUTO does not execute anything -- see docs/SAFETY.md rule 6
    (confidence != permission) and the FA-007 design plan. BLOCK is stronger
    than REVIEW: an explicit prohibition, not merely uncertainty requiring a
    human decision.
    """

    AUTO = "auto"
    REVIEW = "review"
    BLOCK = "block"


class PolicyDecision(BaseModel):
    """An immutable record of what policy permits for one FileProposal, at
    one policy-engine version. Never a filesystem action -- see
    docs/SAFETY.md rule 6. Re-evaluating the same proposal (e.g. after a
    policy_engine_id bump) produces a new PolicyDecision, never an update to
    an existing one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    proposal_id: UUID
    file_id: UUID
    decision: PolicyOutcome
    reasons: tuple[str, ...] = Field(default_factory=tuple, min_length=1)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    policy_engine_id: str = Field(min_length=1)
    """This decision's own producer -- distinct from proposal_engine_id below,
    which identifies the source proposal's producer."""

    source_category: FileCategory
    destination_category: DestinationCategory | None
    proposal_confidence: float = Field(ge=0.0, le=1.0)
    proposal_engine_id: str = Field(min_length=1)
    """Copied verbatim from the source FileProposal -- structured provenance,
    not just prose in `reasons`."""

    _validate_evaluated_at = field_validator("evaluated_at")(normalize_to_utc)
