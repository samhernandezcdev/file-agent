"""The ONLY place a restore temp-file name is derived. No caller-supplied
destination path is ever accepted anywhere in this package."""

from pathlib import Path
from uuid import uuid4

from file_agent.reserved_artifacts import RESTORE_TEMP_PREFIX


def new_restore_temp_path(target_path: Path) -> Path:
    """Staged in `target_path`'s own parent directory (inside the managed
    root, not app-owned storage) -- guarantees same-volume placement
    relative to `target_path`, which is what makes the final publish a
    genuine atomic, non-overwriting rename rather than a non-atomic
    cross-storage copy. UUID-named under the reserved
    RESTORE_TEMP_PREFIX namespace -- never trusted by identity by any
    future operation, and structurally excluded from organization scanning
    once FA-011.1 lands (see reserved_artifacts).
    """
    return target_path.parent / f"{RESTORE_TEMP_PREFIX}{uuid4().hex}.partial"
