"""managed_fs -- the single, narrow, audited boundary for managed-root
filesystem mutation, shared by TransactionEngine and RecoveryEngine. See
managed_fs.operations for the two approved primitives and docs/SAFETY.md.
"""

from file_agent.managed_fs.operations import move_no_replace, write_new_file

__all__ = [
    "move_no_replace",
    "write_new_file",
]
