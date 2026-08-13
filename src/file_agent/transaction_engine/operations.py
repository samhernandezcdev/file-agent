"""The sole mutation-primitive call site in this package (and, per the
repo-wide mutation-boundary guardrail, in the whole codebase outside
persistence's own allow-listed app-data mkdir).

Path.rename() -- not os.replace(), not shutil.move(). See engine.py's
docstring for the full reasoning: os.replace() succeeds by overwriting,
which is the opposite of "must never overwrite"; shutil.move() silently
falls back to copy+delete on a failed rename, which is not atomic and can
leave a partial destination file. On Windows, Path.rename() raises OSError
if the destination already exists rather than overwriting it -- a genuine
OS-level backstop, not just documentation.
"""

from pathlib import Path


def move(source: Path, destination: Path) -> None:
    """Performs the actual same-volume rename. Raises OSError on failure --
    callers must translate that into TransactionStatus.FAILED, never retry
    silently, never fall back to another primitive."""
    source.rename(destination)
