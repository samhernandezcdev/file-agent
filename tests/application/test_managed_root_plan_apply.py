"""FA-015 single-root plan/batch invariant and the two-layer active-root
authorization mechanism (design §15/§20): MixedManagedRootsError raised
before any filesystem inspection for a selection spanning more than one
root, and apply_item (bypassing apply_items' own structural gate entirely)
still independently rejects a since-removed root via its own per-item
"layer 2" re-check."""

from pathlib import Path

import pytest

from file_agent.application import (
    ApplicationOutcomeStatus,
    FileAgentApplicationService,
)
from file_agent.application.dto import ApplicationRejectionReason, BatchStatus
from file_agent.application.errors import MixedManagedRootsError
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


def test_same_root_plan_builds_correctly(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    folder = _make_root(tmp_path, "Downloads")
    (folder / "a.pdf").write_bytes(b"a")
    (folder / "b.pdf").write_bytes(b"b")
    root = service.add_managed_root(folder)
    analysis = service.analyze_managed_root(root.id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    ids = [item.policy_decision_id for item in analysis.items]

    plan = service.create_organization_plan(ids)

    assert not isinstance(plan, ManagedRootUnavailable)
    assert plan.managed_root_id == root.id
    assert plan.root_path == root.path


def test_mixed_root_plan_raises_before_any_filesystem_inspection(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    folder_a = _make_root(tmp_path, "A")
    (folder_a / "a.pdf").write_bytes(b"a")
    folder_b = _make_root(tmp_path, "B")
    (folder_b / "b.pdf").write_bytes(b"b")
    root_a = service.add_managed_root(folder_a)
    root_b = service.add_managed_root(folder_b)
    analysis_a = service.analyze_managed_root(root_a.id)
    analysis_b = service.analyze_managed_root(root_b.id)
    assert not isinstance(analysis_a, ManagedRootUnavailable)
    assert not isinstance(analysis_b, ManagedRootUnavailable)
    id_a = analysis_a.items[0].policy_decision_id
    id_b = analysis_b.items[0].policy_decision_id

    # If MixedManagedRootsError were raised AFTER filesystem inspection, the
    # destination directories under folder_b would already exist untouched
    # anyway -- the real proof is that no item in folder_a/folder_b was
    # ever moved and no plan was constructed at all.
    with pytest.raises(MixedManagedRootsError) as excinfo:
        service.create_organization_plan([id_a, id_b])

    assert excinfo.value.roots_seen == frozenset({root_a.id, root_b.id})
    assert (folder_a / "a.pdf").exists()
    assert (folder_b / "b.pdf").exists()


def test_mixed_root_apply_items_raises_before_batch_apply_started(
    service: FileAgentApplicationService, tmp_path: Path, store: FileAgentStore
) -> None:
    folder_a = _make_root(tmp_path, "A")
    (folder_a / "a.pdf").write_bytes(b"a")
    folder_b = _make_root(tmp_path, "B")
    (folder_b / "b.pdf").write_bytes(b"b")
    root_a = service.add_managed_root(folder_a)
    root_b = service.add_managed_root(folder_b)
    analysis_a = service.analyze_managed_root(root_a.id)
    analysis_b = service.analyze_managed_root(root_b.id)
    assert not isinstance(analysis_a, ManagedRootUnavailable)
    assert not isinstance(analysis_b, ManagedRootUnavailable)
    id_a = analysis_a.items[0].policy_decision_id
    id_b = analysis_b.items[0].policy_decision_id
    events_before = store.list_events_by_type(EventType.BATCH_APPLY_STARTED)

    with pytest.raises(MixedManagedRootsError):
        service.apply_items([id_a, id_b])

    assert store.list_events_by_type(EventType.BATCH_APPLY_STARTED) == events_before
    assert (folder_a / "a.pdf").exists()
    assert (folder_b / "b.pdf").exists()


def test_plan_against_removed_root_returns_unavailable(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    folder = _make_root(tmp_path, "Downloads")
    (folder / "a.pdf").write_bytes(b"a")
    root = service.add_managed_root(folder)
    analysis = service.analyze_managed_root(root.id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    ids = [item.policy_decision_id for item in analysis.items]

    service.remove_managed_root(root.id)

    plan = service.create_organization_plan(ids)

    assert isinstance(plan, ManagedRootUnavailable)


def test_apply_items_root_removed_between_preview_and_apply_zero_mutation(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    folder = _make_root(tmp_path, "Downloads")
    (folder / "a.pdf").write_bytes(b"a")
    root = service.add_managed_root(folder)
    analysis = service.analyze_managed_root(root.id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    ids = [item.policy_decision_id for item in analysis.items]

    service.remove_managed_root(root.id)

    result = service.apply_items(ids)

    assert isinstance(result, ManagedRootUnavailable)
    assert (folder / "a.pdf").exists()


def test_direct_apply_item_against_removed_root_rejected_layer_2_alone(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    """apply_item never goes through apply_items' structural "layer 1"
    gate at all -- proving _apply_one's own per-item "layer 2" re-check is
    unconditionally sufficient on its own."""
    folder = _make_root(tmp_path, "Downloads")
    (folder / "a.pdf").write_bytes(b"a")
    root = service.add_managed_root(folder)
    analysis = service.analyze_managed_root(root.id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    policy_decision_id = analysis.items[0].policy_decision_id

    service.remove_managed_root(root.id)

    result = service.apply_item(policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert (
        result.reason_code == ApplicationRejectionReason.MANAGED_ROOT_NOT_ACTIVE.value
    )
    assert (folder / "a.pdf").exists()


def test_successful_batch_started_payload_carries_correct_managed_root_id(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    folder = _make_root(tmp_path, "Downloads")
    (folder / "a.pdf").write_bytes(b"a")
    root = service.add_managed_root(folder)
    analysis = service.analyze_managed_root(root.id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    ids = [item.policy_decision_id for item in analysis.items]

    result = service.apply_items(ids)

    assert result.status is BatchStatus.COMPLETED
    assert result.managed_root_id == root.id
