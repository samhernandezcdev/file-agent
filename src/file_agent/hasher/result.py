"""HashOutcome — a tagged union of a trusted hash or a rejected attempt.

A tagged union (rather than one dataclass with optional fields) makes an
"impossible" state — both a hash and an issue, or neither — unrepresentable.
"""

from dataclasses import dataclass

from file_agent.domain import DiscoveredFile, DomainEvent
from file_agent.hasher.issues import HashIssue


@dataclass(frozen=True, slots=True)
class HashSuccess:
    """A trusted hash: all identity checks passed."""

    original: DiscoveredFile
    hashed: DiscoveredFile
    event: DomainEvent


@dataclass(frozen=True, slots=True)
class HashFailure:
    """A rejected hash attempt. Any digest that may have been computed is discarded."""

    original: DiscoveredFile
    issue: HashIssue


HashOutcome = HashSuccess | HashFailure
