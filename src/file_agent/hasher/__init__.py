"""Read-only streaming SHA-256 hashing for files discovered by the scanner.

Given a DiscoveredFile, computes its SHA-256 and produces a new immutable
snapshot via DiscoveredFile.with_sha256() — but only if a chain of identity
checks confirms the file being read is still the same file the scanner
observed, and that nothing changed while it was being read. Never mutates
the filesystem. See docs/SAFETY.md rule 3.
"""

from file_agent.hasher.hasher import FileHasher, hash_discovered_file
from file_agent.hasher.issues import HashIssue, HashIssueSeverity, HashIssueType
from file_agent.hasher.result import HashFailure, HashOutcome, HashSuccess

__all__ = [
    "FileHasher",
    "HashFailure",
    "HashIssue",
    "HashIssueSeverity",
    "HashIssueType",
    "HashOutcome",
    "HashSuccess",
    "hash_discovered_file",
]
