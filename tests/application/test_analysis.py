"""Analysis flow: analyze_managed_root()/analyze_file() coordinate
DiscoveredFile -> FileHasher -> ClassificationResult -> FileProposal ->
PolicyDecision without the caller ever touching those engines directly."""

from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from file_agent.application import (
    AnalysisFailure,
    AnalyzedItem,
    FileAgentApplicationService,
)
from file_agent.domain import EntityType, EventType, FileCategory, PolicyOutcome
from file_agent.persistence import FileAgentStore


def test_document_produces_auto_end_to_end(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("report.pdf", content=b"pdf content")

    result = service.analyze_managed_root(managed_root_id)

    assert result.files_discovered == 1
    assert result.failures == ()
    assert len(result.items) == 1
    item = result.items[0]
    assert item.category is FileCategory.DOCUMENT
    assert item.policy_outcome is PolicyOutcome.AUTO
    assert item.requires_review is False


def test_unknown_extension_requires_review(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("mystery.xyz123", content=b"???")

    result = service.analyze_managed_root(managed_root_id)

    assert len(result.items) == 1
    item = result.items[0]
    assert item.category is FileCategory.UNKNOWN
    assert item.proposed_destination_category is None
    assert item.policy_outcome is PolicyOutcome.REVIEW
    assert item.requires_review is True


def test_hash_failure_produces_analysis_failure_and_scan_continues(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good = make_source_file("good.pdf", content=b"fine")
    vanishing = make_source_file("vanishing.pdf", content=b"gone soon")

    # analyze_managed_root() persists the full scan (discovering both files)
    # before hashing any of them -- delete "vanishing.pdf" in that exact
    # gap, via the seam record_scan() already provides, so the scan
    # genuinely discovers both files and only the per-file hash step fails
    # for the one that vanished afterward.
    real_record_scan = store.record_scan

    def _record_scan_then_delete(result: object) -> None:
        real_record_scan(result)  # type: ignore[arg-type]
        vanishing.unlink()

    monkeypatch.setattr(store, "record_scan", _record_scan_then_delete)

    result = service.analyze_managed_root(managed_root_id)

    assert result.files_discovered == 2
    assert len(result.failures) == 1
    assert result.failures[0].path == vanishing
    assert len(result.items) == 1
    assert result.items[0].path == good


def test_every_analysis_stage_persists_its_event(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("report.pdf", content=b"pdf content")

    result = service.analyze_managed_root(managed_root_id)
    item = result.items[0]

    file_events = store.list_events(EntityType.FILE, item.file_id)
    file_event_types = {e.event_type for e in file_events}
    assert EventType.FILE_DISCOVERED in file_event_types
    assert EventType.FILE_HASHED in file_event_types
    assert EventType.FILE_CLASSIFIED in file_event_types

    proposal_events = store.list_events(EntityType.PROPOSAL, item.proposal_id)
    assert any(e.event_type is EventType.PROPOSAL_CREATED for e in proposal_events)

    policy_events = store.list_events(
        EntityType.POLICY_DECISION, item.policy_decision_id
    )
    assert any(e.event_type is EventType.POLICY_EVALUATED for e in policy_events)


def test_analyze_file_on_unknown_id_returns_failure_not_exception(
    service: FileAgentApplicationService,
) -> None:
    result = service.analyze_file(uuid4())

    assert isinstance(result, AnalysisFailure)
    assert result.path is None
    assert result.reason_code == "file_not_found"


def test_analyze_file_reanalyzes_an_already_discovered_file(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("report.pdf", content=b"pdf content")
    first_scan = service.analyze_managed_root(managed_root_id)
    file_id = first_scan.items[0].file_id

    result = service.analyze_file(file_id)

    assert isinstance(result, AnalyzedItem)
    assert result.file_id == file_id
    assert result.category is FileCategory.DOCUMENT
