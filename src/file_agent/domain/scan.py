"""ScanRun — an immutable snapshot of one directory scan's lifecycle state."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from file_agent.domain._validators import ensure_absolute_path, normalize_to_utc


class ScanStatus(str, Enum):
    """Lifecycle state of a ScanRun."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ScanRun(BaseModel):
    """A snapshot of one directory scan: where, when, how far, and its outcome.

    Frozen, like the other domain models — a scan's lifecycle is represented as
    a sequence of immutable snapshots rather than in-place mutation, so no
    caller can ever observe (or accidentally construct) a state where, e.g.,
    ``status`` is ``COMPLETED`` but ``completed_at`` hasn't been set yet. Use
    :meth:`evolve` to produce the next snapshot from the current one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    _EVOLVABLE_FIELDS = frozenset({"status", "completed_at", "files_discovered"})

    id: UUID = Field(default_factory=uuid4)
    root_path: Path
    started_at: datetime
    completed_at: datetime | None = None
    files_discovered: int = Field(default=0, ge=0)
    status: ScanStatus = ScanStatus.PENDING

    _validate_root_path = field_validator("root_path")(ensure_absolute_path)
    _validate_started_at = field_validator("started_at")(normalize_to_utc)

    @field_validator("completed_at")
    @classmethod
    def _validate_completed_at(cls, value: datetime | None) -> datetime | None:
        return value if value is None else normalize_to_utc(value)

    @model_validator(mode="after")
    def _validate_completion_state(self) -> "ScanRun":
        if (
            self.status in (ScanStatus.COMPLETED, ScanStatus.FAILED)
            and self.completed_at is None
        ):
            raise ValueError(
                "completed_at must be set when status is COMPLETED or FAILED"
            )
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot be before started_at")
        return self

    def evolve(self, **changes: Any) -> "ScanRun":
        """Return a new ScanRun with ``changes`` applied, validated as a whole.

        Only lifecycle/progress fields (``status``, ``completed_at``,
        ``files_discovered``) may be changed. Identity and structural fields
        (``id``, ``root_path``, ``started_at``) are rejected, as is any
        unrecognized field — a scan's identity must not drift across its own
        lifecycle snapshots. This is a generic immutable-update helper, not a
        lifecycle-specific transition method — it applies the given changes
        atomically so that a multi-field update (e.g. status + completed_at
        together) is either fully valid or rejected, with no intermediate
        invalid state.
        """
        disallowed = set(changes) - self._EVOLVABLE_FIELDS
        if disallowed:
            raise ValueError(
                f"evolve() cannot modify {sorted(disallowed)}; "
                f"only {sorted(self._EVOLVABLE_FIELDS)} may be changed"
            )
        return type(self).model_validate({**self.model_dump(), **changes})
