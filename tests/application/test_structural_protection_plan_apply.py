"""FA-016 plan/apply structural protection: stale source state (item D),
destination protection (item E), stale destination state (item F), and the
normal-path regression proof (item N) -- "current filesystem state wins over
stale preview" in both directions (source and destination), and ordinary
eligible files remain completely unaffected."""

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from file_agent.application import (
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
