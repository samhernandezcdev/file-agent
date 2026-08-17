"""FA-015 Spanish presentation: content-level assertions distinguishing
messages that must NOT share copy -- NOT_FOUND vs UNAVAILABLE
(managed_root_unavailable_message) and undo vs restore
(HISTORICAL_ROOT_UNAVAILABLE) render different, action-appropriate text,
per round-3/round-4's explicit correction that a shared message would be
actively wrong for at least one of the two cases in each pair."""

from pathlib import Path
from uuid import uuid4

from file_agent.application.errors import (
    AppDataManagedRootError,
    DuplicateManagedRootError,
    FilesystemRootManagedRootError,
    InvalidManagedRootPathError,
    ManagedRootRegistrationError,
    ManagedRootReparsePointError,
    OverlappingManagedRootError,
    SystemDirectoryManagedRootError,
    UserProfileManagedRootError,
)
from file_agent.application.managed_roots import (
    ManagedRootLookupStatus,
    ManagedRootUnavailable,
)
from file_agent.presentation import es


def test_not_found_and_unavailable_render_distinct_copy() -> None:
    not_found = es.managed_root_unavailable_message(
        ManagedRootUnavailable(uuid4(), ManagedRootLookupStatus.NOT_FOUND, "d")
    )
    unavailable = es.managed_root_unavailable_message(
        ManagedRootUnavailable(uuid4(), ManagedRootLookupStatus.UNAVAILABLE, "d")
    )

    assert not_found.detail != unavailable.detail


def test_undo_and_restore_render_distinct_copy() -> None:
    undo = es.undo_historical_root_unavailable_message()
    restore = es.restore_historical_root_unavailable_message()

    assert undo.detail != restore.detail
    assert undo.title != restore.title
    assert "deshacer" in undo.title.lower() or "deshacer" in undo.detail.lower()
    assert "restaurar" in restore.title.lower() or "restaurar" in restore.detail.lower()


def test_duplicate_root_message() -> None:
    path = Path("C:/Users/Ana/Downloads").resolve()
    message = es.managed_root_registration_error_message(
        DuplicateManagedRootError(path, uuid4())
    )
    assert message.detail == "Esta carpeta ya está agregada."


def test_overlap_child_vs_parent_render_distinct_directional_copy() -> None:
    path = Path("C:/Users/Ana/Downloads").resolve()
    existing = path / "Subfolder"
    child_overlap = es.managed_root_registration_error_message(
        OverlappingManagedRootError(existing, uuid4(), path)
    )
    parent_overlap = es.managed_root_registration_error_message(
        OverlappingManagedRootError(path, uuid4(), existing)
    )

    assert child_overlap.detail != parent_overlap.detail
    assert "dentro de otra carpeta" in child_overlap.detail
    assert "contiene otra carpeta" in parent_overlap.detail


def test_filesystem_root_message() -> None:
    message = es.managed_root_registration_error_message(
        FilesystemRootManagedRootError(Path("C:/"), "drive")
    )
    assert "unidad completa" in message.detail


def test_breadth_policy_errors_share_the_same_fallback_copy() -> None:
    path = Path("C:/Users/Ana/Downloads").resolve()
    user_profile = es.managed_root_registration_error_message(
        UserProfileManagedRootError(path, "profile")
    )
    system_dir = es.managed_root_registration_error_message(
        SystemDirectoryManagedRootError(path, "system")
    )
    assert user_profile.detail == system_dir.detail


def test_app_data_overlap_message() -> None:
    path = Path("C:/Users/Ana/Downloads").resolve()
    message = es.managed_root_registration_error_message(
        AppDataManagedRootError(path, "overlap")
    )
    assert "internamente" in message.detail


def test_invalid_path_and_reparse_point_share_the_same_fallback_copy() -> None:
    path = Path("C:/Users/Ana/Downloads").resolve()
    invalid = es.managed_root_registration_error_message(
        InvalidManagedRootPathError(path, "bad")
    )
    reparse = es.managed_root_registration_error_message(
        ManagedRootReparsePointError(path, "reparse")
    )
    assert invalid.detail == reparse.detail


def test_unmapped_registration_error_subtype_renders_generic_fallback() -> None:
    class _FutureManagedRootError(ManagedRootRegistrationError):
        pass

    message = es.managed_root_registration_error_message(
        _FutureManagedRootError(Path("C:/x").resolve(), "future reason")
    )

    assert message.detail
    assert message.title == "No se pudo agregar esta carpeta."
