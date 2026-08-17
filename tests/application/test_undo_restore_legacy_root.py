"""FA-015 round-3 regression: legacy pre-FA-015 undo/restore semantics.
_resolve_historical_root deterministically fails closed to None -- never
raises, never crashes, never infers a root from current filesystem state --
for every reason a live historical root cannot be resolved, including a
FileObservationRow with managed_root_id=None (genuinely legacy data, the
adopted v1 migration contract: never retroactively backfilled). Callers
cannot distinguish WHY the historical root is unavailable from the public
API -- that is by design (see service.py's _resolve_historical_root
docstring)."""

from pathlib import Path

from file_agent.application import (
    ApplicationOutcomeStatus,
    FileAgentApplicationService,
)
from file_agent.application.dto import ApplicationRejectionReason
from file_agent.application.managed_roots import ManagedRootUnavailable
from file_agent.destination import PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY
from file_agent.persistence import FileAgentStore
from file_agent.persistence.orm import FileObservationRow


def _make_root(tmp_path: Path, name: str) -> Path:
    folder = tmp_path / name
    folder.mkdir()
    for directory in PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY.values():
        (folder / directory).mkdir()
    return folder


def _null_out_managed_root_id(store: FileAgentStore, file_id) -> None:
    """White-box simulation of genuinely legacy pre-FA-015 data: no public
    API can ever produce managed_root_id=None for a row inserted by today's
    scanner (it always stamps one), so a direct ORM write is the only way
    to construct this state for a regression test."""
    session = store._session_factory()
    try:
        with session.begin():
            row = session.get(FileObservationRow, file_id)
            assert row is not None
            row.managed_root_id = None
    finally:
        session.close()


def test_undo_succeeds_after_owning_root_removed_folder_still_present(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    """Recommendation B: undo is historically-authorized recovery,
    independent of CURRENT root registration status."""
    folder = _make_root(tmp_path, "Downloads")
    (folder / "report.pdf").write_bytes(b"content")
    root = service.add_managed_root(folder)
    analysis = service.analyze_managed_root(root.id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    applied = service.apply_item(analysis.items[0].policy_decision_id)
    assert applied.status is ApplicationOutcomeStatus.SUCCEEDED

    service.remove_managed_root(root.id)

    result = service.undo_transaction(applied.transaction_id)

    assert result.status is ApplicationOutcomeStatus.SUCCEEDED
    original = folder / "report.pdf"
    assert original.exists()


def test_undo_fails_closed_for_legacy_file_with_no_managed_root_lineage(
    service: FileAgentApplicationService, store: FileAgentStore, tmp_path: Path
) -> None:
    folder = _make_root(tmp_path, "Downloads")
    (folder / "report.pdf").write_bytes(b"content")
    root = service.add_managed_root(folder)
    analysis = service.analyze_managed_root(root.id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    file_id = analysis.items[0].file_id
    applied = service.apply_item(analysis.items[0].policy_decision_id)
    assert applied.status is ApplicationOutcomeStatus.SUCCEEDED

    _null_out_managed_root_id(store, file_id)

    result = service.undo_transaction(applied.transaction_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert (
        result.reason_code
        == ApplicationRejectionReason.HISTORICAL_ROOT_UNAVAILABLE.value
    )
    # No mutation: the file remains wherever apply_item legitimately left it.
    destination = applied.destination_path
    assert destination is not None
    assert destination.exists()


def test_restore_fails_closed_for_legacy_capture_with_no_managed_root_lineage(
    service: FileAgentApplicationService, store: FileAgentStore, tmp_path: Path
) -> None:
    import hashlib
    from datetime import UTC, datetime

    from file_agent.domain import VaultCaptureRequest, VaultCaptureStatus
    from file_agent.persistence import AppPaths
    from file_agent.scanner import SandboxRoot
    from file_agent.vault_engine import (
        VaultEngine,
        vault_capture_requested_event,
        vault_capture_result_event,
    )

    folder = _make_root(tmp_path, "Downloads")
    content = b"vault-backed content"
    source = folder / "report.txt"
    source.write_bytes(content)
    root = service.add_managed_root(folder)
    analysis = service.analyze_managed_root(root.id)
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
    app_paths = AppPaths.from_root(tmp_path / "appdata_for_capture")
    capture_result = VaultEngine(SandboxRoot.from_path(folder), app_paths).capture(
        request
    )
    store.record_event(vault_capture_result_event(capture_result))
    assert capture_result.status is VaultCaptureStatus.CAPTURED
    source.unlink()

    _null_out_managed_root_id(store, file_id)

    result = service.restore_capture(request.id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert (
        result.reason_code
        == ApplicationRejectionReason.HISTORICAL_ROOT_UNAVAILABLE.value
    )
    assert not source.exists()


def test_resolve_historical_root_returns_none_uniformly_for_every_underlying_cause(
    service: FileAgentApplicationService, store: FileAgentStore, tmp_path: Path
) -> None:
    """Three distinct underlying causes -- no lineage at all (unknown
    file_id), managed_root_id is None (legacy data), and a since-removed/
    unresolvable ManagedRootRow -- all collapse to the identical None
    result, so callers can never distinguish WHY from the public API."""
    from uuid import uuid4

    # Cause 1: no DiscoveredFile at all.
    assert service._resolve_historical_root(uuid4()) is None

    # Cause 2: managed_root_id is None (legacy).
    folder = _make_root(tmp_path, "Downloads")
    (folder / "a.pdf").write_bytes(b"a")
    root = service.add_managed_root(folder)
    analysis = service.analyze_managed_root(root.id)
    assert not isinstance(analysis, ManagedRootUnavailable)
    file_id_legacy = analysis.items[0].file_id
    _null_out_managed_root_id(store, file_id_legacy)
    assert service._resolve_historical_root(file_id_legacy) is None

    # Cause 3: managed_root_id set, but the live primitive fails (root
    # removed AND the folder itself no longer exists at all).
    folder2 = _make_root(tmp_path, "Documents")
    (folder2 / "b.pdf").write_bytes(b"b")
    root2 = service.add_managed_root(folder2)
    analysis2 = service.analyze_managed_root(root2.id)
    assert not isinstance(analysis2, ManagedRootUnavailable)
    file_id_gone = analysis2.items[0].file_id
    service.remove_managed_root(root2.id)
    import shutil

    shutil.rmtree(folder2)
    assert service._resolve_historical_root(file_id_gone) is None
