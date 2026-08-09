"""Core typed domain model for File Agent: read-only entities and events.

This layer performs no filesystem I/O and no mutation of any kind — see
docs/SAFETY.md. Scanning, classification, persistence, and the future
TransactionEngine are separate layers built on top of these types.
"""

from file_agent.domain.events import DomainEvent, EntityType, EventType
from file_agent.domain.file import DiscoveredFile
from file_agent.domain.proposal import DestinationCategory, FileCategory, FileProposal
from file_agent.domain.scan import ScanRun, ScanStatus

__all__ = [
    "DestinationCategory",
    "DiscoveredFile",
    "DomainEvent",
    "EntityType",
    "EventType",
    "FileCategory",
    "FileProposal",
    "ScanRun",
    "ScanStatus",
]
