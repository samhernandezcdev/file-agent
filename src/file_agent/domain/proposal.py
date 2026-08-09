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
    category: FileCategory
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: tuple[str, ...] = Field(default_factory=tuple, min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    _validate_created_at = field_validator("created_at")(normalize_to_utc)

    @field_validator("proposed_destination")
    @classmethod
    def _validate_destination(cls, value: Path | None) -> Path | None:
        return value if value is None else ensure_absolute_path(value)
