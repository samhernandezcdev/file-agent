"""DiscoveredFile — an immutable record of a file found during a scan."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from file_agent.domain._validators import ensure_absolute_path, normalize_to_utc


class DiscoveredFile(BaseModel):
    """A file discovered on disk during a scan, as of the moment it was observed.

    ``sha256`` is optional because a file exists in the domain from the moment
    ``FILE_DISCOVERED`` fires, but its hash is only known once ``FILE_HASHED``
    fires. Use :meth:`with_sha256` to produce a later snapshot of the same
    logical file (same ``id``) once its hash becomes known — the instance
    itself is never mutated in place.

    ``filename`` and ``extension`` are derived from ``path`` rather than
    stored as independent fields, so they can never disagree with it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    path: Path
    size_bytes: int = Field(ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    modified_at: datetime
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    discovered_by_scan_id: UUID | None = None
    managed_root_id: UUID | None = None
    """FA-015: which ManagedRoot this file was discovered under. Set exactly
    once, at construction (by the scanner), never mutated afterward -- the
    single source of truth every other component (proposal, policy,
    transaction, vault capture, batch, undo/restore) derives root lineage
    from via file_id, never stored redundantly elsewhere. None only for
    observations created before the FA-015 migration (permanently so; never
    retroactively backfilled)."""

    _validate_path = field_validator("path")(ensure_absolute_path)
    _validate_created_at = field_validator("created_at")(normalize_to_utc)
    _validate_modified_at = field_validator("modified_at")(normalize_to_utc)
    _validate_discovered_at = field_validator("discovered_at")(normalize_to_utc)

    @property
    def filename(self) -> str:
        """The file's name, taken directly from ``path`` (single source of truth)."""
        return self.path.name

    @property
    def extension(self) -> str:
        """The file's extension: ``path.suffix``, lowercased, without the leading dot.

        Only the final suffix is used (pathlib semantics), so
        ``archive.tar.gz`` yields ``"gz"``, not ``"tar.gz"``.
        """
        return self.path.suffix.lstrip(".").lower()

    def with_sha256(self, sha256: str) -> "DiscoveredFile":
        """Return a new snapshot of this file with ``sha256`` set.

        Preserves ``id`` and every other field; represents a later snapshot of
        the same logical discovered file once its hash is known, without
        mutating this instance.
        """
        return type(self).model_validate({**self.model_dump(), "sha256": sha256})
