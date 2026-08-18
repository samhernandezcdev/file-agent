"""FA-016 scan-time structural pruning: marker-based Protected Trees and
hard exclusions are pruned during the walk itself -- zero descendant
DiscoveredFile/FILE_DISCOVERED events for anything beneath either kind, at
any nesting depth, including when the Managed Root's own directory
qualifies. Covers the review's required tests A/B (scan-time portions)."""

from pathlib import Path
from uuid import uuid4

import pytest

from file_agent.domain import EventType
from file_agent.scanner import DirectoryScanner, SandboxRoot


def _scan(root: Path) -> tuple:
    sandbox = SandboxRoot.from_path(root)
    return DirectoryScanner(sandbox, uuid4()).run(), sandbox


# --- Marker-based Protected Trees -------------------------------------------


def test_project_marker_prunes_entire_subtree(sandbox_dir: Path) -> None:
    project = sandbox_dir / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text("x")
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("x")
    loose = sandbox_dir / "invoice.pdf"
    loose.write_text("x")

    result, _ = _scan(sandbox_dir)

    assert {f.filename for f in result.files} == {"invoice.pdf"}
    assert len(result.protected_trees) == 1
    assert result.protected_trees[0].root_path == project


def test_marker_file_itself_never_discovered(sandbox_dir: Path) -> None:
    project = sandbox_dir / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text("x")

    result, _ = _scan(sandbox_dir)

    assert result.files == ()
    assert "pyproject.toml" not in {f.filename for f in result.files}


def test_protected_tree_detected_event_recorded_once_per_root(
    sandbox_dir: Path,
) -> None:
    project = sandbox_dir / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text("x")
    (project / "a.py").write_text("x")
    (project / "b.py").write_text("x")

    result, _ = _scan(sandbox_dir)

    protected_events = [
        e for e in result.events if e.event_type is EventType.PROTECTED_TREE_DETECTED
    ]
    assert len(protected_events) == 1
    assert protected_events[0].payload["root_path"] == str(project)


def test_nested_project_marker_not_separately_traversed(sandbox_dir: Path) -> None:
    outer = sandbox_dir / "outer"
    outer.mkdir()
    (outer / "pyproject.toml").write_text("x")
    inner = outer / "vendor" / "lib"
    inner.mkdir(parents=True)
    (inner / "package.json").write_text("x")
    (inner / "index.js").write_text("x")

    result, _ = _scan(sandbox_dir)

    assert result.files == ()
    assert len(result.protected_trees) == 1
    assert result.protected_trees[0].root_path == outer


def test_project_at_managed_root_root_protects_entire_root(sandbox_dir: Path) -> None:
    (sandbox_dir / "pyproject.toml").write_text("x")
    (sandbox_dir / "src").mkdir()
    (sandbox_dir / "src" / "main.py").write_text("x")

    result, sandbox = _scan(sandbox_dir)

    assert result.files == ()
    assert len(result.protected_trees) == 1
    assert result.protected_trees[0].root_path == sandbox.path


def test_project_several_levels_deep(sandbox_dir: Path) -> None:
    deep = sandbox_dir / "a" / "b" / "c" / "project"
    deep.mkdir(parents=True)
    (deep / "package.json").write_text("x")
    (deep / "index.js").write_text("x")
    loose = sandbox_dir / "a" / "b" / "loose.txt"
    loose.write_text("x")

    result, _ = _scan(sandbox_dir)

    assert {f.filename for f in result.files} == {"loose.txt"}


# --- Hard exclusions ---------------------------------------------------------


@pytest.mark.parametrize(
    "excluded_name",
    [
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
    ],
)
def test_hard_excluded_directory_never_descended(
    sandbox_dir: Path, excluded_name: str
) -> None:
    excluded = sandbox_dir / excluded_name
    excluded.mkdir()
    (excluded / "sub").mkdir()
    (excluded / "sub" / "deep.js").write_text("x")
    loose = sandbox_dir / "loose.txt"
    loose.write_text("x")

    result, _ = _scan(sandbox_dir)

    assert {f.filename for f in result.files} == {"loose.txt"}
    file_discovered = [
        e for e in result.events if e.event_type is EventType.FILE_DISCOVERED
    ]
    assert len(file_discovered) == 1
    # Silent: no protected_trees entry for a hard exclusion at scan time.
    assert result.protected_trees == ()


def test_dot_git_directory_hard_excluded(sandbox_dir: Path) -> None:
    git_dir = sandbox_dir / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main")
    (git_dir / "objects").mkdir()
    (git_dir / "objects" / "loose_object").write_text("binary-ish")

    result, _ = _scan(sandbox_dir)

    assert result.files == ()
    # .git ALSO serves as a project marker for its own containing directory
    # (sandbox_dir itself here) -- the root becomes a protected tree via the
    # marker check, not via the hard-exclusion silent path, since the
    # sandbox_dir's OWN classify_directory call sees `.git` as one of its
    # children.
    assert len(result.protected_trees) == 1
    assert result.protected_trees[0].root_path == sandbox_dir


def test_marker_inside_hard_excluded_directory_never_inspected(
    sandbox_dir: Path,
) -> None:
    """Hard-exclusion pruning takes precedence -- a package.json living
    inside node_modules/some-dep/ is never even seen, proving the exclusion
    happens before any directory listing of node_modules itself."""
    dep = sandbox_dir / "node_modules" / "some-dep"
    dep.mkdir(parents=True)
    (dep / "package.json").write_text("x")
    (dep / "index.js").write_text("x")

    result, _ = _scan(sandbox_dir)

    assert result.files == ()
    assert result.protected_trees == ()


@pytest.mark.parametrize("excluded_name", ["node_modules", ".venv", ".git"])
def test_managed_root_itself_named_hard_excluded(
    tmp_path: Path, excluded_name: str
) -> None:
    root = tmp_path / excluded_name
    root.mkdir()
    (root / "sub").mkdir()
    (root / "sub" / "file.txt").write_text("x")

    result, _ = _scan(root)

    assert result.files == ()
    assert result.protected_trees == ()
    assert result.scan_run.files_discovered == 0


def test_nested_exclusion_directory_regression(sandbox_dir: Path) -> None:
    """An ordinary project structure with an exclusion directory nested
    inside it behaves exactly as an isolated exclusion would."""
    project = sandbox_dir / "myapp"
    project.mkdir()
    (project / "index.html").write_text("x")
    node_modules = project / "node_modules"
    (node_modules / "lodash").mkdir(parents=True)
    (node_modules / "lodash" / "index.js").write_text("x")

    result, _ = _scan(sandbox_dir)

    assert {f.filename for f in result.files} == {"index.html"}
