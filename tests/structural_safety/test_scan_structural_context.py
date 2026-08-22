"""FA-017.7B.3 ScanStructuralContext: proves the scan-scoped ancestor-fact
cache reuses shared-ancestor work correctly while never weakening any
existing structural-safety guarantee -- candidate-leaf freshness, sibling
isolation, parent replacement/rename/content-change detection, fail-closed
lookup failures, never positively caching a failure, and complete
isolation between separate contexts (no module-global or cross-invocation
state)."""

import os
import subprocess
from pathlib import Path

import pytest

from file_agent.structural_safety import (
    ScanStructuralContext,
    StructuralInspectionFailure,
    StructuralProtection,
    StructuralProtectionKind,
)


def _make_junction(link: Path, target: Path) -> None:
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
    )


# --- Part 15: shared-ancestor reuse ------------------------------------------


def test_shared_ancestor_scanned_once_for_many_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    files = []
    for i in range(25):
        f = root / f"file_{i:03d}.txt"
        f.write_text("x")
        files.append(f)

    scandir_calls = {"count": 0}
    real_scandir = os.scandir

    def _counted_scandir(path):  # type: ignore[no-untyped-def]
        scandir_calls["count"] += 1
        return real_scandir(path)

    monkeypatch.setattr("file_agent.structural_safety.os.scandir", _counted_scandir)

    context = ScanStructuralContext(root)
    results = [
        context.check_candidate(f, inspect_candidate_reference=True) for f in files
    ]

    assert all(result is None for result in results)
    # Exactly one full directory listing of `root`, not 25 -- the whole
    # point of the cache.
    assert scandir_calls["count"] == 1


# --- Part 16: normal flat/nested, sibling isolation --------------------------


