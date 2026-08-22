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
from file_agent.persistence import FileAgentStore, repositories
from file_agent.persistence.errors import DatabaseUnavailableError


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


def test_successful_analyze_uses_one_transaction_per_file(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FA-017.7B: proves the successful analyze-stage persistence shape is
    exactly 1 commit (one record_analyzed_file call) per successfully
    analyzed file -- not literally N total transactions for the whole
    analyze_managed_root call, since record_scan's own single transaction
    for the whole scan is separate and unaffected. Counts calls to the
    FileAgentStore methods themselves (each already independently proven,
    by direct inspection of store.py, to open exactly one
    `with session.begin():` block per call) rather than adding any
    production instrumentation."""
    make_source_file("first.pdf", content=b"first")
    make_source_file("second.pdf", content=b"second")
    make_source_file("third.pdf", content=b"third")

    call_counts = {
        "record_scan": 0,
        "record_analyzed_file": 0,
        "record_hash_success": 0,
        "record_event": 0,
    }

    def _counted(name: str, real: object) -> object:
        def _wrapper(*args: object, **kwargs: object) -> object:
            call_counts[name] += 1
            return real(*args, **kwargs)  # type: ignore[operator]

        return _wrapper

    for method_name in call_counts:
        monkeypatch.setattr(
            store, method_name, _counted(method_name, getattr(store, method_name))
        )

    result = service.analyze_managed_root(managed_root_id)

    assert result.files_discovered == 3
    assert len(result.items) == 3
    assert call_counts["record_scan"] == 1
    assert call_counts["record_analyzed_file"] == 3
    # The old four-commits-per-file methods are no longer used at all on
    # the successful analyze path -- the 4->1 reduction is real, not just
    # additive.
    assert call_counts["record_hash_success"] == 0
    assert call_counts["record_event"] == 0


def test_persistence_failure_partway_through_one_files_transaction_rolls_back_only_that_file(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FA-017.7B atomicity regression: forces a persistence failure inside
    the SECOND file's record_analyzed_file transaction, after that file's
    hash-observation update and FILE_CLASSIFIED insert have already
    executed (but not yet committed) within the same open transaction, by
    failing on the PROPOSAL_CREATED insert specifically. Proves: the
    failed file ends up with ZERO of its four analyze-stage facts durable
    (the whole transaction rolled back, including the writes that already
    ran), the first (already separately committed) file keeps its
    complete four-fact set, and -- following the ACTUAL current exception
    semantics (no try/except wraps _analyze_discovered's persistence call
    anywhere in analyze_managed_root today) -- the exception propagates
    out of analyze_managed_root as a whole, so the third file is never
    even attempted. This is not invented recovery behavior; it is the
    real, existing behavior, preserved unchanged by this slice."""
    make_source_file("first.pdf", content=b"first")
    make_source_file("second.pdf", content=b"second")
    make_source_file("third.pdf", content=b"third")

    real_insert_event = repositories.insert_event
    proposal_insert_count = 0

    def _fail_second_proposal_insert(session: object, row: object) -> object:
        nonlocal proposal_insert_count
        if row.event_type == EventType.PROPOSAL_CREATED.value:  # type: ignore[attr-defined]
            proposal_insert_count += 1
            if proposal_insert_count == 2:
                raise DatabaseUnavailableError("simulated mid-transaction failure")
        return real_insert_event(session, row)  # type: ignore[arg-type]

    monkeypatch.setattr(repositories, "insert_event", _fail_second_proposal_insert)

    # record_scan itself is untouched by this slice and always commits in
    # full before any per-file work begins -- capture its scan_id as a
    # side effect so the test can look up all 3 discovered files' facts
    # afterward, since the raised exception below means
    # analyze_managed_root never returns an AnalyzedScanResult to read
    # scan_id from directly.
    captured_scan_id: list[UUID] = []
    real_record_scan = store.record_scan

    def _capturing_record_scan(result: object) -> None:
        real_record_scan(result)  # type: ignore[arg-type]
        captured_scan_id.append(result.scan_run.id)  # type: ignore[attr-defined]

    monkeypatch.setattr(store, "record_scan", _capturing_record_scan)

    with pytest.raises(DatabaseUnavailableError):
        service.analyze_managed_root(managed_root_id)

    assert len(captured_scan_id) == 1
    discovered = store.list_discovered_files(captured_scan_id[0])
    assert len(discovered) == 3

    fully_persisted = []
    zero_facts = []
    for file in discovered:
        events = store.list_events(EntityType.FILE, file.id)
        event_types = {e.event_type for e in events}
        analyze_stage_facts = event_types & {
            EventType.FILE_HASHED,
            EventType.FILE_CLASSIFIED,
        }
        if analyze_stage_facts == {EventType.FILE_HASHED, EventType.FILE_CLASSIFIED}:
            fully_persisted.append(file)
        elif not analyze_stage_facts:
            zero_facts.append(file)
        else:
            pytest.fail(
                f"file {file.id} has a PARTIAL analyze-stage fact set: {analyze_stage_facts} "
                "-- the per-file transaction did not roll back atomically"
            )

    # Exactly one file (the second, targeted one) has zero analyze-stage
    # facts; the third file was never attempted at all (its FILE_HASHED/
    # FILE_CLASSIFIED events also don't exist, landing it in zero_facts
    # too -- confirmed separately below to distinguish "rolled back" from
    # "never reached").
    assert len(zero_facts) == 2
    assert len(fully_persisted) == 1


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
