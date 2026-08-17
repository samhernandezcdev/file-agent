"""ManagedRoot -- FA-015's durable, user-registered filesystem authority
boundary. FileAgent may only analyze/organize files inside an active
(non-removed) ManagedRoot; see application/managed_roots.py for the full
registration-validation and live-resolution logic this model backs.

Smallest model that satisfies the actual product requirement: no `enabled`
flag (soft-delete via `removed_at` already gives an unambiguous "not
currently authoritative" state), no stored display name (derived from
`path.name` at render time), no persisted availability status (computed on
demand -- see application/managed_roots.py's ManagedRootView).
"""

from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from file_agent.domain._validators import ensure_absolute_path, normalize_to_utc


class ManagedRoot(BaseModel):
    """A registered folder FileAgent is authorized to analyze/organize.

    `id` is durable and stable across scans/history -- never reused, even
    across a remove-then-re-register cycle for the same path (see
    application/managed_roots.py for why reusing an id would be unsafe).
    `path` is immutable after creation: it is never rewritten to follow a
    rename, and registering a genuinely different folder always creates a
    new ManagedRoot rather than mutating an existing one. Soft-delete only:
    `removed_at` is set to record removal, but the row is never deleted and
    never reactivated -- this is what lets historical `managed_root_id`
    lineage on FileObservationRow/batch history always resolve to something,
    even for a long-removed root.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    path: Path
    created_at: datetime
    removed_at: datetime | None = None

    _validate_path = field_validator("path")(ensure_absolute_path)
    _validate_created_at = field_validator("created_at")(normalize_to_utc)

    @field_validator("removed_at")
    @classmethod
    def _validate_removed_at(cls, value: datetime | None) -> datetime | None:
        return value if value is None else normalize_to_utc(value)

    @property
    def is_active(self) -> bool:
        return self.removed_at is None
