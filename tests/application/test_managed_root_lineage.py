"""FA-015 round-2 regression: registration-generation lineage. Proves the
repository trace in the design doc's §10 -- a full scan NEVER reuses an
existing FileObservationRow by path, so remove-root -> re-register-same-path
-> rescan naturally produces a brand-new, correctly-scoped observation
without any new identity/dedup mechanism. Exact 8-step scenario from the
round-4-approved design's test matrix (§28)."""

from pathlib import Path

from file_agent.application import (
    ApplicationOutcomeStatus,
    FileAgentApplicationService,
)
from file_agent.application.dto import ApplicationRejectionReason
from file_agent.application.managed_roots import ManagedRootUnavailable
from file_agent.destination import PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY


def _make_root(tmp_path: Path, name: str) -> Path:
    folder = tmp_path / name
    folder.mkdir()
    for directory in PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY.values():
        (folder / directory).mkdir()
    return folder


def test_registration_generation_lineage_never_drifts(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    folder = _make_root(tmp_path, "Downloads")
    source = folder / "invoice.pdf"
    source.write_bytes(b"invoice content")

    # 1. Register R1, scan -> F1/D1.
    r1 = service.add_managed_root(folder)
    analysis1 = service.analyze_managed_root(r1.id)
    assert not isinstance(analysis1, ManagedRootUnavailable)
    d1 = analysis1.items[0].policy_decision_id
    f1 = analysis1.items[0].file_id

    # 2. Remove R1.
    service.remove_managed_root(r1.id)

    # 3. Register the same physical path as R2 -- a genuinely new id.
    r2 = service.add_managed_root(folder)
    assert r2.id != r1.id

    # 4. Rescan under R2 -- a NEW observation F2 is inserted, never reusing F1.
    analysis2 = service.analyze_managed_root(r2.id)
    assert not isinstance(analysis2, ManagedRootUnavailable)
    d2 = analysis2.items[0].policy_decision_id
    f2 = analysis2.items[0].file_id
    assert f2 != f1

    # 5. D1's lineage resolves to R1; D2's lineage resolves to R2.
    discovered1 = service._store.get_discovered_file(f1)
    discovered2 = service._store.get_discovered_file(f2)
    assert discovered1 is not None
    assert discovered2 is not None
    assert discovered1.managed_root_id == r1.id
    assert discovered2.managed_root_id == r2.id
    assert discovered1.managed_root_id != discovered2.managed_root_id

    # 6. apply_item(D1) is rejected, MANAGED_ROOT_NOT_ACTIVE (R1 inactive).
    result1 = service.apply_item(d1)
    assert result1.status is ApplicationOutcomeStatus.REJECTED
    assert (
        result1.reason_code == ApplicationRejectionReason.MANAGED_ROOT_NOT_ACTIVE.value
    )

    # 7. apply_item(D2) proceeds through to TransactionEngine (R2 active).
    result2 = service.apply_item(d2)
    assert result2.status is ApplicationOutcomeStatus.SUCCEEDED

    # 8. Reading D1's history afterward -- even after R2 exists and is
    #    active -- still reports R1, never R2; F1's managed_root_id is
    #    never observed to have changed.
    discovered1_again = service._store.get_discovered_file(f1)
    assert discovered1_again is not None
    assert discovered1_again.managed_root_id == r1.id


def test_two_roots_can_independently_contain_same_named_files(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    folder_a = _make_root(tmp_path, "A")
    (folder_a / "report.pdf").write_bytes(b"content a")
    folder_b = _make_root(tmp_path, "B")
    (folder_b / "report.pdf").write_bytes(b"content b")

    root_a = service.add_managed_root(folder_a)
    root_b = service.add_managed_root(folder_b)

    analysis_a = service.analyze_managed_root(root_a.id)
    analysis_b = service.analyze_managed_root(root_b.id)
    assert not isinstance(analysis_a, ManagedRootUnavailable)
    assert not isinstance(analysis_b, ManagedRootUnavailable)

    file_a = service._store.get_discovered_file(analysis_a.items[0].file_id)
    file_b = service._store.get_discovered_file(analysis_b.items[0].file_id)
    assert file_a is not None
    assert file_b is not None
    assert file_a.managed_root_id == root_a.id
    assert file_b.managed_root_id == root_b.id
    assert file_a.id != file_b.id


def test_repeated_full_scan_of_same_active_root_produces_distinct_generations(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    folder = _make_root(tmp_path, "Downloads")
    (folder / "report.pdf").write_bytes(b"content")
    root = service.add_managed_root(folder)

    first = service.analyze_managed_root(root.id)
    second = service.analyze_managed_root(root.id)
    assert not isinstance(first, ManagedRootUnavailable)
    assert not isinstance(second, ManagedRootUnavailable)

    first_file_id = first.items[0].file_id
    second_file_id = second.items[0].file_id
    assert first_file_id != second_file_id

    first_discovered = service._store.get_discovered_file(first_file_id)
    second_discovered = service._store.get_discovered_file(second_file_id)
    assert first_discovered is not None
    assert second_discovered is not None
    assert first_discovered.managed_root_id == root.id
    assert second_discovered.managed_root_id == root.id


def test_reanalysis_of_same_file_id_keeps_original_managed_root_id(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    """A later re-analysis generation of the SAME file_id (via
    analyze_file) keeps its original managed_root_id -- mirrors FA-013's
    existing .path-immutability proof, extended to this field."""
    folder = _make_root(tmp_path, "Downloads")
    source = folder / "report.pdf"
    source.write_bytes(b"content")
    root = service.add_managed_root(folder)

    analysis = service.analyze_managed_root(root.id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    file_id = analysis.items[0].file_id

    source.write_bytes(b"changed content, triggers re-analysis")
    reanalyzed = service.analyze_file(file_id)
    from file_agent.application.dto import AnalyzedItem

    assert isinstance(reanalyzed, AnalyzedItem)

    discovered = service._store.get_discovered_file(file_id)
    assert discovered is not None
    assert discovered.managed_root_id == root.id
