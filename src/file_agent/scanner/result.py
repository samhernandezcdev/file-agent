"""ScanResult — the complete output of one directory scan."""

from dataclasses import dataclass

from file_agent.domain import DiscoveredFile, DomainEvent, ScanRun
from file_agent.scanner.issues import ScanIssue


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Everything produced by one scan: the run record, discoveries, events, and issues."""

    scan_run: ScanRun
    files: tuple[DiscoveredFile, ...]
    events: tuple[DomainEvent, ...]
    issues: tuple[ScanIssue, ...]
