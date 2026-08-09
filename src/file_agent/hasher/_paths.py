"""Internal path-handling helpers for the hasher. Not part of the public API."""

import os
import stat
from pathlib import Path


def has_reparse_attribute(st: os.stat_result) -> bool:
    """True if an already-obtained stat result has the reparse-point attribute set.

    Operates on a stat result the caller already has (no I/O of its own), so a
    single `os.stat(path, follow_symlinks=False)` call can serve both this
    check and metadata comparison — the same "one syscall, two purposes"
    pattern the scanner uses.
    """
    return bool(st.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def resolve_for_containment(path: Path) -> Path | None:
    """Resolve `path` for a containment check, independent of whether it currently exists.

    `strict=False` gives a well-defined, best-effort resolved path even for a
    path whose leaf doesn't exist (deliberately: "is this inside the
    sandbox" and "does this file currently exist" are different questions —
    existence is checked later, separately, so it can be reported as
    NOT_FOUND rather than folded into an ambiguous "unresolvable containment"
    result). None is returned only when resolution itself fails with an
    OSError (e.g. a genuinely broken/inaccessible intermediate path).
    """
    try:
        return path.resolve(strict=False)
    except OSError:
        return None
