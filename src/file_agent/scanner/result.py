"""ScanResult — the complete output of one directory scan."""

from dataclasses import dataclass

from file_agent.domain import DiscoveredFile, DomainEvent, ScanRun
from file_agent.scanner.issues import ScanIssue
from file_agent.structural_safety import StructuralProtection


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Everything produced by one scan: the run record, discoveries, events, and issues."""

    scan_run: ScanRun
    files: tuple[DiscoveredFile, ...]
    events: tuple[DomainEvent, ...]
    issues: tuple[ScanIssue, ...]
    protected_trees: tuple[StructuralProtection, ...]
    """FA-016: one entry per detected marker-based Protected Tree root this
    scan found and pruned -- never one entry per excluded file. Hard
    exclusions (kind=HARD_EXCLUSION) are never represented here; they
    remain silent at scan time, matching the pre-existing internal-artifact
    exclusion's own silent treatment."""
