"""Smoke test for the public surface of file_agent.domain."""

from file_agent import domain


def test_all_exports_are_importable() -> None:
    assert set(domain.__all__) == {
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
    }
    for name in domain.__all__:
        assert hasattr(domain, name)
