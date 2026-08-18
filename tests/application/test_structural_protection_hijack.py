"""FA-016 round-5 adversarial regressions: ancestor and leaf reparse-point
hijacks (items G, H, I, J from the review's required test matrix). Every
scenario registers/discovers a genuinely safe path, then -- WITHOUT
touching the ManagedRoot registration itself -- replaces an ancestor (or
the candidate leaf) with a junction to an unrelated (or app-data) external
location, so the original path STRING is unchanged but now silently
resolves elsewhere. Every live call site must catch this via
find_structural_protection's fail-closed reference inspection, never
following the junction."""

import subprocess
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from file_agent.application import (
    ApplicationOutcomeStatus,
    FileAgentApplicationService,
)
from file_agent.application.dto import (
    AnalysisFailure,
    ApplicationRejectionReason,
    BatchApplyResult,
)
from file_agent.application.managed_roots import ManagedRootUnavailable
from file_agent.persistence import AppPaths
from file_agent.scanner import SandboxRoot


def _make_junction(link: Path, target: Path) -> None:
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
    )


def _hijack_ancestor(ancestor: Path, tmp_path: Path, external_name: str) -> Path:
    """Replaces `ancestor` with a junction to a fresh, unrelated external
    directory -- the registered path string is unchanged; only what it
    resolves to has silently changed."""
    import shutil

    moved_aside = tmp_path / f"{ancestor.name}_original_contents"
    shutil.move(str(ancestor), str(moved_aside))
    external_target = tmp_path / external_name
    external_target.mkdir()
    _make_junction(ancestor, external_target)
    return external_target


# --- G. Source ancestor hijack ------------------------------------------------


def test_source_ancestor_hijack_analyze_file_rejects_before_hash(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    tmp_path: Path,
) -> None:
    ordinary = sandbox_root.path / "ordinary"
    ordinary.mkdir()
    source = ordinary / "invoice.pdf"
    source.write_bytes(b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    item = analysis.items[0]

    external_target = _hijack_ancestor(ordinary, tmp_path, "external_g")

    result = service.analyze_file(item.file_id)

    assert isinstance(result, AnalysisFailure)
    assert result.reason_code == ApplicationRejectionReason.STRUCTURALLY_PROTECTED.value
    assert not any(external_target.rglob("*"))


def test_source_ancestor_hijack_apply_rejects_zero_mutation(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    tmp_path: Path,
) -> None:
    ordinary = sandbox_root.path / "ordinary"
    ordinary.mkdir()
    source = ordinary / "invoice.pdf"
    source.write_bytes(b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    item = analysis.items[0]

    external_target = _hijack_ancestor(ordinary, tmp_path, "external_g2")

    single = service.apply_item(item.policy_decision_id)
    assert single.status is ApplicationOutcomeStatus.REJECTED
    assert single.reason_code == ApplicationRejectionReason.STRUCTURALLY_PROTECTED.value

    batch = service.apply_items([item.policy_decision_id])
    assert isinstance(batch, BatchApplyResult)
    assert batch.items[0].status.value == "not_applied"
    assert not any(external_target.rglob("*"))


# --- H. Destination ancestor hijack -------------------------------------------


def test_destination_ancestor_hijack_apply_rejects(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    tmp_path: Path,
) -> None:
    source = make_source_file("invoice.pdf", content=b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    item = analysis.items[0]

    plan = service.create_organization_plan([item.policy_decision_id])
    assert not isinstance(plan, ManagedRootUnavailable)

    documents = sandbox_root.path / "Documents"
    external_target = _hijack_ancestor(documents, tmp_path, "external_h")

    result = service.apply_item(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == ApplicationRejectionReason.STRUCTURALLY_PROTECTED.value
    assert source.exists()
    assert not any(external_target.rglob("*"))


# --- I. App-data redirect -----------------------------------------------------


def test_ancestor_redirect_toward_app_data_root_rejects_untouched(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
) -> None:
    app_paths.root.mkdir(parents=True, exist_ok=True)
    ordinary = sandbox_root.path / "ordinary"
    ordinary.mkdir()
    source = ordinary / "invoice.pdf"
    source.write_bytes(b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    item = analysis.items[0]

    import shutil

    moved_aside = sandbox_root.path / "ordinary_original_contents"
    shutil.move(str(ordinary), str(moved_aside))
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(ordinary), str(app_paths.root)],
        check=True,
        capture_output=True,
    )
    before_listing = list(app_paths.root.rglob("*"))

    result = service.analyze_file(item.file_id)

    assert isinstance(result, AnalysisFailure)
    assert result.reason_code == ApplicationRejectionReason.STRUCTURALLY_PROTECTED.value
    # The real AppPaths.root (database file, Vault objects) is untouched --
    # nothing was ever read/written as a result of the rejected operation.
    assert list(app_paths.root.rglob("*")) == before_listing


# --- J. Source leaf hijack -----------------------------------------------------


def test_source_leaf_hijack_analyze_file_rejects_before_hash(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    tmp_path: Path,
) -> None:
    source = make_source_file("invoice.pdf", content=b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    item = analysis.items[0]

    source.unlink()
    external_target = tmp_path / "external_j"
    external_target.mkdir()
    (external_target / "secret.txt").write_text("secret")
    _make_junction(source, external_target)

    result = service.analyze_file(item.file_id)

    assert isinstance(result, AnalysisFailure)
    assert result.reason_code == ApplicationRejectionReason.STRUCTURALLY_PROTECTED.value


def test_source_leaf_hijack_apply_rejects_before_transaction(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    tmp_path: Path,
) -> None:
    source = make_source_file("invoice.pdf", content=b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    item = analysis.items[0]

    source.unlink()
    external_target = tmp_path / "external_j2"
    external_target.mkdir()
    (external_target / "secret.txt").write_text("secret")
    _make_junction(source, external_target)

    result = service.apply_item(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == ApplicationRejectionReason.STRUCTURALLY_PROTECTED.value
    assert result.transaction_id is None
    assert not (sandbox_root.path / "Documents" / "invoice.pdf").exists()
