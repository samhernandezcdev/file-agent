"""SandboxRoot — a validated, canonical root the scanner is allowed to read within."""

from dataclasses import dataclass
from pathlib import Path

from file_agent.scanner._paths import is_reparse_point, is_unc_path


class SandboxRootError(ValueError):
    """Raised when a configured sandbox root fails validation. Never raised mid-scan."""


@dataclass(frozen=True, slots=True)
class SandboxRoot:
    """A validated sandbox root: absolute, resolved, existing, real directory, non-UNC.

    See SAFETY.md rule 3 — this is the actual security boundary the scanner
    enforces. `from_path` performs a specific validation order: it inspects
    the ORIGINAL, unresolved path for reparse-point status before calling
    `resolve()`, because resolving first would silently follow a
    symlink/junction root and lose the information needed to reject it.
    """

    path: Path

    @classmethod
    def from_path(cls, raw: Path) -> "SandboxRoot":
        """Validate and canonicalize `raw`. Raises SandboxRootError on any precondition failure."""
        if not raw.is_absolute():
            raise SandboxRootError(
                f"sandbox root must be an absolute path, got: {raw!r}"
            )
        if is_unc_path(raw):
            raise SandboxRootError(f"UNC sandbox roots are not supported: {raw!r}")
        if is_reparse_point(raw):
            raise SandboxRootError(
                f"sandbox root must not be a symlink, junction, or reparse point: {raw!r}"
            )
        try:
            resolved = raw.resolve(strict=True)
        except OSError as exc:
            raise SandboxRootError(
                f"sandbox root does not exist or cannot be resolved: {raw!r} ({exc})"
            ) from exc
        if not resolved.is_dir():
            raise SandboxRootError(f"sandbox root is not a directory: {resolved!r}")
        return cls(path=resolved)
