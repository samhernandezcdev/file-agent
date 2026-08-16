"""Internal, destination-side path-safety helpers. Not part of the public API.

Promoted (moved, not duplicated) from transaction_engine._paths -- once
destination.inspection became the single shared implementation both
OrganizationPlanner and TransactionEngine consume, keeping a second, private
copy inside transaction_engine would have re-created exactly the kind of
divergence risk this package exists to eliminate. There is now exactly one
canonical implementation. `resolve_for_containment` is re-exported via
destination/__init__.py for transaction_engine.preconditions' own
request-self-consistency check (check_destination_category_physical_path),
which needs plain containment resolution but not the full destination
inspection; `is_unsafe_reparse_point`/`has_unsafe_reparse_ancestor` remain
internal to this package, used by inspection.py only.

Source-side containment/reparse safety is entirely delegated to the existing
FileHasher (see transaction_engine.engine) -- FileHasher already
independently re-validates it, and duplicating that logic here would drift
out of sync with FA-003's. Destination-side checks have no other existing
primitive to reuse (nothing else validates a not-yet-existing path).
"""

import os
from pathlib import Path


def resolve_for_containment(path: Path) -> Path | None:
    """Resolve `path` for a containment check, independent of whether it
    currently exists. `strict=False` still follows any existing reparse
    point along an ancestor directory chain before appending a nonexistent
    leaf. None only when resolution itself fails with an OSError.
    """
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
    including) `boundary`, is a symlink/junction.

    Mirrors the scanner's conservative "never follow a reparse point, even
    one that would resolve inside the sandbox" policy (see
    scanner.scanner._handle_reference) -- containment alone (resolve() +
    is_relative_to()) is not treated as sufficient for a destination path;
    no reparse point may sit anywhere between the sandbox root and the
    destination's parent directory.
    """
    if is_unsafe_reparse_point(path):
        return True
    for ancestor in path.parents:
        if ancestor == boundary or not ancestor.is_relative_to(boundary):
            break
        if is_unsafe_reparse_point(ancestor):
            return True
    return False
