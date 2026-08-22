"""FA-016 plan/apply structural protection: stale source state (item D),
destination protection (item E), stale destination state (item F), and the
normal-path regression proof (item N) -- "current filesystem state wins over
stale preview" in both directions (source and destination), and ordinary
eligible files remain completely unaffected."""

import os
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import pytest

from file_agent.application import (
    AnalysisFailure,
    ApplicationOutcomeStatus,
    FileAgentApplicationService,
)
from file_agent.application.dto import ApplicationRejectionReason
from file_agent.application.managed_roots import ManagedRootUnavailable
from file_agent.application.organization_plan import PlanStatus
from file_agent.scanner import SandboxRoot

# --- D. Stale source project state -------------------------------------------


def test_marker_appears_in_source_ancestor_after_preview_apply_rejects(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    project = sandbox_root.path / "project"
    project.mkdir()
    source = project / "notes.pdf"
    source.write_bytes(b"notes")
    analysis = service.analyze_managed_root(managed_root_id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    item = next(i for i in analysis.items if i.filename == "notes.pdf")

    plan = service.create_organization_plan([item.policy_decision_id])
    assert not isinstance(plan, ManagedRootUnavailable)
    assert plan.items[0].status is PlanStatus.READY

    (project / "pyproject.toml").write_text("x")

    result = service.apply_item(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == ApplicationRejectionReason.STRUCTURALLY_PROTECTED.value
    assert source.exists()


# --- E. Destination protection ------------------------------------------------


def test_destination_folder_already_a_project_preview_and_apply_reject(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    documents = sandbox_root.path / "Documents"
    (documents / "package.json").write_text("{}")
    source = make_source_file("invoice.pdf", content=b"pdf content")

    analysis = service.analyze_managed_root(managed_root_id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    item = analysis.items[0]

    plan = service.create_organization_plan([item.policy_decision_id])
    assert not isinstance(plan, ManagedRootUnavailable)
    assert plan.items[0].status is PlanStatus.PROTECTED
    assert (
        plan.items[0].reason_code.value
        == ApplicationRejectionReason.STRUCTURALLY_PROTECTED.value
    )

    result = service.apply_item(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == ApplicationRejectionReason.STRUCTURALLY_PROTECTED.value
    assert source.exists()
    assert not (documents / "invoice.pdf").exists()


# --- F. Stale destination state ----------------------------------------------


def test_marker_appears_in_destination_after_preview_apply_rejects_zero_mutation(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    source = make_source_file("invoice.pdf", content=b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    item = analysis.items[0]

    plan = service.create_organization_plan([item.policy_decision_id])
    assert not isinstance(plan, ManagedRootUnavailable)
    assert plan.items[0].status is PlanStatus.READY

    documents = sandbox_root.path / "Documents"
    (documents / "package.json").write_text("{}")

    result = service.apply_item(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == ApplicationRejectionReason.STRUCTURALLY_PROTECTED.value
    assert source.exists()
    assert not (documents / "invoice.pdf").exists()


# --- N. Normal-path regression ------------------------------------------------


def test_ordinary_source_and_destination_unchanged_behavior(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    source = make_source_file("invoice.pdf", content=b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    item = analysis.items[0]

    plan = service.create_organization_plan([item.policy_decision_id])
    assert not isinstance(plan, ManagedRootUnavailable)
    assert plan.items[0].status is PlanStatus.READY
    assert plan.summary.protected == 0

    result = service.apply_item(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.SUCCEEDED
    assert not source.exists()
    assert (sandbox_root.path / "Documents" / "invoice.pdf").exists()


# --- Marker disappearance permits organization again -------------------------


def test_marker_disappearance_permits_organization_again(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    """Documented, symmetric, honest limitation from the approved design:
    a marker that briefly existed and then disappeared is indistinguishable
    from one that never existed -- structural safety no longer rejects,
    subject to every other check."""
    project = sandbox_root.path / "project"
    project.mkdir()
    marker = project / "pyproject.toml"
    marker.write_text("x")
    source = project / "notes.pdf"
    source.write_bytes(b"notes")

    analysis = service.analyze_managed_root(managed_root_id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    # The file was never discovered at all -- pruned at scan time.
    assert analysis.items == ()

    marker.unlink()
    analysis_again = service.analyze_managed_root(managed_root_id)
    assert not isinstance(analysis_again, ManagedRootUnavailable)
    assert len(analysis_again.items) == 1
    item = analysis_again.items[0]

    result = service.apply_item(item.policy_decision_id)
    assert result.status is ApplicationOutcomeStatus.SUCCEEDED


# --- FA-017.7B.3: ScanStructuralContext invocation isolation -----------------


def test_analyze_file_does_not_reuse_analyze_managed_roots_structural_context(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    """A marker appearing in an ancestor AFTER analyze_managed_root
    completes must be caught when that SAME already-discovered file is
    later re-analyzed via analyze_file -- proving analyze_file constructs
    its own fresh ScanStructuralContext (per FA-017.7B.3's design), never
    reusing analyze_managed_root's already-discarded one. (A second
    analyze_managed_root call is not used here: the DirectoryScanner
    itself would prune the now-protected file at scan time before
    _analyze_discovered's own live check is ever reached, which would
    prove the scanner's separate pruning, not ScanStructuralContext's own
    invocation isolation -- analyze_file's live re-check of an existing
    DiscoveredFile row is the mechanism this property actually governs.)"""
    project = sandbox_root.path / "project"
    project.mkdir()
    source = project / "notes.pdf"
    source.write_bytes(b"notes")

    first = service.analyze_managed_root(managed_root_id)
    assert not isinstance(first, ManagedRootUnavailable)
    assert len(first.items) == 1
    file_id = first.items[0].file_id

    (project / "pyproject.toml").write_text("")

    result = service.analyze_file(file_id)

    # A fresh context re-derives `project`'s structural state from
    # scratch -- if analyze_managed_root's own (already-discarded) cache
    # had somehow leaked into analyze_file, this file would be wrongly
    # reported eligible again.
    assert isinstance(result, AnalysisFailure)
    assert result.reason_code == ApplicationRejectionReason.STRUCTURALLY_PROTECTED.value


def test_plan_create_and_analyze_use_independent_structural_contexts(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    """A marker appearing in an ancestor AFTER analyze_managed_root but
    BEFORE create_organization_plan must be caught by plan creation's own
    Phase 3.5 check -- proving build_organization_plan constructs its own
    fresh ScanStructuralContext, never reusing (or being contaminated by)
    analyze_managed_root's already-discarded one."""
    project = sandbox_root.path / "project"
    project.mkdir()
    source = project / "notes.pdf"
    source.write_bytes(b"notes")

    analysis = service.analyze_managed_root(managed_root_id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    item = analysis.items[0]

    (project / "pyproject.toml").write_text("")

    plan = service.create_organization_plan([item.policy_decision_id])
    assert not isinstance(plan, ManagedRootUnavailable)
    assert plan.items[0].status is PlanStatus.PROTECTED
    assert source.exists()


def test_plan_create_scans_shared_ancestor_once_for_many_selected_items(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FA-017.7B.3 Part 24/25: proves create_organization_plan's own bulk
    path (Phase 3.5) also benefits from ScanStructuralContext -- many
    selected items sharing one ancestor cause exactly one full directory
    listing of that ancestor, not one per item."""
    for i in range(10):
        make_source_file(f"file_{i:02d}.pdf", content=f"content {i}".encode())

    analysis = service.analyze_managed_root(managed_root_id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    assert len(analysis.items) == 10
    ids = [item.policy_decision_id for item in analysis.items]

    scandir_calls = {"count": 0}
    real_scandir = os.scandir

    def _counted_scandir(path):  # type: ignore[no-untyped-def]
        scandir_calls["count"] += 1
        return real_scandir(path)

    monkeypatch.setattr("file_agent.structural_safety.os.scandir", _counted_scandir)

    plan = service.create_organization_plan(ids)

    assert not isinstance(plan, ManagedRootUnavailable)
    assert plan.summary.protected == 0
    assert len(plan.items) == 10
    # Exactly 2 full directory listings total, not 20: one for the
    # shared SOURCE ancestor (the managed-root directory all 10 files
    # sit in, checked once by Phase 3.5's loop) and one for the shared
    # DESTINATION ancestor (the "Documents" folder all 10 items resolve
    # to, checked once across Phase 4's 10 per-item destination checks)
    # -- each reused by every item that shares it, instead of being
    # listed fresh for every one of the 10 items against both ancestors
    # (which would be 20).
    assert scandir_calls["count"] == 2