def test_normal_flat_directory_all_eligible(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    f = root / "file.txt"
    f.write_text("x")
    context = ScanStructuralContext(root)
    assert context.check_candidate(f, inspect_candidate_reference=True) is None


def test_normal_nested_directory_all_eligible(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "a" / "b").mkdir(parents=True)
    f = root / "a" / "b" / "file.txt"
    f.write_text("x")
    context = ScanStructuralContext(root)
    assert context.check_candidate(f, inspect_candidate_reference=True) is None


def test_sibling_directory_does_not_inherit_anothers_cached_result(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    protected = root / "protected"
    protected.mkdir(parents=True)
    (protected / "pyproject.toml").write_text("")
    clean = root / "clean"
    clean.mkdir()

    protected_file = protected / "file.txt"
    protected_file.write_text("x")
    clean_file = clean / "file.txt"
    clean_file.write_text("x")

    context = ScanStructuralContext(root)
    protected_result = context.check_candidate(
        protected_file, inspect_candidate_reference=True
    )
    clean_result = context.check_candidate(clean_file, inspect_candidate_reference=True)

    assert isinstance(protected_result, StructuralProtection)
    assert protected_result.kind is StructuralProtectionKind.PROTECTED_TREE
    assert clean_result is None


# --- Part 17: candidate leaf always fresh ------------------------------------


def test_candidate_leaf_rechecked_fresh_even_after_parent_cached(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    other = root / "other.txt"
    other.write_text("x")
    target = tmp_path / "external"
    target.mkdir()

    context = ScanStructuralContext(root)
    # Populate the cache for `root` via an unrelated file first.
    assert context.check_candidate(other, inspect_candidate_reference=True) is None

    # Now the candidate itself becomes a junction -- the shared ancestor
    # (root) is unchanged and would still hit the cache, but the leaf
    # check must never be skipped or inferred from the ancestor's cached
    # "clear" fact.
    hijacked = root / "hijacked"
    _make_junction(hijacked, target)

    result = context.check_candidate(hijacked, inspect_candidate_reference=True)
    assert isinstance(result, StructuralInspectionFailure)
    assert "candidate itself is a symlink, junction, or reparse point" in result.detail


# --- Part 18: parent replacement adversarial test ----------------------------


def test_parent_replaced_with_junction_after_caching_is_detected(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    sub = root / "sub"
    sub.mkdir(parents=True)
    first = sub / "first.txt"
    first.write_text("x")
    external = tmp_path / "external"
    external.mkdir()

    context = ScanStructuralContext(root)
    # First candidate populates the cache entry for `sub`.
    assert context.check_candidate(first, inspect_candidate_reference=True) is None

    # Replace `sub` itself with a junction after it was cached as clear.
    import shutil

    shutil.rmtree(sub)
    _make_junction(sub, external)

    second = sub / "second.txt"  # path string only -- sub now redirects externally
    result = context.check_candidate(second, inspect_candidate_reference=True)

    assert isinstance(result, StructuralInspectionFailure)
    assert "ancestor is a symlink, junction, or reparse point" in result.detail


def test_ancestor_renamed_out_of_hard_exclusion_after_caching_is_detected(
    tmp_path: Path,
) -> None:
    """A directory keeps the same inode across an in-place rename on
    NTFS -- proves the cache's name check (not identity alone) catches a
    hard-excluded directory being renamed to a non-excluded name."""
    root = tmp_path / "root"
    excluded = root / "node_modules"
    excluded.mkdir(parents=True)
    f = excluded / "file.txt"
    f.write_text("x")

    context = ScanStructuralContext(root)
    first = context.check_candidate(f, inspect_candidate_reference=True)
    assert isinstance(first, StructuralProtection)
    assert first.kind is StructuralProtectionKind.HARD_EXCLUSION

    renamed = root / "renamed"
    excluded.rename(renamed)
    f2 = renamed / "file.txt"

    second = context.check_candidate(f2, inspect_candidate_reference=True)
    assert second is None


def test_marker_added_to_cached_clear_ancestor_is_detected(tmp_path: Path) -> None:
    """A directory's own mtime changes when its immediate children
    change -- proves the cache's mtime check catches a project marker
    appearing in an ancestor that was already cached as clear.

    NTFS write-timestamp granularity/coalescing under rapid, back-to-back
    filesystem operations (as in a fast test suite) can occasionly make
    two immediately-successive mtimes compare equal even though a real,
    externally-observable change occurred -- polling with a short sleep
    guarantees a detectable tick without weakening what's being proven
    (a real production TOCTOU window is measured in at least
    milliseconds of real work between files, never this granularity)."""
    import time

    root = tmp_path / "root"
    project = root / "project"
    project.mkdir(parents=True)
    f = project / "file.txt"
    f.write_text("x")

    context = ScanStructuralContext(root)
    first = context.check_candidate(f, inspect_candidate_reference=True)
    assert first is None
    cached_mtime = os.stat(project, follow_symlinks=False).st_mtime

    # Directory mtime advances on structure changes (entries added/
    # removed), not on rewriting an existing entry's content -- each
    # retry must add a genuinely new, distinctly-named entry.
    for i in range(20):
        (project / f"decoy_{i}.tmp").write_text("")
        if os.stat(project, follow_symlinks=False).st_mtime != cached_mtime:
            break
        time.sleep(0.01)
    else:
        pytest.fail("directory mtime never advanced after adding new entries")
    (project / "pyproject.toml").write_text("")
    f2 = project / "another.txt"
    f2.write_text("y")

    second = context.check_candidate(f2, inspect_candidate_reference=True)
    assert isinstance(second, StructuralProtection)
    assert second.kind is StructuralProtectionKind.PROTECTED_TREE


# --- Part 19: lookup failure never trusts a stale cache ----------------------


def test_lookup_failure_during_revalidation_does_not_trust_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    first = root / "first.txt"
    first.write_text("x")
    second = root / "second.txt"
    second.write_text("y")

    context = ScanStructuralContext(root)
    assert context.check_candidate(first, inspect_candidate_reference=True) is None

    original_stat = os.stat

    def _raise_stat(path, *, follow_symlinks=True):  # type: ignore[no-untyped-def]
        if Path(str(path)) == root:
            raise PermissionError("simulated failure")
        return original_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr("file_agent.structural_safety.os.stat", _raise_stat)

    result = context.check_candidate(second, inspect_candidate_reference=True)
    assert isinstance(result, StructuralInspectionFailure)


def test_inspection_failure_is_never_cached_as_a_positive_fact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    first = root / "first.txt"
    first.write_text("x")
    second = root / "second.txt"
    second.write_text("y")

    original_stat = os.stat
    fail_next = {"value": True}

    def _sometimes_raise_stat(path, *, follow_symlinks=True):  # type: ignore[no-untyped-def]
        if Path(str(path)) == root and fail_next["value"]:
            fail_next["value"] = False
            raise PermissionError("simulated failure")
        return original_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr("file_agent.structural_safety.os.stat", _sometimes_raise_stat)

    context = ScanStructuralContext(root)
    first_result = context.check_candidate(first, inspect_candidate_reference=True)
    assert isinstance(first_result, StructuralInspectionFailure)

    # The failure must not have been cached as a reusable "clear" fact --
    # the second candidate re-attempts the full inspection fresh and
    # succeeds now that the fault is no longer injected.
    second_result = context.check_candidate(second, inspect_candidate_reference=True)
    assert second_result is None


def test_missing_ancestor_is_never_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    not_yet_created = root / "future"
    candidate = not_yet_created / "file.txt"

    scandir_calls = {"count": 0}
    real_scandir = os.scandir

    def _counted_scandir(path):  # type: ignore[no-untyped-def]
        scandir_calls["count"] += 1
        return real_scandir(path)

    monkeypatch.setattr("file_agent.structural_safety.os.scandir", _counted_scandir)

    context = ScanStructuralContext(root)
    # `not_yet_created` doesn't exist -- candidate reference is skipped
    # (destination mode), only its ancestor chain matters.
    result1 = context.check_candidate(candidate, inspect_candidate_reference=False)
    assert result1 is None

    not_yet_created.mkdir()
    (not_yet_created / "pyproject.toml").write_text("")
    result2 = context.check_candidate(candidate, inspect_candidate_reference=False)

    # A now-created, now-protected ancestor is correctly detected --
    # proving the earlier "missing" observation was never cached as
    # "clear" for this ancestor.
    assert isinstance(result2, StructuralProtection)


# --- Part 20: complete isolation between contexts ----------------------------


def test_two_contexts_never_share_cache_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    f = root / "file.txt"
    f.write_text("x")

    scandir_calls = {"count": 0}
    real_scandir = os.scandir

    def _counted_scandir(path):  # type: ignore[no-untyped-def]
        scandir_calls["count"] += 1
        return real_scandir(path)

    monkeypatch.setattr("file_agent.structural_safety.os.scandir", _counted_scandir)

    context_a = ScanStructuralContext(root)
    context_a.check_candidate(f, inspect_candidate_reference=True)
    assert scandir_calls["count"] == 1

    # A brand-new context for the "same" root (e.g. a second
    # analyze_managed_root/analyze_file/build_organization_plan
    # invocation) must re-derive everything fresh -- no module-global,
    # no shared cache of any kind.
    context_b = ScanStructuralContext(root)
    context_b.check_candidate(f, inspect_candidate_reference=True)
    assert scandir_calls["count"] == 2
