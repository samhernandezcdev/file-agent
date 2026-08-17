"""Tests for sandbox containment enforcement against symlinks/junctions."""

import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from file_agent.domain import ScanStatus
from file_agent.scanner import DirectoryScanner, SandboxRoot
from file_agent.scanner.issues import ScanIssueSeverity, ScanIssueType


def _make_symlink(link: Path, target: Path, *, target_is_directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError:
        pytest.skip(
            "symlink creation requires elevated privilege or Developer Mode on this host"
        )


def _make_junction(link: Path, target: Path) -> None:
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
    )


def test_file_symlink_escaping_sandbox(tmp_path: Path, sandbox_dir: Path) -> None:
    outside_target = tmp_path / "outside.txt"
    outside_target.write_text("secret")
    link = sandbox_dir / "escape.txt"
    _make_symlink(link, outside_target, target_is_directory=False)

    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root, uuid4()).run()

    assert result.files == ()
    assert result.scan_run.status == ScanStatus.COMPLETED
    escape_issues = [
        i for i in result.issues if i.issue_type == ScanIssueType.SANDBOX_ESCAPE_ATTEMPT
    ]
    assert len(escape_issues) == 1
    assert escape_issues[0].severity == ScanIssueSeverity.CRITICAL


def test_directory_symlink_escaping_sandbox(tmp_path: Path, sandbox_dir: Path) -> None:
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_text("secret")
    link = sandbox_dir / "escape_dir"
    _make_symlink(link, outside_dir, target_is_directory=True)

    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root, uuid4()).run()

    assert result.files == ()
    escape_issues = [
        i for i in result.issues if i.issue_type == ScanIssueType.SANDBOX_ESCAPE_ATTEMPT
    ]
    assert len(escape_issues) == 1


def test_symlink_targeting_inside_sandbox_not_followed(sandbox_dir: Path) -> None:
    real_dir = sandbox_dir / "real"
    real_dir.mkdir()
    (real_dir / "inside.txt").write_text("hi")
    link = sandbox_dir / "link_inside"
    _make_symlink(link, real_dir, target_is_directory=True)

    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root, uuid4()).run()

    assert {f.filename for f in result.files} == {"inside.txt"}
    info_issues = [
        i for i in result.issues if i.issue_type == ScanIssueType.SYMLINK_NOT_FOLLOWED
    ]
    assert len(info_issues) == 1
    assert info_issues[0].severity == ScanIssueSeverity.INFO
    assert result.scan_run.status == ScanStatus.COMPLETED


def test_junction_escaping_sandbox(tmp_path: Path, sandbox_dir: Path) -> None:
    outside_dir = tmp_path / "outside_junction_target"
    outside_dir.mkdir()
    link = sandbox_dir / "escape_junction"
    _make_junction(link, outside_dir)

    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root, uuid4()).run()

    escape_issues = [
        i for i in result.issues if i.issue_type == ScanIssueType.SANDBOX_ESCAPE_ATTEMPT
    ]
    assert len(escape_issues) == 1
    assert result.scan_run.status == ScanStatus.COMPLETED


def test_junction_targeting_inside_sandbox_not_followed(sandbox_dir: Path) -> None:
    real_dir = sandbox_dir / "real2"
    real_dir.mkdir()
    (real_dir / "inside2.txt").write_text("hi")
    link = sandbox_dir / "junction_inside"
    _make_junction(link, real_dir)

    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root, uuid4()).run()

    junction_issues = [
        i for i in result.issues if i.issue_type == ScanIssueType.JUNCTION_NOT_FOLLOWED
    ]
    assert len(junction_issues) == 1
    # inside2.txt is discovered exactly once, via the real "real2" directory —
    # the junction pointing at the same target is not independently walked,
    # so it must not produce a duplicate discovery.
    assert [f.filename for f in result.files] == ["inside2.txt"]


def test_broken_symlink_is_unresolvable_not_escape(
    sandbox_dir: Path, tmp_path: Path
) -> None:
    vanishing_target = tmp_path / "vanishing.txt"
    vanishing_target.write_text("x")
    link = sandbox_dir / "broken.txt"
    _make_symlink(link, vanishing_target, target_is_directory=False)
    vanishing_target.unlink()

    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root, uuid4()).run()

    unresolvable = [
        i for i in result.issues if i.issue_type == ScanIssueType.UNRESOLVABLE_REFERENCE
    ]
    escape = [
        i for i in result.issues if i.issue_type == ScanIssueType.SANDBOX_ESCAPE_ATTEMPT
    ]
    assert len(unresolvable) == 1
    assert unresolvable[0].severity == ScanIssueSeverity.WARNING
    assert escape == []
    assert result.scan_run.status == ScanStatus.COMPLETED
