"""Internal, managed-root path-safety helpers -- not part of the public API.

Own small local copies (not imported from transaction_engine/_paths.py or
elsewhere), matching the established convention: transaction_engine/_paths.py's
own docstring endorses small-helper duplication over cross-package private
imports, and vault_engine/safety.py already re-derived its own
is_unsafe_reparse_point rather than importing transaction_engine's or
hasher's. Vault-side safety is entirely vault_engine.lookup's job and is
never duplicated here -- these helpers are for evidence.source_path/
evidence.destination_path/target_path (managed-root paths) only.
"""

import os
from pathlib import Path


def resolve_for_containment(path: Path) -> Path | None:
    """Resolve `path` for a containment check, independent of whether it
    currently exists. `strict=False` still follows any existing reparse
    point along an ancestor directory chain before appending a nonexistent
    leaf. None only when resolution itself fails with an OSError."""
    try:
        return path.resolve(strict=False)
    except OSError:
        return None


def is_unsafe_reparse_point(path: Path) -> bool:
    """True if `path` itself (not its target) is a symlink, junction, or any
    other reparse-tagged entry. Never follows `path`."""
    if path.is_symlink():
        return True
    return bool(os.path.isjunction(path))


def has_unsafe_reparse_ancestor(path: Path, boundary: Path) -> bool:
    """True if `path` itself, or any ancestor directory up to (but not
    including) `boundary`, is a symlink/junction."""
    if is_unsafe_reparse_point(path):
        return True
    for ancestor in path.parents:
        if ancestor == boundary or not ancestor.is_relative_to(boundary):
            break
        if is_unsafe_reparse_point(ancestor):
            return True
    return False
