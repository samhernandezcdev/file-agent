"""inspect_destination -- the single, shared, read-only destination-safety
check both OrganizationPlanner (preview) and TransactionEngine (execution)
call. Neither layer re-derives its own equivalent: this is the concrete
mechanism that keeps "what preview shows" and "what apply enforces" from
silently drifting apart.

Performs no filesystem mutation whatsoever -- only Path.exists()/.is_dir()/
.is_symlink()/.resolve() and os.path.isjunction(), the same read-only
primitives every other engine in this codebase already uses for safety
observation.

Only OSError-class failures during those stat calls are converted to
DestinationConflict.OBSERVATION_FAILED. A programming/configuration error
(ValueError, KeyError, AssertionError, or anything else not raised by the
stat calls themselves) is never caught here and propagates normally -- this
module does not swallow bugs as if they were ordinary filesystem conflicts.
"""

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from file_agent.destination._paths import (
    has_unsafe_reparse_ancestor,
    resolve_for_containment,
)
from file_agent.scanner import SandboxRoot


class DestinationConflict(str, Enum):
    """Every destination-side condition inspect_destination can report, in
    the fixed order they are checked -- first match wins, mirroring
    TransactionEngine's own long-established fail-fast precondition-chain
    style."""

    NONE = "none"
    SOURCE_EQUALS_DESTINATION = "source_equals_destination"
    BASENAME_MISMATCH = "basename_mismatch"
    OUTSIDE_SANDBOX = "outside_sandbox"
    UNSAFE_REPARSE_POINT = "unsafe_reparse_point"
    PARENT_MISSING = "parent_missing"
    ALREADY_OCCUPIED = "already_occupied"
    OBSERVATION_FAILED = "observation_failed"


@dataclass(frozen=True, slots=True)
class DestinationInspection:
    destination_path: Path
    conflict: DestinationConflict


def inspect_destination(
    sandbox_root: SandboxRoot, source_path: Path, destination_path: Path
) -> DestinationInspection:
    """Read-only. Checks, in order:

    1. source_path resolves to the same place as destination_path -> SOURCE_EQUALS_DESTINATION
    2. source_path.name != destination_path.name -> BASENAME_MISMATCH
    3. destination_path does not resolve within sandbox_root -> OUTSIDE_SANDBOX
    4. destination_path's parent, or any ancestor up to sandbox_root, is a
       symlink/junction -> UNSAFE_REPARSE_POINT
    5. destination_path's parent does not exist as a directory -> PARENT_MISSING
    6. destination_path exists, or is itself a (possibly dangling)
       symlink/junction -> ALREADY_OCCUPIED
    7. an unexpected OSError during any of the above -> OBSERVATION_FAILED
    8. otherwise -> NONE
    """
    try:
        source_resolved = resolve_for_containment(source_path)
        destination_resolved = resolve_for_containment(destination_path)
        if (
            source_resolved is not None
            and destination_resolved is not None
            and source_resolved == destination_resolved
        ):
            return DestinationInspection(
                destination_path, DestinationConflict.SOURCE_EQUALS_DESTINATION
            )

        if source_path.name != destination_path.name:
            return DestinationInspection(
                destination_path, DestinationConflict.BASENAME_MISMATCH
            )

        if destination_resolved is None or not destination_resolved.is_relative_to(
            sandbox_root.path
        ):
            return DestinationInspection(
                destination_path, DestinationConflict.OUTSIDE_SANDBOX
            )

        if has_unsafe_reparse_ancestor(destination_path.parent, sandbox_root.path):
            return DestinationInspection(
                destination_path, DestinationConflict.UNSAFE_REPARSE_POINT
            )

        if not destination_path.parent.is_dir():
            return DestinationInspection(
                destination_path, DestinationConflict.PARENT_MISSING
            )

        if (
            destination_path.exists()
            or destination_path.is_symlink()
            or os.path.isjunction(destination_path)
        ):
            return DestinationInspection(
                destination_path, DestinationConflict.ALREADY_OCCUPIED
            )
    except OSError:
        return DestinationInspection(
            destination_path, DestinationConflict.OBSERVATION_FAILED
        )

    return DestinationInspection(destination_path, DestinationConflict.NONE)
