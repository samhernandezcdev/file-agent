"""vault_engine.paths -- content-addressed path arithmetic. No public
function accepts a caller-supplied destination path; every path is derived
from a sha256 string, which is itself strictly re-validated here."""

from pathlib import Path

import pytest

from file_agent.persistence import AppPaths
from file_agent.vault_engine.paths import (
    object_abs_path,
    object_prefix_dir,
    object_relative_path,
)

_VALID_SHA = "a" * 64


@pytest.fixture
def app_paths(tmp_path: Path) -> AppPaths:
    return AppPaths.from_root(tmp_path / "appdata")


@pytest.mark.parametrize(
    "bad_sha",
    [
        "",
        "not-a-hash",
        "a" * 63,  # too short
        "a" * 65,  # too long
        "A" * 64,  # uppercase not accepted
        "g" * 64,  # non-hex character
        "../../../../etc/passwd",
        "../" * 20 + "a" * 64,
        "a" * 64 + "/../../escape",
        "a" * 64 + "\x00",
        "..\\..\\windows\\system32",
    ],
)
def test_invalid_sha256_rejected_everywhere_a_path_is_derived(
    bad_sha: str, app_paths: AppPaths
) -> None:
    with pytest.raises(ValueError):
        object_relative_path(bad_sha)
    with pytest.raises(ValueError):
        object_abs_path(app_paths, bad_sha)
    with pytest.raises(ValueError):
        object_prefix_dir(app_paths, bad_sha)


def test_object_relative_path_is_deterministic() -> None:
    assert object_relative_path(_VALID_SHA) == f"objects/aa/{_VALID_SHA}"
    assert object_relative_path(_VALID_SHA) == object_relative_path(_VALID_SHA)


def test_object_abs_path_uses_two_char_prefix_fanout(app_paths: AppPaths) -> None:
    abs_path = object_abs_path(app_paths, _VALID_SHA)
    prefix = object_prefix_dir(app_paths, _VALID_SHA)

    assert abs_path == app_paths.vault_root / "objects" / "aa" / _VALID_SHA
    assert abs_path.parent == prefix
    assert prefix.name == "aa"


def test_different_shas_map_to_different_deterministic_paths(
    app_paths: AppPaths,
) -> None:
    sha_a = "a" * 64
    sha_b = "b" * 64

    assert object_abs_path(app_paths, sha_a) != object_abs_path(app_paths, sha_b)
    assert object_abs_path(app_paths, sha_a) == object_abs_path(app_paths, sha_a)
