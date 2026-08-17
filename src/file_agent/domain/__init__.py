"""Core typed domain model for File Agent: read-only entities and events.

This layer performs no filesystem I/O and no mutation of any kind — see
docs/SAFETY.md. Scanning, classification, persistence, and the future
TransactionEngine are separate layers built on top of these types.
"""

from file_agent.domain.authorization import (
    ExecutionAuthorization,
    ExecutionAuthorizationKind,
)
from file_agent.domain.events import DomainEvent, EntityType, EventType
from file_agent.domain.file import DiscoveredFile
from file_agent.domain.human_review import (
    HumanReviewDecision,
    HumanReviewOutcome,
    ReviewSource,
)
from file_agent.domain.managed_root import ManagedRoot
from file_agent.domain.policy import PolicyDecision, PolicyOutcome
from file_agent.domain.proposal import DestinationCategory, FileCategory, FileProposal
from file_agent.domain.recovery import (
    CompletedMoveEvidence,
    RecoveryOperation,
    RecoveryRejectionCode,
    RecoveryRequest,
    RecoveryResult,
    RecoveryStatus,
    RestoreFromVaultRequest,
    ReverseMoveRequest,
    VaultCaptureEvidence,
)
from file_agent.domain.scan import ScanRun, ScanStatus
from file_agent.domain.transaction import (
    RejectionCode,
    TransactionOperation,
    TransactionRequest,
    TransactionResult,
    TransactionStatus,
)
from file_agent.domain.vault import (
    VaultCaptureRequest,
    VaultCaptureResult,
    VaultCaptureStatus,
    VaultObject,
    VaultRejectionCode,
)

__all__ = [
    "CompletedMoveEvidence",
    "DestinationCategory",
    "DiscoveredFile",
    "DomainEvent",
    "EntityType",
    "EventType",
    "ExecutionAuthorization",
    "ExecutionAuthorizationKind",
    "FileCategory",
    "FileProposal",
    "HumanReviewDecision",
    "HumanReviewOutcome",
    "ManagedRoot",
    "PolicyDecision",
    "PolicyOutcome",
    "RecoveryOperation",
    "RecoveryRejectionCode",
    "RecoveryRequest",
    "RecoveryResult",
    "RecoveryStatus",
    "RejectionCode",
    "RestoreFromVaultRequest",
    "ReverseMoveRequest",
    "ReviewSource",
    "ScanRun",
    "ScanStatus",
    "TransactionOperation",
    "TransactionRequest",
    "TransactionResult",
    "TransactionStatus",
    "VaultCaptureEvidence",
    "VaultCaptureRequest",
    "VaultCaptureResult",
    "VaultCaptureStatus",
    "VaultObject",
    "VaultRejectionCode",
]
