"""FA-016 structural_safety pure unit tests: marker families, hard-exclusion
names, symlinked-marker non-establishment, containment precondition, and
fail-closed reference-inspection-uncertainty (fault injection at
Path.is_symlink/os.path.isjunction/os.stat, for both an ancestor and the
candidate leaf) -- the review's required tests K/L/M at the primitive
level."""

import os
import subprocess
from pathlib import Path

import pytest

from file_agent.structural_safety import (
    ProjectMarkerType,
    StructuralInspectionFailure,
    StructuralProtection,
    StructuralProtectionKind,
    find_structural_protection,
    is_hard_excluded_directory_name,
)

MARKER_FAMILIES: tuple[tuple[str, ProjectMarkerType, bool], ...] = (
    (".git", ProjectMarkerType.GIT, True),
    ("package.json", ProjectMarkerType.PACKAGE_JSON, False),
    ("pyproject.toml", ProjectMarkerType.PYPROJECT_TOML, False),
    ("Cargo.toml", ProjectMarkerType.CARGO_TOML, False),
    ("go.mod", ProjectMarkerType.GO_MOD, False),
    ("pom.xml", ProjectMarkerType.POM_XML, False),
    ("build.gradle", ProjectMarkerType.BUILD_GRADLE, False),
    ("settings.gradle", ProjectMarkerType.SETTINGS_GRADLE, False),
    ("app.sln", ProjectMarkerType.DOTNET_SOLUTION, False),
    ("app.csproj", ProjectMarkerType.DOTNET_PROJECT, False),
    ("CMakeLists.txt", ProjectMarkerType.CMAKE_LISTS, False),
    ("composer.json", ProjectMarkerType.COMPOSER_JSON, False),
    ("Gemfile", ProjectMarkerType.GEMFILE, False),
)

HARD_EXCLUSION_NAMES: tuple[str, ...] = (
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "vendor",
    "target",
    ".gradle",
    ".idea",
    ".vscode",
    "dist",
    "build",
)


def _make_junction(link: Path, target: Path) -> None:
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
    )


# --- Ordinary eligibility -----------------------------------------------


def test_ordinary_loose_file_remains_eligible(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "a" / "b").mkdir(parents=True)
    f = root / "a" / "b" / "file.txt"
    f.write_text("x")

    result = find_structural_protection(f, root, inspect_candidate_reference=True)

    assert result is None


# --- Marker families ------------------------------------------------------


@pytest.mark.parametrize("marker_name,marker_type,is_dir", MARKER_FAMILIES)
def test_each_marker_family_establishes_protection(
    tmp_path: Path, marker_name: str, marker_type: ProjectMarkerType, is_dir: bool
) -> None:
    root = tmp_path / "root"
    project = root / "project"
    project.mkdir(parents=True)
    marker_path = project / marker_name
    if is_dir:
        marker_path.mkdir()
    else:
        marker_path.write_text("x")
    (project / "src").mkdir()
    nested = project / "src" / "main.py"
    nested.write_text("x")

    result = find_structural_protection(nested, root, inspect_candidate_reference=True)

    assert isinstance(result, StructuralProtection)
    assert result.kind is StructuralProtectionKind.PROTECTED_TREE
    assert result.marker is marker_type
    assert result.root_path == project
    assert result.marker_path == marker_path


def test_marker_matching_is_case_insensitive(tmp_path: Path) -> None:
    root = tmp_path / "root"
    project = root / "project"
    project.mkdir(parents=True)
    (project / "PyProject.TOML").write_text("x")
    f = project / "main.py"
    f.write_text("x")

    result = find_structural_protection(f, root, inspect_candidate_reference=True)

    assert isinstance(result, StructuralProtection)
    assert result.marker is ProjectMarkerType.PYPROJECT_TOML


def test_marker_file_itself_is_never_eligible(tmp_path: Path) -> None:
    root = tmp_path / "root"
    project = root / "project"
    project.mkdir(parents=True)
    marker = project / "pyproject.toml"
    marker.write_text("x")

    result = find_structural_protection(marker, root, inspect_candidate_reference=True)

    assert isinstance(result, StructuralProtection)
    assert result.root_path == project


def test_sibling_file_outside_project_remains_eligible(tmp_path: Path) -> None:
    root = tmp_path / "root"
    project = root / "project"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text("x")
    sibling = root / "invoice.pdf"
    sibling.write_text("x")

    result = find_structural_protection(sibling, root, inspect_candidate_reference=True)

    assert result is None


