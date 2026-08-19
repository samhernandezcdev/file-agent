"""FA-017.2: the sole caller of managed_fs.create_directory_no_replace,
mirroring TransactionEngine/RecoveryEngine's existing role as the only
callers of managed_fs for their own mutation kinds -- application/ itself
is AST-guardrailed (tests/application/test_mutation_boundary.py) to never
import managed_fs directly, so this narrow module exists purely to satisfy
that boundary for the new mutation kind.

No prepare()/commit() split here, unlike TransactionEngine/RecoveryEngine:
those exist to decouple an expensive re-verification step (a full file
re-hash) from the actual mutation. Directory creation has no equivalent
step -- FileAgentApplicationService.prepare_destinations already performs
every required live safety check (live SandboxRoot resolution,
current-need authorization, find_structural_protection, inspect_leaf)
immediately before calling this function, so a second phase here would be
ceremony without a second consumer.
"""

from pathlib import Path

from file_agent.managed_fs import create_directory_no_replace


def prepare_destination_directory(path: Path) -> None:
    """Creates exactly one directory leaf at `path`. Raises FileExistsError/
    FileNotFoundError/OSError exactly as managed_fs.create_directory_no_
    replace does -- never caught or reinterpreted here; the caller owns
    all classification of what a raised exception means."""
    create_directory_no_replace(path)
