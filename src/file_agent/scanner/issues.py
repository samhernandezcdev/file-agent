"""Recoverable per-entry problems encountered during a scan.

Plain dataclasses, not domain entities: these are in-process return values
with no persistence/identity contract, so they don't reuse the domain
layer's Pydantic/``extra="forbid"`` pattern.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ScanIssueSeverity(str, Enum):
    """How alarming an issue is for a human reviewing scan results."""

    INFO = "info"
    """Policy-driven skip, working as intended (e.g. a symlink not followed)."""

    WARNING = "warning"
    """Recoverable, not a security concern (races, permissions, unresolvable references)."""

    CRITICAL = "critical"
    """A confirmed sandbox-containment violation, successfully blocked."""


class ScanIssueType(str, Enum):
    """What kind of problem was encountered."""

    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"
    STAT_FAILED = "stat_failed"
    SYMLINK_NOT_FOLLOWED = "symlink_not_followed"
    JUNCTION_NOT_FOLLOWED = "junction_not_followed"
    UNSUPPORTED_REPARSE_POINT = "unsupported_reparse_point"
    UNRESOLVABLE_REFERENCE = "unresolvable_reference"
    """A symlink/junction whose target could not be resolved. Skipped fail-closed,
    but NOT the same as a confirmed escape — containment was never evaluated."""

    SANDBOX_ESCAPE_ATTEMPT = "sandbox_escape_attempt"
    """A symlink/junction whose target resolved successfully AND is confirmed
    to be outside the sandbox. Reserved for this specific, evidenced case."""

    UNSUPPORTED_ENTRY_TYPE = "unsupported_entry_type"
    SCAN_ABORTED = "scan_aborted"
    """A root-level fatal condition. The only issue type that drives status=FAILED."""


@dataclass(frozen=True, slots=True)
class ScanIssue:
    """A single recoverable problem encountered while scanning one path."""

    path: str
    issue_type: ScanIssueType
    severity: ScanIssueSeverity
    message: str
    detected_at: datetime
