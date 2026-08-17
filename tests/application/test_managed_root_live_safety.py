"""FA-015 round-4 CRITICAL regression: registration-time validation only
proves a path was safe ONCE. Every one of these tests registers a root
safely, performs some legitimate operation, then -- WITHOUT touching the
ManagedRoot registration itself -- replaces an ancestor directory of the
registered path with a junction to an unrelated external location, so the
registered path STRING is unchanged but now silently resolves elsewhere.
Every live call site must catch this via _resolve_safe_managed_root's
lexical ancestor-reparse scan, never merely trusting a cached/prior-proven
result. This is the direct regression suite for the round-4 approval's
"High-priority adversarial regressions" requirement."""

import hashlib
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from file_agent.application import (
    ApplicationOutcomeStatus,
    FileAgentApplicationService,
)
from file_agent.application.dto import ApplicationRejectionReason
from file_agent.application.managed_roots import (
    ManagedRootLookupStatus,
    ManagedRootPathFailure,
    ManagedRootPathFailureReason,
    ManagedRootStatus,
    ManagedRootUnavailable,
    _resolve_safe_managed_root,
)
from file_agent.destination import PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY
from file_agent.domain import VaultCaptureRequest, VaultCaptureStatus
from file_agent.persistence import AppPaths, FileAgentStore
from file_agent.scanner import SandboxRoot
from file_agent.vault_engine import (
    VaultEngine,
    vault_capture_requested_event,
    vault_capture_result_event,
)


def _make_junction(link: Path, target: Path) -> None:
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
    )


def _build_registered_root(
    service: FileAgentApplicationService, tmp_path: Path
) -> tuple[UUID, Path, Path]:
    """Registers `real_parent/managed` as a safe ManagedRoot and returns
    (managed_root_id, real_parent, managed_dir). `real_parent` is the
    ancestor that later gets swapped for a junction."""
    real_parent = tmp_path / "real_parent"
    real_parent.mkdir()
    managed_dir = real_parent / "managed"
    managed_dir.mkdir()
    for directory in PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY.values():
        (managed_dir / directory).mkdir()
    view = service.add_managed_root(managed_dir)
    return view.id, real_parent, managed_dir


def _hijack_ancestor(real_parent: Path, tmp_path: Path) -> Path:
    """Replaces `real_parent` -- an ANCESTOR of the registered root, not the
    registered root itself -- with a junction to a fresh, unrelated external
    directory. The registered ManagedRoot.path string is completely
    unchanged; only what it resolves to has silently changed."""
    moved_aside = tmp_path / "real_parent_original_contents"
    shutil.move(str(real_parent), str(moved_aside))
    external_target = tmp_path / "external_target"
    external_target.mkdir()
    _make_junction(real_parent, external_target)
    return external_target


@pytest.fixture
def make_file_in(tmp_path: Path) -> Callable[[Path, str, bytes], Path]:
    def _make(directory: Path, name: str, content: bytes) -> Path:
        path = directory / name
        path.write_bytes(content)
        return path

    return _make


# --- 1. analyze_managed_root -------------------------------------------------


def test_analyze_managed_root_rejects_after_ancestor_hijack(
    service: FileAgentApplicationService,
    tmp_path: Path,
) -> None:
    managed_root_id, real_parent, managed_dir = _build_registered_root(
        service, tmp_path
    )
    (managed_dir / "invoice.pdf").write_bytes(b"pdf content")
    external_target = _hijack_ancestor(real_parent, tmp_path)

    result = service.analyze_managed_root(managed_root_id)

    assert isinstance(result, ManagedRootUnavailable)
    assert result.status is ManagedRootLookupStatus.UNAVAILABLE
    assert not any(external_target.rglob("*"))


# --- 2. apply_item / apply_items ---------------------------------------------