def test_nested_marker_beneath_already_protected_root_still_protected(
    tmp_path: Path,
) -> None:
    """A file several levels below an OUTER project marker is still
    protected even when a SECOND, nested marker also exists closer to it --
    the live re-check walks nearest-ancestor-first and correctly reports
    protection either way. Which of the two qualifying ancestors gets
    attributed doesn't change the exclusion decision itself -- both are
    genuinely protected, exactly mirroring how marker-priority-within-one-
    directory is also "which gets reported, not whether." At SCAN time
    (top-down pruning, see scanner.py), the OUTER root is what actually
    gets found and pruned first, since the inner directory is never even
    visited -- this test exercises the LIVE re-check specifically, which
    only runs at all for a path that already exists outside the ordinary
    scan-time-pruned population (e.g. historical data, §3b)."""
    root = tmp_path / "root"
    outer = root / "outer"
    outer.mkdir(parents=True)
    (outer / "pyproject.toml").write_text("x")
    inner = outer / "vendor" / "lib"
    inner.mkdir(parents=True)
    (inner / "package.json").write_text("x")
    deep_file = inner / "index.js"
    deep_file.write_text("x")

    result = find_structural_protection(
        deep_file, root, inspect_candidate_reference=True
    )

    assert isinstance(result, StructuralProtection)
    assert result.root_path in (outer, inner)


def test_symlinked_marker_does_not_establish_protection(tmp_path: Path) -> None:
    root = tmp_path / "root"
    project = root / "project"
    project.mkdir(parents=True)
    real_marker = tmp_path / "external_pyproject.toml"
    real_marker.write_text("x")
    link = project / "pyproject.toml"
    try:
        link.symlink_to(real_marker)
    except OSError:
        pytest.skip("symlink creation requires elevated privilege or Developer Mode")
    f = project / "main.py"
    f.write_text("x")

    result = find_structural_protection(f, root, inspect_candidate_reference=True)

    assert result is None


# --- Hard exclusions -------------------------------------------------------


@pytest.mark.parametrize("excluded_name", HARD_EXCLUSION_NAMES)
def test_each_hard_exclusion_name_is_recognized(excluded_name: str) -> None:
    assert is_hard_excluded_directory_name(excluded_name)
    assert is_hard_excluded_directory_name(excluded_name.upper())


@pytest.mark.parametrize("excluded_name", HARD_EXCLUSION_NAMES)
def test_each_hard_exclusion_establishes_protection(
    tmp_path: Path, excluded_name: str
) -> None:
    root = tmp_path / "root"
    excluded = root / excluded_name
    (excluded / "nested").mkdir(parents=True)
    f = excluded / "nested" / "file.js"
    f.write_text("x")

    result = find_structural_protection(f, root, inspect_candidate_reference=True)

    assert isinstance(result, StructuralProtection)
    assert result.kind is StructuralProtectionKind.HARD_EXCLUSION
    assert result.excluded_name == excluded_name


def test_ordinary_name_is_not_hard_excluded() -> None:
    assert not is_hard_excluded_directory_name("Downloads")
    assert not is_hard_excluded_directory_name("my-project")


# --- Containment precondition (review test L) ------------------------------


