"""FA-015 add_managed_root() registration validation: syntax/reparse/
existence checks (via the shared _resolve_safe_managed_root primitive),
breadth policy (drive root / user profile / system directory), overlap
against active roots, soft-delete + re-registration identity, and the
reparse-ancestor inspection ordering that round-2's review specifically
required (walking the ORIGINAL unresolved path before any resolve() call)."""

import subprocess
import threading
from pathlib import Path

import pytest

from file_agent.application import FileAgentApplicationService
from file_agent.application.errors import (
    AppDataManagedRootError,
    DuplicateManagedRootError,
    FilesystemRootManagedRootError,
    InvalidManagedRootPathError,
    ManagedRootReparsePointError,
    OverlappingManagedRootError,
    SystemDirectoryManagedRootError,
    UserProfileManagedRootError,
)
from file_agent.application.managed_roots import (
    ManagedRootStatus,
    _reject_bare_drive_root,
)
from file_agent.persistence import AppPaths, FileAgentStore


def _make_junction(link: Path, target: Path) -> None:
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
    )


# --- Basic acceptance / rejection --------------------------------------------


def test_valid_folder_registers(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    folder = tmp_path / "Downloads"
    folder.mkdir()

    view = service.add_managed_root(folder)

    assert view.path == folder.resolve()
    assert view.status is ManagedRootStatus.AVAILABLE
    assert view.id is not None


def test_relative_path_rejected(service: FileAgentApplicationService) -> None:
    with pytest.raises(InvalidManagedRootPathError):
        service.add_managed_root(Path("relative/folder"))


def test_dot_component_rejected_before_filesystem_io(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    with pytest.raises(InvalidManagedRootPathError):
        service.add_managed_root(tmp_path / "." / "Downloads")


def test_dotdot_component_rejected_before_filesystem_io(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    with pytest.raises(InvalidManagedRootPathError):
        service.add_managed_root(tmp_path / "Downloads" / ".." / "Sensitive")


def test_nonexistent_path_rejected(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    with pytest.raises(InvalidManagedRootPathError):
        service.add_managed_root(tmp_path / "does_not_exist")


def test_file_not_directory_rejected(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    plain_file = tmp_path / "not_a_folder.txt"
    plain_file.write_text("x")

    with pytest.raises(InvalidManagedRootPathError):
        service.add_managed_root(plain_file)


# --- Breadth policy -----------------------------------------------------------


def test_bare_drive_root_rejected() -> None:
    """Exercised as a direct unit test against the breadth-policy check
    itself, rather than through the full add_managed_root flow: on a
    single-drive test host, AppPaths.root necessarily lives on the same
    drive as any candidate bare-drive-root path, so the app-data
    disjointness check (which runs first, inside _resolve_safe_managed_root)
    would otherwise always shadow this one deterministically -- both are
    correct rejections, but this isolates the specific rule under test."""
    drive = Path(Path.cwd().anchor)
    with pytest.raises(FilesystemRootManagedRootError):
        _reject_bare_drive_root(drive)


def test_current_user_profile_root_rejected(
    service: FileAgentApplicationService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_users = tmp_path / "Users"
    fake_users.mkdir()
    fake_home = fake_users / "Ana"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    with pytest.raises(UserProfileManagedRootError):
        service.add_managed_root(fake_home)


def test_another_users_profile_root_rejected(
    service: FileAgentApplicationService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rejected via the structural Path.home().parent rule, not a hardcoded
    username -- must equally catch a DIFFERENT user's profile directory."""
    fake_users = tmp_path / "Users"
    fake_users.mkdir()
    fake_home = fake_users / "Ana"
    fake_home.mkdir()
    other_profile = fake_users / "Bob"
    other_profile.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    with pytest.raises(UserProfileManagedRootError):
        service.add_managed_root(other_profile)


def test_subfolder_of_user_profile_is_allowed(
    service: FileAgentApplicationService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_users = tmp_path / "Users"
    fake_users.mkdir()
    fake_home = fake_users / "Ana"
    fake_home.mkdir()
    downloads = fake_home / "Downloads"
    downloads.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    view = service.add_managed_root(downloads)

    assert view.status is ManagedRootStatus.AVAILABLE


def test_system_directory_exact_match_rejected(
    service: FileAgentApplicationService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_windir = tmp_path / "Windows"
    fake_windir.mkdir()
    monkeypatch.setenv("WINDIR", str(fake_windir))

    with pytest.raises(SystemDirectoryManagedRootError):
        service.add_managed_root(fake_windir)


def test_system_directory_subfolder_is_allowed(
    service: FileAgentApplicationService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round-4 documented v1 scope boundary: rule 3 is exact-equality-only
    -- a descendant of %WINDIR% is NOT rejected by this check."""
    fake_windir = tmp_path / "Windows"
    fake_windir.mkdir()
    subfolder = fake_windir / "System32"
    subfolder.mkdir()
    monkeypatch.setenv("WINDIR", str(fake_windir))

    view = service.add_managed_root(subfolder)

    assert view.status is ManagedRootStatus.AVAILABLE


# --- Overlap / duplicate --------------------------------------------------


def test_duplicate_path_rejected(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    folder = tmp_path / "Downloads"
    folder.mkdir()
    service.add_managed_root(folder)

    with pytest.raises(DuplicateManagedRootError):
        service.add_managed_root(folder)


def test_child_overlap_rejected(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    parent = tmp_path / "Documents"
    parent.mkdir()
    child = parent / "Subfolder"
    child.mkdir()
    service.add_managed_root(parent)

    with pytest.raises(OverlappingManagedRootError):
        service.add_managed_root(child)


def test_parent_overlap_rejected(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    parent = tmp_path / "Documents"
    parent.mkdir()
    child = parent / "Subfolder"
    child.mkdir()
    service.add_managed_root(child)

    with pytest.raises(OverlappingManagedRootError):
        service.add_managed_root(parent)


def test_sibling_roots_allowed(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    documents = tmp_path / "Documents"
    documents.mkdir()

    service.add_managed_root(downloads)
    view = service.add_managed_root(documents)

    assert view.status is ManagedRootStatus.AVAILABLE


def test_overlap_only_checked_against_active_roots(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    """A removed root imposes no constraint on future registrations."""
    parent = tmp_path / "Documents"
    parent.mkdir()
    child = parent / "Subfolder"
    child.mkdir()
    removed = service.add_managed_root(parent)
    service.remove_managed_root(removed.id)

    view = service.add_managed_root(child)

    assert view.status is ManagedRootStatus.AVAILABLE


# --- App-data disjointness -------------------------------------------------


def test_app_data_root_itself_rejected(
    service: FileAgentApplicationService, app_paths: AppPaths
) -> None:
    app_paths.root.mkdir(parents=True, exist_ok=True)
    with pytest.raises(AppDataManagedRootError):
        service.add_managed_root(app_paths.root)


def test_managed_root_containing_app_data_rejected(
    service: FileAgentApplicationService, app_paths: AppPaths, tmp_path: Path
) -> None:
    app_paths.root.mkdir(parents=True, exist_ok=True)
    parent = app_paths.root.parent
    with pytest.raises(AppDataManagedRootError):
        service.add_managed_root(parent)


# --- Re-registration / soft-delete identity --------------------------------


def test_reregistering_after_removal_gets_a_new_id(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    folder = tmp_path / "Downloads"
    folder.mkdir()
    first = service.add_managed_root(folder)
    service.remove_managed_root(first.id)

    second = service.add_managed_root(folder)

    assert second.id != first.id
    assert second.status is ManagedRootStatus.AVAILABLE


def test_concurrent_add_managed_root_race_produces_exactly_one_success(
    app_paths: AppPaths, store: FileAgentStore, tmp_path: Path
) -> None:
    folder = tmp_path / "Downloads"
    folder.mkdir()
    service_a = FileAgentApplicationService(app_paths, store)
    service_b = FileAgentApplicationService(app_paths, store)

    results: list[BaseException | None] = [None, None]

    def _register(service: FileAgentApplicationService, index: int) -> None:
        try:
            service.add_managed_root(folder)
        except BaseException as exc:  # noqa: BLE001 - captured for assertion below
            results[index] = exc

    t1 = threading.Thread(target=_register, args=(service_a, 0))
    t2 = threading.Thread(target=_register, args=(service_b, 1))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    failures = [r for r in results if r is not None]
    assert len(failures) == 1
    assert isinstance(failures[0], DuplicateManagedRootError)
    active = [root for root in store.list_managed_roots() if root.is_active]
    assert len(active) == 1


# --- Reparse-ancestor inspection ordering (round-2 regression) -------------


def test_root_itself_a_junction_rejected(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "junction_root"
    _make_junction(link, target)

    with pytest.raises(ManagedRootReparsePointError):
        service.add_managed_root(link)


def test_ancestor_junction_not_leaf_rejected(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    """The exact scenario round-1's ordering would have wrongly accepted:
    resolving first and walking the RESOLVED path's ancestors would never
    see `Alias` at all once resolve() had already substituted the
    junction's target. The corrected design inspects the ORIGINAL,
    unresolved path's lexical component chain before any resolve()."""
    external_target = tmp_path / "external"
    external_target.mkdir()
    real_parent = tmp_path / "real_parent"
    real_parent.mkdir()
    alias = tmp_path / "Alias"
    _make_junction(alias, real_parent)
    subfolder = (
        alias / "Subfolder"
    )  # exists via the junction, on-disk under real_parent
    (real_parent / "Subfolder").mkdir()

    with pytest.raises(ManagedRootReparsePointError):
        service.add_managed_root(subfolder)


def test_dotdot_immediately_after_reparse_ancestor_rejected_at_syntax_step(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    real_parent = tmp_path / "real_parent"
    real_parent.mkdir()
    alias = tmp_path / "Alias"
    _make_junction(alias, real_parent)

    with pytest.raises(InvalidManagedRootPathError):
        service.add_managed_root(alias / ".." / "Sensitive")


def test_ordinary_deep_ancestor_chain_accepted(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    deep = tmp_path / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)

    view = service.add_managed_root(deep)

    assert view.status is ManagedRootStatus.AVAILABLE


# --- Path-identity semantics (round-3 documentation, §17) -------------------


def test_active_registration_reusable_after_directory_replaced_at_same_path(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    """An ACTIVE registration whose directory is deleted and replaced by a
    brand-new, unrelated directory at the exact same path becomes usable
    again automatically -- no re-registration required, no error. FileAgent
    cannot distinguish "the original came back" from "something unrelated
    now occupies this path," and this is the documented, accepted v1
    consequence of path-based (not File-ID-based) identity."""
    folder = tmp_path / "Downloads"
    folder.mkdir()
    view = service.add_managed_root(folder)

    import shutil

    shutil.rmtree(folder)
    folder.mkdir()  # a brand-new, unrelated directory at the same path

    listed = service.list_managed_roots()
    matching = [r for r in listed if r.id == view.id]
    assert len(matching) == 1
    assert matching[0].status is ManagedRootStatus.AVAILABLE


def test_removed_registration_requires_genuine_reregistration_not_mere_directory_return(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    folder = tmp_path / "Downloads"
    folder.mkdir()
    first = service.add_managed_root(folder)
    service.remove_managed_root(first.id)

    import shutil

    shutil.rmtree(folder)
    folder.mkdir()

    # The removed registration is gone from list_managed_roots (active-only)
    assert first.id not in {r.id for r in service.list_managed_roots()}
    # Using the path again requires a genuinely new add_managed_root call.
    second = service.add_managed_root(folder)
    assert second.id != first.id
