"""The sole managed-root filesystem mutation primitives in the codebase --
shared by TransactionEngine (MOVE), RecoveryEngine (REVERSE_MOVE,
RESTORE_FROM_VAULT), and destination_engine (CREATE_DIRECTORY, FA-017.2).
Exactly three functions, nothing else. Neither hashes, verifies, or decides
anything -- callers own preconditions and verification; this module only
performs the raw OS-level operation, as narrowly as possible.

move_no_replace() -- Path.rename(), not os.replace(), not shutil.move().
os.replace() succeeds by overwriting, which is the opposite of "must never
overwrite"; shutil.move() silently falls back to copy+delete on a failed
rename, which is not atomic and can leave a partial destination file. On
Windows, Path.rename() raises OSError if the destination already exists
rather than overwriting it -- a genuine OS-level backstop, not just
documentation.

write_new_file() -- open(path, "xb"), not open(path, "wb") preceded by a
separate existence check. "xb" (O_CREAT|O_EXCL under the hood) is an atomic
"must not already exist" primitive: the OS itself refuses if `path` already
exists, closing the check-then-open TOCTOU a separate .exists() guard would
leave open (another process could create `path` between the check and the
open; "wb" would then silently truncate and overwrite it). open(..., "wb")
is banned as a managed-root file-creation primitive throughout this module.

create_directory_no_replace() -- Path.mkdir() with no parents=True and no
exist_ok=True. Creates exactly one directory leaf; raises FileExistsError
if anything already occupies that path (directory, file, or reparse point
alike -- this function never inspects what's there, only the caller does)
and FileNotFoundError if the parent does not already exist. No recursive
parent creation, ever -- see destination/rules.py's fixed, one-level
category-folder mapping, the only shape this is ever used for.

No delete/unlink/cleanup primitive exists here, deliberately -- see
recovery_engine's own docs for why RESTORE_FROM_VAULT's failure paths leave
their staging artifact in place rather than removing it.
"""

from collections.abc import Iterable
from pathlib import Path


def move_no_replace(source: Path, destination: Path) -> None:
    """Performs the actual same-volume rename. Raises OSError on failure --
    callers must translate that into a FAILED-shaped result, never retry
    silently, never fall back to another primitive."""
    source.rename(destination)


def write_new_file(path: Path, chunks: Iterable[bytes]) -> int:
    """Creates a BRAND NEW file at `path` via exclusive creation. Raises
    FileExistsError if `path` already exists -- propagated, not caught;
    callers decide how to handle it. Returns bytes written."""
    bytes_written = 0
    with open(path, "xb") as handle:
        for chunk in chunks:
            handle.write(chunk)
            bytes_written += len(chunk)
    return bytes_written


def create_directory_no_replace(path: Path) -> None:
    """Creates exactly one directory leaf at `path`. Raises FileExistsError
    if anything already exists there (directory, file, or reparse point --
    never inspected here, never replaced). Raises FileNotFoundError if the
    parent does not exist. Never creates parents (no parents=True), never
    treats an existing directory as success (no exist_ok=True). Callers own
    all containment/safety verification and all interpretation of what an
    existing entry means -- this performs only the raw OS-level mkdir."""
    path.mkdir()
