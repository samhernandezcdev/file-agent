"""Content-addressed path arithmetic -- the ONLY place a sha256 string
becomes a filesystem path.

There is no public function anywhere in vault_engine that accepts a
caller-supplied destination path: every path here is derived internally from
a digest the engine itself has just verified. This, combined with
_require_valid_sha256's defense-in-depth shape re-validation, is what makes
"caller cannot choose an arbitrary Vault path" / "no path traversal" true
structurally, not just by convention.
"""

import re
from pathlib import Path
from uuid import uuid4

from file_agent.persistence import AppPaths

_PREFIX_LEN = 2
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

OBJECTS_DIRNAME = "objects"
TMP_DIRNAME = "tmp"


def _require_valid_sha256(sha256: str) -> None:
    if not _SHA256_RE.fullmatch(sha256):
        raise ValueError(f"not a validated sha256 digest: {sha256!r}")


def object_relative_path(sha256: str) -> str:
    """POSIX-style, relative to vault_root -- suitable for a durable/portable
    audit-event payload (see VaultCaptureResult.vault_object_path)."""
    _require_valid_sha256(sha256)
    return f"{OBJECTS_DIRNAME}/{sha256[:_PREFIX_LEN]}/{sha256}"


def object_abs_path(app_paths: AppPaths, sha256: str) -> Path:
    _require_valid_sha256(sha256)
    return app_paths.vault_root / OBJECTS_DIRNAME / sha256[:_PREFIX_LEN] / sha256


def object_prefix_dir(app_paths: AppPaths, sha256: str) -> Path:
    _require_valid_sha256(sha256)
    return app_paths.vault_root / OBJECTS_DIRNAME / sha256[:_PREFIX_LEN]


def objects_root(app_paths: AppPaths) -> Path:
    return app_paths.vault_root / OBJECTS_DIRNAME


def tmp_dir(app_paths: AppPaths) -> Path:
    return app_paths.vault_root / TMP_DIRNAME


def new_temp_path(app_paths: AppPaths) -> Path:
    """UUID-named, never SHA-named -- the temp file's content is unverified
    at creation time, so naming it after a claimed-but-unproven SHA would be
    misleading. Always under vault_root/tmp/, guaranteeing same-volume
    placement relative to objects/ -- required for the publish rename to be
    meaningfully atomic."""
    return tmp_dir(app_paths) / f"{uuid4().hex}.partial"