def test_candidate_outside_root_fails_closed_before_any_io(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x")

    calls: list[Path] = []
    original_scandir = os.scandir

    def _spy_scandir(path):  # type: ignore[no-untyped-def]
        calls.append(Path(path))
        return original_scandir(path)

    import file_agent.structural_safety as ss

    orig = ss.os.scandir
    ss.os.scandir = _spy_scandir  # type: ignore[assignment]
    try:
        result = find_structural_protection(
            outside, root, inspect_candidate_reference=True
        )
    finally:
        ss.os.scandir = orig  # type: ignore[assignment]

    assert isinstance(result, StructuralInspectionFailure)
    assert calls == []


def test_candidate_equal_to_root_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()

    result = find_structural_protection(root, root, inspect_candidate_reference=True)

    assert isinstance(result, StructuralInspectionFailure)


# --- Prospective destination absence (review test M) ------------------------


def test_prospective_destination_absence_is_not_a_failure(tmp_path: Path) -> None:
    root = tmp_path / "root"
    documents = root / "Documents"
    documents.mkdir(parents=True)
    destination = documents / "not_yet_created.pdf"
    assert not destination.exists()

    result = find_structural_protection(
        destination, root, inspect_candidate_reference=False
    )

    assert result is None


def test_prospective_destination_with_no_existing_parent_is_still_eligible(
    tmp_path: Path,
) -> None:
    """destination_path's own immediate parent category folder may not
    exist yet either -- absence alone must never surface as
    StructuralInspectionFailure; that remains inspect_destination's own,
    separate DESTINATION_PARENT_MISSING concern."""
    root = tmp_path / "root"
    root.mkdir()
    destination = root / "Documents" / "not_yet_created.pdf"

    result = find_structural_protection(
        destination, root, inspect_candidate_reference=False
    )

    assert result is None


def test_destination_leaf_itself_never_inspected(tmp_path: Path) -> None:
    """Even if something odd already sits AT destination_path (a symlink),
    inspect_candidate_reference=False means the leaf itself is never
    examined -- that remains TransactionEngine's own responsibility."""
    root = tmp_path / "root"
    root.mkdir()
    real_target = tmp_path / "external.txt"
    real_target.write_text("x")
    destination = root / "weird_symlink.txt"
    try:
        destination.symlink_to(real_target)
    except OSError:
        pytest.skip("symlink creation requires elevated privilege or Developer Mode")

    result = find_structural_protection(
        destination, root, inspect_candidate_reference=False
    )

    assert result is None


# --- Fail-closed reference-inspection uncertainty (review test K) ----------


def test_ancestor_reference_inspection_uncertainty_fails_closed_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    sub = root / "sub"
    sub.mkdir(parents=True)
    f = sub / "file.txt"
    f.write_text("x")

    original_is_symlink = Path.is_symlink

    def _raise_is_symlink(self: Path) -> bool:
        if self == sub:
            raise PermissionError("simulated failure")
        return original_is_symlink(self)

    monkeypatch.setattr(Path, "is_symlink", _raise_is_symlink)
    scandir_calls: list[Path] = []
    original_scandir = os.scandir
    monkeypatch.setattr(
        "file_agent.structural_safety.os.scandir",
        lambda p: scandir_calls.append(Path(p)) or original_scandir(p),
    )

    result = find_structural_protection(f, root, inspect_candidate_reference=True)

    assert isinstance(result, StructuralInspectionFailure)
    assert sub not in scandir_calls


def test_ancestor_reference_inspection_uncertainty_fails_closed_isjunction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    sub = root / "sub"
    sub.mkdir(parents=True)
    f = sub / "file.txt"
    f.write_text("x")

    def _raise_isjunction(path: object) -> bool:
        if Path(str(path)) == sub:
            raise PermissionError("simulated failure")
        return False

    monkeypatch.setattr(
        "file_agent.structural_safety.os.path.isjunction", _raise_isjunction
    )

    result = find_structural_protection(f, root, inspect_candidate_reference=True)

    assert isinstance(result, StructuralInspectionFailure)


def test_ancestor_reference_inspection_uncertainty_fails_closed_stat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    sub = root / "sub"
    sub.mkdir(parents=True)
    f = sub / "file.txt"
    f.write_text("x")

    original_stat = os.stat

    def _raise_stat(path, *, follow_symlinks=True):  # type: ignore[no-untyped-def]
        if Path(str(path)) == sub:
            raise PermissionError("simulated failure")
        return original_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr("file_agent.structural_safety.os.stat", _raise_stat)

    result = find_structural_protection(f, root, inspect_candidate_reference=True)

    assert isinstance(result, StructuralInspectionFailure)


def test_candidate_leaf_reference_inspection_uncertainty_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same fault-injection proof, targeting the CANDIDATE itself (source
    mode) rather than an ancestor -- review test K's explicit requirement
    to verify both."""
    root = tmp_path / "root"
    root.mkdir()
    f = root / "file.txt"
    f.write_text("x")

    original_stat = os.stat

    def _raise_stat(path, *, follow_symlinks=True):  # type: ignore[no-untyped-def]
        if Path(str(path)) == f:
            raise PermissionError("simulated failure")
        return original_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr("file_agent.structural_safety.os.stat", _raise_stat)

    result = find_structural_protection(f, root, inspect_candidate_reference=True)

    assert isinstance(result, StructuralInspectionFailure)


def test_missing_ancestor_is_normal_not_a_failure(tmp_path: Path) -> None:
    """A genuinely nonexistent ancestor (not yet created) is conclusively
    normal -- never confused with an inspection failure. Confirms the fix
    that resolved a real regression against pre-existing
    DESTINATION_PARENT_MISSING/source-already-moved behavior."""
    root = tmp_path / "root"
    root.mkdir()
    destination = root / "Documents" / "report.pdf"

    result = find_structural_protection(
        destination, root, inspect_candidate_reference=False
    )

    assert result is None


# --- Reparse-point ancestor/leaf hijack (junction-based) --------------------


def test_reparse_ancestor_fails_closed_never_lists_external_target(
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real_parent"
    real_parent.mkdir()
    root = real_parent.parent  # tmp_path itself acts as the managed root
    managed = real_parent / "managed"
    managed.mkdir()
    (managed / "file.txt").write_text("x")

    import shutil

    moved_aside = tmp_path / "real_parent_original_contents"
    shutil.move(str(real_parent), str(moved_aside))
    external_target = tmp_path / "external_target"
    external_target.mkdir()
    _make_junction(real_parent, external_target)

    candidate = real_parent / "managed" / "file.txt"
    result = find_structural_protection(
        candidate, root, inspect_candidate_reference=True
    )

    assert isinstance(result, StructuralInspectionFailure)
    assert not any(external_target.rglob("*"))


def test_reparse_leaf_hijack_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    external_target = tmp_path / "external_target"
    external_target.mkdir()
    (external_target / "secret.txt").write_text("secret")
    link = root / "file.txt"
    _make_junction(link, external_target)

    result = find_structural_protection(link, root, inspect_candidate_reference=True)

    assert isinstance(result, StructuralInspectionFailure)
