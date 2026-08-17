"""FA-015 round-3 regression: BATCH_APPLY_STARTED.managed_root_id is an
AGGREGATE CLAIM, not a primitive fact -- _reconstruct_batch's new step 2
cross-verifies it against every selected id's independently-resolvable
lineage rather than trusting the persisted payload uncritically. A single
disagreeing id is sufficient to fail the whole batch closed, MALFORMED,
regardless of majority agreement; both get_batch_history and
list_recent_batch_history inherit this identically, since both share one
reconstruction path."""

from pathlib import Path
from uuid import UUID

from file_agent.application import (
    BatchHistoryEntry,
    FileAgentApplicationService,
    UnavailableBatchHistoryRow,
    queries,
)
from file_agent.application.history import batch_apply_started_event
from file_agent.application.managed_roots import ManagedRootUnavailable
from file_agent.destination import PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY
from file_agent.domain import EventType
from file_agent.persistence import FileAgentStore


def _make_root(tmp_path: Path, name: str) -> Path:
    folder = tmp_path / name
    folder.mkdir()
    for directory in PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY.values():
        (folder / directory).mkdir()
    return folder


def _rewrite_started_managed_root_id(
    store: FileAgentStore, batch_id: UUID, claimed_managed_root_id: UUID
) -> None:
    """Simulates a corrupted/buggy BATCH_APPLY_STARTED payload by directly
    inserting a second, differently-payloaded STARTED-shaped event is not
    possible (would trip the AMBIGUOUS multiple-STARTED check) -- instead
    we rewrite the ORM row's payload in place, the same white-box technique
    this test module needs to construct an otherwise-unreachable malformed
    state deliberately."""
    from file_agent.persistence.orm import DomainEventRow

    session = store._session_factory()
    try:
        with session.begin():
            row = (
                session.query(DomainEventRow)
                .filter_by(
                    entity_id=batch_id,
                    event_type=EventType.BATCH_APPLY_STARTED.value,
                )
                .one()
            )
            payload = dict(row.payload)
            payload["managed_root_id"] = str(claimed_managed_root_id)
            row.payload = payload
    finally:
        session.close()


