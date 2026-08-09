"""Read-only recursive directory scanner. See docs/SAFETY.md rule 3.

Discovers files inside a validated SandboxRoot and produces DiscoveredFile /
DomainEvent instances. Never mutates the filesystem.
"""

from file_agent.scanner.issues import ScanIssue, ScanIssueSeverity, ScanIssueType
from file_agent.scanner.result import ScanResult
from file_agent.scanner.sandbox_root import SandboxRoot, SandboxRootError
from file_agent.scanner.scanner import DirectoryScanner, scan_sandbox

__all__ = [
    "DirectoryScanner",
    "SandboxRoot",
    "SandboxRootError",
    "ScanIssue",
    "ScanIssueSeverity",
    "ScanIssueType",
    "ScanResult",
    "scan_sandbox",
]
