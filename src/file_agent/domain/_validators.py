"""Shared validator functions for domain models.

Not part of the public API of :mod:`file_agent.domain` — internal helpers only.
"""

from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any


def ensure_absolute_path(value: Path) -> Path:
    """Reject relative paths; domain entities must reference unambiguous locations."""
    if not value.is_absolute():
        raise ValueError(f"path must be absolute, got: {value!r}")
    return value


def normalize_to_utc(value: datetime) -> datetime:
    """Reject naive datetimes; convert any timezone-aware datetime to UTC."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(
            f"datetime must be timezone-aware, got naive datetime: {value!r}"
        )
    return value.astimezone(UTC)


def deep_freeze(value: Any) -> Any:
    """Recursively convert dicts to read-only mappings and lists to tuples.

    Used to make container-typed fields (e.g. event payloads) genuinely
    immutable under a frozen model, not just protected against attribute
    reassignment.
    """
    if isinstance(value, dict):
        return MappingProxyType({key: deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(deep_freeze(item) for item in value)
    return value


def deep_thaw(value: Any) -> Any:
    """Inverse of deep_freeze: convert back to plain JSON-compatible dict/list."""
    if isinstance(value, MappingProxyType):
        return {key: deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [deep_thaw(item) for item in value]
    return value
