"""Smoke test for the public surface of file_agent.domain."""

from file_agent import domain


def test_all_exports_are_importable() -> None:
    assert set(domain.__all__) == {
        "DestinationCategory",
        "DiscoveredFile",
        "DomainEvent",
        "EntityType",
        "EventType",
        "FileCategory",
        "FileProposal",
        "PolicyDecision",
        "PolicyOutcome",
        "ScanRun",
        "ScanStatus",
    }
    for name in domain.__all__:
        assert hasattr(domain, name)