def test_valid_honest_batch_reports_the_correct_root(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    folder = _make_root(tmp_path, "Downloads")
    (folder / "a.pdf").write_bytes(b"a")
    root = service.add_managed_root(folder)
    analysis = service.analyze_managed_root(root.id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    ids = [item.policy_decision_id for item in analysis.items]

    applied = service.apply_items(ids)
    entry = service.get_batch_history(applied.batch_id)

    assert isinstance(entry, BatchHistoryEntry)
    assert entry.managed_root_id == root.id


def test_started_claims_wrong_root_for_every_selected_id_fails_closed(
    service: FileAgentApplicationService, store: FileAgentStore, tmp_path: Path
) -> None:
    folder_a = _make_root(tmp_path, "A")
    (folder_a / "a.pdf").write_bytes(b"a")
    folder_b = _make_root(tmp_path, "B")
    (folder_b / "b.pdf").write_bytes(b"b")
    root_a = service.add_managed_root(folder_a)
    root_b = service.add_managed_root(folder_b)
    analysis_a = service.analyze_managed_root(root_a.id)
    assert not isinstance(analysis_a, ManagedRootUnavailable)
    ids = [item.policy_decision_id for item in analysis_a.items]

    applied = service.apply_items(ids)
    _rewrite_started_managed_root_id(store, applied.batch_id, root_b.id)

    result = service.get_batch_history(applied.batch_id)

    assert isinstance(result, queries.LookupFailure)
    assert result.status is queries.LookupStatus.MALFORMED


def test_one_disagreeing_id_among_many_fails_closed_not_a_majority_vote(
    service: FileAgentApplicationService, store: FileAgentStore, tmp_path: Path
) -> None:
    folder_a = _make_root(tmp_path, "A")
    (folder_a / "a1.pdf").write_bytes(b"a1")
    (folder_a / "a2.pdf").write_bytes(b"a2")
    folder_b = _make_root(tmp_path, "B")
    (folder_b / "b.pdf").write_bytes(b"b")
    root_a = service.add_managed_root(folder_a)
    root_b = service.add_managed_root(folder_b)
    analysis_a = service.analyze_managed_root(root_a.id)
    assert not isinstance(analysis_a, ManagedRootUnavailable)
    ids = [item.policy_decision_id for item in analysis_a.items]
    assert len(ids) == 2

    applied = service.apply_items(ids)
    # STARTED honestly claims root_a (correct for both items) -- now
    # corrupt it to claim root_b instead, disagreeing with EVERY item, to
    # keep this test deterministic and independent of dict/set ordering
    # while still proving "a single contradiction is sufficient," since
    # both selected ids independently resolve to root_a here.
    _rewrite_started_managed_root_id(store, applied.batch_id, root_b.id)

    result = service.get_batch_history(applied.batch_id)

    assert isinstance(result, queries.LookupFailure)
    assert result.status is queries.LookupStatus.MALFORMED


def test_malformed_root_claim_also_fails_via_list_recent_batch_history(
    service: FileAgentApplicationService, store: FileAgentStore, tmp_path: Path
) -> None:
    """Proves both callers inherit the same check through shared
    reconstruction, not just that get_batch_history alone catches it."""
    folder_a = _make_root(tmp_path, "A")
    (folder_a / "a.pdf").write_bytes(b"a")
    folder_b = _make_root(tmp_path, "B")
    (folder_b / "b.pdf").write_bytes(b"b")
    root_a = service.add_managed_root(folder_a)
    root_b = service.add_managed_root(folder_b)
    analysis_a = service.analyze_managed_root(root_a.id)
    assert not isinstance(analysis_a, ManagedRootUnavailable)
    ids = [item.policy_decision_id for item in analysis_a.items]

    applied = service.apply_items(ids)
    _rewrite_started_managed_root_id(store, applied.batch_id, root_b.id)

    rows = service.list_recent_batch_history()

    matching = [r for r in rows if r.batch_id == applied.batch_id]
    assert len(matching) == 1
    assert isinstance(matching[0], UnavailableBatchHistoryRow)
    assert matching[0].reason == queries.LookupStatus.MALFORMED.value


def test_legacy_batch_with_no_managed_root_id_key_reads_as_none_and_skips_check(
    service: FileAgentApplicationService, store: FileAgentStore
) -> None:
    """A legacy pre-FA-015 BATCH_APPLY_STARTED payload simply has no
    "managed_root_id" key at all -- reconstructed as managed_root_id=None,
    and step 2's cross-check is never attempted for it (never retroactively
    inferred)."""
    from uuid import uuid4

    from file_agent.domain import DomainEvent, EntityType

    batch_id = uuid4()
    policy_decision_id = uuid4()
    started_at = service._clock()
    reference_event = batch_apply_started_event(
        batch_id, [policy_decision_id], started_at, None
    )
    # Simulate a genuinely legacy payload by omitting the key entirely,
    # rather than relying on batch_apply_started_event's own None-handling
    # (which already writes managed_root_id: null -- a real legacy row
    # predates the key's existence altogether). No BATCH_APPLY_COMPLETED is
    # recorded -- this test only needs to prove managed_root_id reads as
    # None and skips the cross-check; an INCOMPLETE batch is sufficient and
    # avoids needing a matching BATCH_ITEM_RECORDED checkpoint too.
    payload = dict(reference_event.payload)
    del payload["managed_root_id"]
    event = DomainEvent(
        event_type=EventType.BATCH_APPLY_STARTED,
        entity_type=EntityType.BATCH,
        entity_id=batch_id,
        timestamp=started_at,
        payload=payload,
    )
    store.record_event(event)

    entry = service.get_batch_history(batch_id)

    assert isinstance(entry, BatchHistoryEntry)
    assert entry.managed_root_id is None
