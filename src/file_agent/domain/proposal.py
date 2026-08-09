"""FileProposal — an immutable, human-reviewable suggestion about a discovered file."""

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from file_agent.domain._validators import ensure_absolute_path, normalize_to_utc


class FileCategory(str, Enum):
    """Coarse classification of a discovered file's content."""

    DOCUMENT = "document"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    ARCHIVE = "archive"
    CODE = "code"
    EXECUTABLE = "executable"
    """A directly-launchable operational file (.exe, .msi, .dll, .bat, .cmd, ...) —
    not defined strictly as "binary/compiled" (.bat/.cmd are text). The distinguishing
    property is that the OS launches/loads it directly by name, unlike CODE (source/
    scripts requiring an explicit interpreter). Exists to preserve a distinct signal
    for a future policy layer (e.g. "never auto-move executables") — the domain and
    classifier layers do not implement any such policy themselves.
    """
    OTHER = "other"
    UNKNOWN = "unknown"


class DestinationCategory(str, Enum):
    """A logical organization destination — not a filesystem path, absolute
    or relative. Resolving this into an actual location (organization root,
    category folder, filename) is explicitly deferred to a future ticket;
    this enum exists only to constrain proposals to a small, stable, typed
    vocabulary instead of letting arbitrary strings ("Docs", "documents/",
    ad-hoc casing) enter durable proposal records.
    """

    DOCUMENTS = "documents"
    IMAGES = "images"
    AUDIO = "audio"
    VIDEO = "video"
    ARCHIVES = "archives"
    CODE = "code"
    EXECUTABLES = "executables"


class FileProposal(BaseModel):
    """A proposed rename/move for a discovered file, with the reasoning behind it.

    ``confidence`` is never authorization to act — see SAFETY.md rule 6
    ("confidence != permission"). ``proposed_name``/``proposed_destination`` may
    both be absent: a low-confidence proposal may flag a file for human review
    without yet resolving a specific new name or destination.

    ``reasons`` is a tuple rather than a list so that, combined with
    ``frozen=True``, a proposal is genuinely immutable after creation — not
    just protected against top-level attribute reassignment.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    file_id: UUID
    proposed_name: str | None = Field(default=None, min_length=1)
    proposed_destination: Path | None = None
    proposed_destination_category: DestinationCategory | None = None
    """A logical destination key, or None if no destination can be proposed.
    Deliberately distinct from ``proposed_destination`` (an absolute path,
    reserved for a future organization-root-aware producer) — this field
    represents organization *intent*, not a resolved filesystem location.
    """
    category: FileCategory
    """The classification category this proposal is based on (i.e. the
    source ``ClassificationResult.category`` at proposal-generation time) —
    not an independent proposal-specific taxonomy."""
    confidence: float = Field(ge=0.0, le=1.0)
    """0.0 whenever no destination is proposed; otherwise equal to
    ``source_classification_confidence``, carried forward as supporting
    evidence. Not an independently computed probabilistic model — never
    authorization to act (SAFETY.md rule 6: confidence != permission)."""
    source_classification_confidence: float = Field(ge=0.0, le=1.0)
    """The confidence of the ClassificationResult this proposal was built
    from, preserved verbatim. May diverge from ``confidence`` above (e.g. a
    confident OTHER classification with no destination mapping has
    source_classification_confidence=1.0 but confidence=0.0)."""
    source_classifier_id: str = Field(min_length=1)
    """Which classifier produced the classification this proposal is based
    on — structured provenance, not just prose in ``reasons``."""
    reasons: tuple[str, ...] = Field(default_factory=tuple, min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    proposal_engine_id: str = Field(min_length=1)
    """Stable identifier for the proposal-engine rule set that produced this
    proposal — mirrors the classifier's classifier_id."""

    _validate_created_at = field_validator("created_at")(normalize_to_utc)

    @field_validator("proposed_destination")
    @classmethod
    def _validate_destination(cls, value: Path | None) -> Path | None:
        return value if value is None else ensure_absolute_path(value)
