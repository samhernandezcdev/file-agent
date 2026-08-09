"""AppPaths — the only way to configure where File Agent's own state lives.

Never inferred from DiscoveredFile.path, SandboxRoot.path, or any scanned/
managed location — see docs/SAFETY.md's "Application-owned state" section.
"""

from dataclasses import dataclass
from pathlib import Path

DATABASE_FILENAME = "file-agent.sqlite3"


@dataclass(frozen=True, slots=True)
class AppPaths:
    """A validated application-data root and its derived database path.

    ``from_root`` is the only constructor. ``database_path`` is always
    ``root / "file-agent.sqlite3"`` — there is no way to independently
    configure an arbitrary database path that could point outside the
    authorized root.
    """

    root: Path
    database_path: Path

    @classmethod
    def from_root(cls, root: Path) -> "AppPaths":
        if not root.is_absolute():
            raise ValueError(f"application-data root must be absolute, got: {root!r}")
        return cls(root=root, database_path=root / DATABASE_FILENAME)