def test_apply_rejected_after_ancestor_hijack(
    service: FileAgentApplicationService,
    tmp_path: Path,
) -> None:
    managed_root_id, real_parent, managed_dir = _build_registered_root(
        service, tmp_path
    )
    (managed_dir / "invoice.pdf").write_bytes(b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    policy_decision_id = analysis.items[0].policy_decision_id

    external_target = _hijack_ancestor(real_parent, tmp_path)

    single = service.apply_item(policy_decision_id)
    assert single.status is ApplicationOutcomeStatus.REJECTED
    assert (
        single.reason_code == ApplicationRejectionReason.MANAGED_ROOT_NOT_ACTIVE.value
    )

    batch = service.apply_items([policy_decision_id])
    assert isinstance(batch, ManagedRootUnavailable)
    assert not any(external_target.rglob("*"))


# --- 3. create_organization_plan ---------------------------------------------


def test_create_organization_plan_rejected_after_ancestor_hijack(
    service: FileAgentApplicationService,
    tmp_path: Path,
) -> None:
    managed_root_id, real_parent, managed_dir = _build_registered_root(
        service, tmp_path
    )
    (managed_dir / "invoice.pdf").write_bytes(b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    policy_decision_id = analysis.items[0].policy_decision_id

    external_target = _hijack_ancestor(real_parent, tmp_path)

    plan = service.create_organization_plan([policy_decision_id])

    assert isinstance(plan, ManagedRootUnavailable)
    assert not any(external_target.rglob("*"))


# --- 4. list_managed_roots ----------------------------------------------------


def test_list_managed_roots_reports_unavailable_after_ancestor_hijack(
    service: FileAgentApplicationService,
    tmp_path: Path,
) -> None:
    managed_root_id, real_parent, _managed_dir = _build_registered_root(
        service, tmp_path
    )
    _hijack_ancestor(real_parent, tmp_path)

    views = service.list_managed_roots()

    matching = [v for v in views if v.id == managed_root_id]
    assert len(matching) == 1
    assert matching[0].status is ManagedRootStatus.UNAVAILABLE


# --- 5. undo_transaction ------------------------------------------------------


def test_undo_transaction_rejected_after_ancestor_hijack(
    service: FileAgentApplicationService,
    tmp_path: Path,
) -> None:
    managed_root_id, real_parent, managed_dir = _build_registered_root(
        service, tmp_path
    )
    (managed_dir / "invoice.pdf").write_bytes(b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    policy_decision_id = analysis.items[0].policy_decision_id
    applied = service.apply_item(policy_decision_id)
    assert applied.status is ApplicationOutcomeStatus.SUCCEEDED
    transaction_id = applied.transaction_id
    assert transaction_id is not None

    external_target = _hijack_ancestor(real_parent, tmp_path)

    result = service.undo_transaction(transaction_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert (
        result.reason_code
        == ApplicationRejectionReason.HISTORICAL_ROOT_UNAVAILABLE.value
    )
    assert not any(external_target.rglob("*"))


# --- 6. restore_capture -------------------------------------------------------


def test_restore_capture_rejected_after_ancestor_hijack(
    service: FileAgentApplicationService,
    app_paths: AppPaths,
    store: FileAgentStore,
    tmp_path: Path,
) -> None:
    managed_root_id, real_parent, managed_dir = _build_registered_root(
        service, tmp_path
    )
    content = b"vault-backed content"
    source = managed_dir / "report.txt"
    source.write_bytes(content)
    analysis = service.analyze_managed_root(managed_root_id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    file_id = analysis.items[0].file_id

    st = source.stat()
    request = VaultCaptureRequest(
        file_id=file_id,
        source_path=source,
        expected_size=st.st_size,
        expected_created_at=datetime.fromtimestamp(st.st_ctime, tz=UTC),
        expected_modified_at=datetime.fromtimestamp(st.st_mtime, tz=UTC),
        expected_sha256=hashlib.sha256(content).hexdigest(),
    )
    store.record_event(vault_capture_requested_event(request))
    sandbox_root = SandboxRoot.from_path(managed_dir)
    capture_result = VaultEngine(sandbox_root, app_paths).capture(request)
    store.record_event(vault_capture_result_event(capture_result))
    assert capture_result.status is VaultCaptureStatus.CAPTURED

    external_target = _hijack_ancestor(real_parent, tmp_path)

    result = service.restore_capture(request.id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert (
        result.reason_code
        == ApplicationRejectionReason.HISTORICAL_ROOT_UNAVAILABLE.value
    )
    assert not any(external_target.rglob("*"))


# --- 7. App-data redirect -----------------------------------------------------


def test_resolve_safe_managed_root_rechecks_app_data_disjointness_live(
    tmp_path: Path,
) -> None:
    """_resolve_safe_managed_root's app-data disjointness re-check (step F)
    is evaluated fresh against the app_paths ARGUMENT on every call -- never
    cached from a prior successful call. This is the mechanism the round-4
    design's "app-data redirect" scenario relies on: a managed root that was
    genuinely disjoint from app data at registration time must be rejected
    the moment app data's own location is (re-)resolved to overlap it,
    without the managed root's own path or registration ever changing.

    (A real ancestor-junction swap always trips the reparse-ancestor check,
    steps B-D, before step F is ever reached -- that ordering is itself
    correct defense-in-depth, proven by the six tests above. This test
    isolates step F specifically, the way the design's own call-site table
    frames it: re-verified against the FRESHLY resolved SandboxRoot, live,
    every single call -- not merely re-validated once at registration.)"""
    managed_dir = tmp_path / "managed"
    managed_dir.mkdir()
    disjoint_app_paths = AppPaths.from_root(tmp_path / "disjoint_appdata")

    safe = _resolve_safe_managed_root(managed_dir, disjoint_app_paths)
    assert isinstance(safe, SandboxRoot)

    overlapping_app_paths = AppPaths.from_root(managed_dir.parent)

    outcome = _resolve_safe_managed_root(managed_dir, overlapping_app_paths)

    assert isinstance(outcome, ManagedRootPathFailure)
    assert outcome.reason is ManagedRootPathFailureReason.APP_DATA_OVERLAP


def test_managed_root_unavailable_when_app_paths_shifts_to_overlap_it(
    store: FileAgentStore, tmp_path: Path
) -> None:
    """Service-level counterpart: two FileAgentApplicationService instances
    sharing the same store, one whose AppPaths is disjoint (used at
    registration) and one whose AppPaths now overlaps the already-registered
    root -- proving the check is re-derived from whatever AppPaths is live
    right now, never assumed still-disjoint from registration time."""
    managed_dir = tmp_path / "managed"
    managed_dir.mkdir()
    registering_app_paths = AppPaths.from_root(tmp_path / "disjoint_appdata")
    registering_service = FileAgentApplicationService(registering_app_paths, store)
    view = registering_service.add_managed_root(managed_dir)

    later_app_paths = AppPaths.from_root(managed_dir.parent)
    later_service = FileAgentApplicationService(later_app_paths, store)

    result = later_service.analyze_managed_root(view.id)

    assert isinstance(result, ManagedRootUnavailable)
    assert result.status is ManagedRootLookupStatus.UNAVAILABLE
