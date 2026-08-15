"""FileAgent-owned internal artifact naming conventions.

Zero dependencies, zero I/O -- importable by both low-level packages
(scanner) and high-level packages (recovery_engine) without inverting
either package's place in the dependency graph. This is the one place any
reserved FileAgent-internal-artifact naming convention is defined.
"""

RESTORE_TEMP_PREFIX = ".file_agent_restore."
"""Reserved prefix for RecoveryEngine's RESTORE_FROM_VAULT staging
artifacts. See recovery_engine.restore_paths.new_restore_temp_path."""


def is_file_agent_internal_artifact(name: str) -> bool:
    """True if `name` (a bare filename, not a path) matches a reserved
    FileAgent-internal-artifact naming convention and must never be treated
    as user-managed content by scanning/classification/organization.
    """
    return name.startswith(RESTORE_TEMP_PREFIX)
