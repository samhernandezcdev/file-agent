"""managed_fs -- the single, narrow, audited boundary for managed-root
filesystem mutation, shared by TransactionEngine, RecoveryEngine, and
destination_engine (FA-017.2). See managed_fs.operations for the three
approved primitives and docs/SAFETY.md.
"""

from file_agent.managed_fs.operations import (
    create_directory_no_replace,
    move_no_replace,
    write_new_file,
)

__all__ = [
    "create_directory_no_replace",
    "move_no_replace",
    "write_new_file",
]
