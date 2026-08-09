"""Recoverable per-file problems encountered while hashing.

Plain dataclasses, not domain entities — in-process return values with no
persistence/identity contract, same rationale as the scanner's ScanIssue.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class HashIssueSeverity(str, Enum):
    """How alarming an issue is for a human reviewing hashing results."""

    WARNING = "warning"
    """An environmental condition, a race, or a policy-driven refusal — NOT
    itself proof of a deliberate boundary violation."""

    CRITICAL = "critical"
    """A confirmed, evidenced sandbox-containment violation, or an internal bug."""


class HashIssueType(str, Enum):
    """What kind of problem was encountered. Each has one fixed severity — see
    the mapping in FileHasher; no type is ever contextually re-classified."""

    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"

    PATH_OUTSIDE_SANDBOX = "path_outside_sandbox"
    """CRITICAL. The path resolves outside the configured sandbox — a
    confirmed escape, established before any file is opened."""

    UNRESOLVABLE_PATH = "unresolvable_path"
    REPARSE_POINT_ENCOUNTERED = "reparse_point_encountered"
    UNSUPPORTED_ENTRY_TYPE = "unsupported_entry_type"
    METADATA_MISMATCH_BEFORE_HASH = "metadata_mismatch_before_hash"

    IDENTITY_MISMATCH_ON_OPEN = "identity_mismatch_on_open"
    """WARNING. The file identity (st_dev/st_ino) seen right after open()
    differs from the identity seen by the pre-open path check — an
    integrity/race failure, deliberately NOT classified with the same
    severity as a confirmed PATH_OUTSIDE_SANDBOX escape."""

    MODIFIED_DURING_HASH = "modified_during_hash"
    READ_FAILED = "read_failed"

    INTERNAL_ERROR = "internal_error"
    """CRITICAL. A bug in the hasher itself, not an anticipated filesystem
    condition — mirrors ScanIssueType.SCAN_ABORTED."""


@dataclass(frozen=True, slots=True)
class HashIssue:
    """A single recoverable problem encountered while hashing one path."""

    path: str
    issue_type: HashIssueType
    severity: HashIssueSeverity
    message: str
    detected_at: datetime
