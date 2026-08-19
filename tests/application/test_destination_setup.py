"""FA-017.2 -- FileAgentApplicationService.prepare_destinations: current-need
authorization (never trusting a requested category on its own), the
per-category safety/create sequence, TOCTOU re-inspection, batch semantics,
and the audit-failure matrix (STARTED/ITEM_RESULT/COMPLETED persistence
failures)."""

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import pytest

from file_agent.application import FileAgentApplicationService
from file_agent.application.destination_setup import (
    DestinationPreparationStatus,
    DestinationSetupReasonCode,
    DestinationSetupResult,
)
from file_agent.application.managed_roots import ManagedRootUnavailable
from file_agent.domain import DestinationCategory, EventType
from file_agent.persistence import AppPaths, FileAgentStore
from file_agent.persistence.errors import DatabaseUnavailableError
from file_agent.scanner import SandboxRoot

from .conftest import FailOnEventType


def test_prepare_destinations_creates_missing_required_directory(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("invoice.pdf", content=b"pdf")
    service.analyze_managed_root(managed_root_id)
    (sandbox_root.path / "Documents").rmdir()

    result = service.prepare_destinations(
        managed_root_id, [DestinationCategory.DOCUMENTS]
    )

    assert isinstance(result, DestinationSetupResult)
    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert outcome.destination_category is DestinationCategory.DOCUMENTS
    assert outcome.status is DestinationPreparationStatus.PREPARED
    assert outcome.reason_code is None
    assert (sandbox_root.path / "Documents").is_dir()


def test_prepare_destinations_rejects_category_not_currently_required_with_no_filesystem_interaction(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    # No audio files exist at all -- AUDIO can never be in the current
    # required set. Remove the Audio folder too, so a proof stronger than
    # "wrong status" is possible: if create_directory_no_replace were
    # wrongly attempted, this folder would exist afterward.
    make_source_file("invoice.pdf", content=b"pdf")
    service.analyze_managed_root(managed_root_id)
    (sandbox_root.path / "Documents").rmdir()
    (sandbox_root.path / "Audio").rmdir()

    result = service.prepare_destinations(managed_root_id, [DestinationCategory.AUDIO])

    assert isinstance(result, DestinationSetupResult)
    (outcome,) = result.outcomes
    assert outcome.destination_category is DestinationCategory.AUDIO
    assert outcome.status is DestinationPreparationStatus.NOT_PREPARED
    assert outcome.reason_code is DestinationSetupReasonCode.NOT_CURRENTLY_REQUIRED
    # Proof of zero filesystem interaction: still absent, never created.
    assert not (sandbox_root.path / "Audio").exists()


def test_prepare_destinations_stale_request_after_facts_change(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    """An "old attention" (Documents was missing when last observed) must
    never authorize a mutation once the underlying facts have changed --
    here, the one pending file that needed Documents is deleted before
    prepare_destinations is called."""
    source = make_source_file("invoice.pdf", content=b"pdf")
    service.analyze_managed_root(managed_root_id)
    (sandbox_root.path / "Documents").rmdir()
    source.unlink()  # the fact that made Documents "required" no longer holds

    result = service.prepare_destinations(
        managed_root_id, [DestinationCategory.DOCUMENTS]
    )

    assert isinstance(result, DestinationSetupResult)
    (outcome,) = result.outcomes
    assert outcome.status is DestinationPreparationStatus.NOT_PREPARED
    assert outcome.reason_code is DestinationSetupReasonCode.NOT_CURRENTLY_REQUIRED
    assert not (sandbox_root.path / "Documents").exists()


def test_prepare_destinations_mixed_required_and_non_required(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("invoice.pdf", content=b"pdf")  # -> Documents only
    service.analyze_managed_root(managed_root_id)
    (sandbox_root.path / "Documents").rmdir()
    (sandbox_root.path / "Images").rmdir()

    result = service.prepare_destinations(
        managed_root_id, [DestinationCategory.DOCUMENTS, DestinationCategory.IMAGES]
    )

    assert isinstance(result, DestinationSetupResult)
    assert [o.destination_category for o in result.outcomes] == [
        DestinationCategory.DOCUMENTS,
        DestinationCategory.IMAGES,
    ]
    documents_outcome, images_outcome = result.outcomes
    assert documents_outcome.status is DestinationPreparationStatus.PREPARED
    assert images_outcome.status is DestinationPreparationStatus.NOT_PREPARED
    assert (
        images_outcome.reason_code is DestinationSetupReasonCode.NOT_CURRENTLY_REQUIRED
    )
    assert (sandbox_root.path / "Documents").is_dir()
    assert not (sandbox_root.path / "Images").exists()


def test_prepare_destinations_all_seven_categories_maliciously_requested(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("invoice.pdf", content=b"pdf")  # -> Documents only
    service.analyze_managed_root(managed_root_id)
    (sandbox_root.path / "Documents").rmdir()
    for category in DestinationCategory:
        if category is not DestinationCategory.DOCUMENTS:
            folder = (
                sandbox_root.path
                / {
                    DestinationCategory.IMAGES: "Images",
                    DestinationCategory.AUDIO: "Audio",
                    DestinationCategory.VIDEO: "Video",
                    DestinationCategory.ARCHIVES: "Archives",
                    DestinationCategory.CODE: "Code",
                    DestinationCategory.EXECUTABLES: "Executables",
                }[category]
            )
            folder.rmdir()

    result = service.prepare_destinations(managed_root_id, list(DestinationCategory))

    assert isinstance(result, DestinationSetupResult)
    assert len(result.outcomes) == 7
    by_category = {o.destination_category: o for o in result.outcomes}
    assert by_category[DestinationCategory.DOCUMENTS].status is (
        DestinationPreparationStatus.PREPARED
    )
    for category, outcome in by_category.items():
        if category is DestinationCategory.DOCUMENTS:
            continue
        assert outcome.status is DestinationPreparationStatus.NOT_PREPARED
        assert outcome.reason_code is DestinationSetupReasonCode.NOT_CURRENTLY_REQUIRED
    # None of the six non-required, currently-absent folders were created.
    assert (sandbox_root.path / "Documents").is_dir()
    assert not (sandbox_root.path / "Images").exists()
    assert not (sandbox_root.path / "Audio").exists()


def test_prepare_destinations_duplicate_categories_collapse_to_one_attempt(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("invoice.pdf", content=b"pdf")
    service.analyze_managed_root(managed_root_id)
    (sandbox_root.path / "Documents").rmdir()

    result = service.prepare_destinations(
        managed_root_id,
        [DestinationCategory.DOCUMENTS, DestinationCategory.DOCUMENTS],
    )

    assert isinstance(result, DestinationSetupResult)
    assert len(result.outcomes) == 1
    assert result.outcomes[0].status is DestinationPreparationStatus.PREPARED


def test_prepare_destinations_intact_folder_means_not_currently_required(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    """Documents already exists as a safe directory -- the item is READY,
    not CONFLICT, so DOCUMENTS is not even "required". A category whose
    folder becomes available BETWEEN the internal replan and the
    per-category mkdir attempt is a distinct TOCTOU scenario, covered
    separately below."""
    make_source_file("invoice.pdf", content=b"pdf")
    service.analyze_managed_root(managed_root_id)
    # Documents folder left intact -- the item is READY.

    result = service.prepare_destinations(
        managed_root_id, [DestinationCategory.DOCUMENTS]
    )

    (outcome,) = result.outcomes
    assert outcome.status is DestinationPreparationStatus.NOT_PREPARED
    assert outcome.reason_code is DestinationSetupReasonCode.NOT_CURRENTLY_REQUIRED


def test_prepare_destinations_toctou_directory_appears_before_mkdir(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_source_file("invoice.pdf", content=b"pdf")
    service.analyze_managed_root(managed_root_id)
    (sandbox_root.path / "Documents").rmdir()

    def _racing_create(path: Path) -> None:
        # Simulates another process winning the race: the directory now
        # exists by the time this call runs.
        path.mkdir()
        raise FileExistsError(str(path))

    monkeypatch.setattr(
        "file_agent.application.service.prepare_destination_directory",
        _racing_create,
    )

    result = service.prepare_destinations(
        managed_root_id, [DestinationCategory.DOCUMENTS]
    )

    (outcome,) = result.outcomes
    # Never PREPARED for a directory this call did not itself create via a
    # successful create_directory_no_replace call.
    assert outcome.status is DestinationPreparationStatus.ALREADY_AVAILABLE
    assert (sandbox_root.path / "Documents").is_dir()


def test_prepare_destinations_toctou_file_appears_before_mkdir(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_source_file("invoice.pdf", content=b"pdf")
    service.analyze_managed_root(managed_root_id)
    (sandbox_root.path / "Documents").rmdir()

    def _racing_create(path: Path) -> None:
        path.write_bytes(b"a file, not a directory")
        raise FileExistsError(str(path))

    monkeypatch.setattr(
        "file_agent.application.service.prepare_destination_directory",
        _racing_create,
    )

    result = service.prepare_destinations(
        managed_root_id, [DestinationCategory.DOCUMENTS]
    )

    (outcome,) = result.outcomes
    assert outcome.status is DestinationPreparationStatus.NOT_PREPARED
    assert outcome.reason_code is DestinationSetupReasonCode.FILE_AT_DESTINATION


def test_prepare_destinations_toctou_never_retries_mkdir(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_source_file("invoice.pdf", content=b"pdf")
    service.analyze_managed_root(managed_root_id)
    (sandbox_root.path / "Documents").rmdir()

    call_count = 0

    def _always_race(path: Path) -> None:
        nonlocal call_count
        call_count += 1
        raise FileExistsError(str(path))

    monkeypatch.setattr(
        "file_agent.application.service.prepare_destination_directory",
        _always_race,
    )

    result = service.prepare_destinations(
        managed_root_id, [DestinationCategory.DOCUMENTS]
    )

    (outcome,) = result.outcomes
    assert outcome.status is DestinationPreparationStatus.NOT_PREPARED
    assert outcome.reason_code is DestinationSetupReasonCode.OBSERVATION_FAILED
    assert call_count == 1  # never retried


def test_prepare_destinations_managed_root_unavailable_performs_no_mutation(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("invoice.pdf", content=b"pdf")
    service.analyze_managed_root(managed_root_id)
    (sandbox_root.path / "Documents").rmdir()
    service.remove_managed_root(managed_root_id)

    result = service.prepare_destinations(
        managed_root_id, [DestinationCategory.DOCUMENTS]
    )

    assert isinstance(result, ManagedRootUnavailable)
    assert not (sandbox_root.path / "Documents").exists()


# --- Audit-failure matrix ----------------------------------------------------


def test_prepare_destinations_started_persistence_failure_performs_zero_mkdir(
    app_paths: AppPaths,
    store: FileAgentStore,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    plain_service = FileAgentApplicationService(app_paths, store)
    managed_root_id = plain_service.add_managed_root(sandbox_root.path).id
    make_source_file("invoice.pdf", content=b"pdf")
    plain_service.analyze_managed_root(managed_root_id)
    (sandbox_root.path / "Documents").rmdir()

    failing_store = FailOnEventType(store, {EventType.DESTINATION_SETUP_STARTED})
    failing_service = FileAgentApplicationService(app_paths, failing_store)  # type: ignore[arg-type]

    with pytest.raises(DatabaseUnavailableError):
        failing_service.prepare_destinations(
            managed_root_id, [DestinationCategory.DOCUMENTS]
        )

    assert not (sandbox_root.path / "Documents").exists()


def test_prepare_destinations_item_result_persistence_failure_keeps_prepared_status(
    app_paths: AppPaths,
    store: FileAgentStore,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    plain_service = FileAgentApplicationService(app_paths, store)
    managed_root_id = plain_service.add_managed_root(sandbox_root.path).id
    make_source_file("invoice.pdf", content=b"pdf")
    plain_service.analyze_managed_root(managed_root_id)
    (sandbox_root.path / "Documents").rmdir()

    failing_store = FailOnEventType(store, {EventType.DESTINATION_SETUP_ITEM_RESULT})
    failing_service = FileAgentApplicationService(app_paths, failing_store)  # type: ignore[arg-type]

    result = failing_service.prepare_destinations(
        managed_root_id, [DestinationCategory.DOCUMENTS]
    )

    assert isinstance(result, DestinationSetupResult)
    (outcome,) = result.outcomes
    # The real mutation succeeded and is reported truthfully, even though
    # its own audit checkpoint failed to persist.
    assert outcome.status is DestinationPreparationStatus.PREPARED
    assert (sandbox_root.path / "Documents").is_dir()


def test_prepare_destinations_item_result_failure_does_not_abort_remaining_categories(
    app_paths: AppPaths,
    store: FileAgentStore,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    plain_service = FileAgentApplicationService(app_paths, store)
    managed_root_id = plain_service.add_managed_root(sandbox_root.path).id
    make_source_file("invoice.pdf", content=b"pdf")
    make_source_file("photo.jpg", content=b"jpg")
    plain_service.analyze_managed_root(managed_root_id)
    (sandbox_root.path / "Documents").rmdir()
    (sandbox_root.path / "Images").rmdir()

    failing_store = FailOnEventType(store, {EventType.DESTINATION_SETUP_ITEM_RESULT})
    failing_service = FileAgentApplicationService(app_paths, failing_store)  # type: ignore[arg-type]

    result = failing_service.prepare_destinations(
        managed_root_id, [DestinationCategory.DOCUMENTS, DestinationCategory.IMAGES]
    )

    assert isinstance(result, DestinationSetupResult)
    assert len(result.outcomes) == 2
    assert all(
        o.status is DestinationPreparationStatus.PREPARED for o in result.outcomes
    )
    assert (sandbox_root.path / "Documents").is_dir()
    assert (sandbox_root.path / "Images").is_dir()


def test_prepare_destinations_completed_persistence_failure_leaves_result_unchanged(
    app_paths: AppPaths,
    store: FileAgentStore,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    plain_service = FileAgentApplicationService(app_paths, store)
    managed_root_id = plain_service.add_managed_root(sandbox_root.path).id
    make_source_file("invoice.pdf", content=b"pdf")
    plain_service.analyze_managed_root(managed_root_id)
    (sandbox_root.path / "Documents").rmdir()

    failing_store = FailOnEventType(store, {EventType.DESTINATION_SETUP_COMPLETED})
    failing_service = FileAgentApplicationService(app_paths, failing_store)  # type: ignore[arg-type]

    result = failing_service.prepare_destinations(
        managed_root_id, [DestinationCategory.DOCUMENTS]
    )

    assert isinstance(result, DestinationSetupResult)
    (outcome,) = result.outcomes
    assert outcome.status is DestinationPreparationStatus.PREPARED
    assert (sandbox_root.path / "Documents").is_dir()


def test_prepare_destinations_already_available_gets_its_own_audit_event(
    app_paths: AppPaths,
    store: FileAgentStore,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Minor 2: an ALREADY_AVAILABLE outcome for an accepted (currently
    required) category still gets a DESTINATION_SETUP_ITEM_RESULT event,
    exactly like PREPARED/NOT_PREPARED -- never a no-op skip. Forces the
    ALREADY_AVAILABLE branch via the same TOCTOU race simulation as above,
    since a category only ever reaches "required" analysis-side when its
    folder is genuinely missing at plan-build time."""
    from file_agent.domain import EntityType

    plain_service = FileAgentApplicationService(app_paths, store)
    managed_root_id = plain_service.add_managed_root(sandbox_root.path).id
    make_source_file("invoice.pdf", content=b"pdf")
    plain_service.analyze_managed_root(managed_root_id)
    (sandbox_root.path / "Documents").rmdir()

    def _racing_create(path: Path) -> None:
        path.mkdir()
        raise FileExistsError(str(path))

    monkeypatch.setattr(
        "file_agent.application.service.prepare_destination_directory",
        _racing_create,
    )

    result = plain_service.prepare_destinations(
        managed_root_id, [DestinationCategory.DOCUMENTS]
    )
    assert isinstance(result, DestinationSetupResult)
    assert result.outcomes[0].status is DestinationPreparationStatus.ALREADY_AVAILABLE
    setup_id = result.setup_id

    events = store.list_events(EntityType.DESTINATION_SETUP, setup_id)
    item_result_events = [
        e for e in events if e.event_type is EventType.DESTINATION_SETUP_ITEM_RESULT
    ]
    assert len(item_result_events) == 1
    assert item_result_events[0].payload["status"] == "already_available"
