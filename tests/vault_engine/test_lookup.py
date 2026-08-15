"""vault_engine.lookup.verify_vault_object -- the one shared, safety-checked
definition of a trusted Vault object."""

import hashlib
import subprocess
from pathlib import Path

from file_agent.persistence import AppPaths
from file_agent.vault_engine.lookup import (
    VaultLookupFailure,
    VaultLookupStatus,
    VerifiedVaultObject,
    verify_vault_object,
)
from file_agent.vault_engine.paths import object_abs_path


def _make_junction(link: Path, target: Path) -> None:
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
    )


def test_not_found_when_object_absent(tmp_path: Path) -> None:
    app_paths = AppPaths.from_root(tmp_path / "appdata")
    (app_paths.vault_root / "objects").mkdir(parents=True)
    (app_paths.vault_root / "tmp").mkdir(parents=True)
    sha = "a" * 64

    outcome = verify_vault_object(app_paths, sha)

    assert isinstance(outcome, VaultLookupFailure)
    assert outcome.status is VaultLookupStatus.NOT_FOUND


def test_verified_when_object_matches_its_own_filename(tmp_path: Path) -> None:
    app_paths = AppPaths.from_root(tmp_path / "appdata")
    (app_paths.vault_root / "tmp").mkdir(parents=True)
    content = b"trusted vault content"
    sha = hashlib.sha256(content).hexdigest()
    final_path = object_abs_path(app_paths, sha)
    final_path.parent.mkdir(parents=True)
    final_path.write_bytes(content)

    outcome = verify_vault_object(app_paths, sha)

    assert isinstance(outcome, VerifiedVaultObject)
    assert outcome.sha256 == sha
    assert outcome.abs_path == final_path
    assert outcome.size_bytes == len(content)
    assert outcome.relative_path == f"objects/{sha[:2]}/{sha}"


def test_corrupted_when_object_does_not_rehash_to_its_filename(tmp_path: Path) -> None:
    app_paths = AppPaths.from_root(tmp_path / "appdata")
    (app_paths.vault_root / "tmp").mkdir(parents=True)
    sha = "b" * 64
    final_path = object_abs_path(app_paths, sha)
    final_path.parent.mkdir(parents=True)
    final_path.write_bytes(b"this does not hash to b" * 64)

    outcome = verify_vault_object(app_paths, sha)

    assert isinstance(outcome, VaultLookupFailure)
    assert outcome.status is VaultLookupStatus.CORRUPTED


def test_unsafe_when_vault_root_itself_is_a_junction(tmp_path: Path) -> None:
    app_paths = AppPaths.from_root(tmp_path / "appdata")
    escape_target = tmp_path / "escape"
    escape_target.mkdir()
    app_paths.root.mkdir(parents=True)
    _make_junction(app_paths.vault_root, escape_target)

    outcome = verify_vault_object(app_paths, "c" * 64)

    assert isinstance(outcome, VaultLookupFailure)
    assert outcome.status is VaultLookupStatus.UNSAFE
    assert outcome.detail == app_paths.vault_root


def test_unsafe_when_sha_prefix_directory_is_a_junction(tmp_path: Path) -> None:
    app_paths = AppPaths.from_root(tmp_path / "appdata")
    (app_paths.vault_root / "objects").mkdir(parents=True)
    (app_paths.vault_root / "tmp").mkdir(parents=True)
    sha = "d" * 64
    prefix_dir = object_abs_path(app_paths, sha).parent
    escape_target = tmp_path / "escape"
    escape_target.mkdir()
    _make_junction(prefix_dir, escape_target)

    outcome = verify_vault_object(app_paths, sha)

    assert isinstance(outcome, VaultLookupFailure)
    assert outcome.status is VaultLookupStatus.UNSAFE
    assert outcome.detail == prefix_dir

    # never reads/writes inside the escape target
    assert list(escape_target.iterdir()) == []


def test_safety_checked_before_existence_no_stat_of_object_when_tree_unsafe(
    tmp_path: Path,
) -> None:
    """Order matters: an unsafe vault tree is rejected before this module
    ever attempts to stat/open the object file itself."""
    app_paths = AppPaths.from_root(tmp_path / "appdata")
    escape_target = tmp_path / "escape"
    escape_target.mkdir()
    app_paths.root.mkdir(parents=True)
    _make_junction(app_paths.vault_root, escape_target)
    # Deliberately do NOT create objects/tmp under the (junctioned) vault_root
    # -- if the implementation tried to stat/open the object path before the
    # safety check, this would raise instead of returning UNSAFE cleanly.

    outcome = verify_vault_object(app_paths, "e" * 64)

    assert isinstance(outcome, VaultLookupFailure)
    assert outcome.status is VaultLookupStatus.UNSAFE
