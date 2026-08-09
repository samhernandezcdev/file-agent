"""Internal path-handling helpers for the scanner. Not part of the public API."""

import os
import stat
from datetime import UTC, datetime
from pathlib import Path


def is_unc_path(path: Path) -> bool:
    """True if `path` is a UNC path (``\\\\server\\share\\...``). UNC roots are rejected."""
    return path.drive.startswith("\\\\")


def is_reparse_point(path: Path) -> bool:
    """Best-effort check of whether `path` itself (not its target) is a reparse point.

    Covers true symlinks, NTFS junctions, and any other reparse-tagged entry
    (e.g. a OneDrive placeholder). Never follows `path`. Used only for
    sandbox-root validation, where the check must happen BEFORE resolving —
    resolving first would silently follow the reference and lose the
    information needed to reject it.
    """
    if path.is_symlink():
        return True
    if os.path.isjunction(path):
        return True
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return bool(st.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def resolve_reference_target(path: Path) -> Path | None:
    """Resolve a symlink/junction's target for containment checking.

    Returns None if the target cannot be resolved or does not exist — callers
    must treat that as "unresolvable" (fail-closed, but not a confirmed
    escape), never as evidence about containment either way.
    """
    try:
        candidate = path.resolve(strict=False)
    except OSError:
        return None
    if not candidate.exists():
        return None
    return candidate


def file_times_from_stat(st: os.stat_result) -> tuple[datetime, datetime]:
    """Map OS timestamps to (created_at, modified_at).

    Windows-specific: `st_ctime` IS creation time on Windows (unlike POSIX,
    where it's metadata-change time) — using it here is correct for this
    platform. Isolated here as the seam for any future POSIX support.
    """
    created_at = datetime.fromtimestamp(st.st_ctime, tz=UTC)
    modified_at = datetime.fromtimestamp(st.st_mtime, tz=UTC)
    return created_at, modified_at
