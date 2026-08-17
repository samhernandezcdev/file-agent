"""Tests for the observable ScanRun lifecycle behavior produced by DirectoryScanner."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from file_agent.domain import ScanStatus
from file_agent.scanner import DirectoryScanner, SandboxRoot
from file_agent.scanner import scanner as scanner_module
from file_agent.scanner.issues import ScanIssueType


def test_happy_path_completes_with_correct_counts(sandbox_dir: Path) -> None:
    (sandbox_dir / "a.txt").write_text("a")
    (sandbox_dir / "b.txt").write_text("b")

    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root, uuid4()).run()

    assert result.scan_run.status == ScanStatus.COMPLETED
    assert result.scan_run.completed_at is not None
    assert result.scan_run.completed_at >= result.scan_run.started_at
    assert result.scan_run.files_discovered == 2 == len(result.files)


def test_escape_attempt_still_completes(sandbox_dir: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    link = sandbox_dir / "escape.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip(
            "symlink creation requires elevated privilege or Developer Mode on this host"
        )

    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root, uuid4()).run()

    assert result.scan_run.status == ScanStatus.COMPLETED
    assert any(
        i.issue_type == ScanIssueType.SANDBOX_ESCAPE_ATTEMPT for i in result.issues
    )


def test_root_becoming_inaccessible_fails_the_scan(
    monkeypatch: pytest.MonkeyPatch, sandbox_dir: Path
) -> None:
    root = SandboxRoot.from_path(sandbox_dir)

    def broken_scandir(path: object) -> object:
        raise PermissionError("root vanished")

    monkeypatch.setattr(scanner_module.os, "scandir", broken_scandir)

    result = DirectoryScanner(root, uuid4()).run()

    assert result.scan_run.status == ScanStatus.FAILED
    assert result.scan_run.completed_at is not None
    assert result.scan_run.files_discovered == 0
    assert any(i.issue_type == ScanIssueType.SCAN_ABORTED for i in result.issues)


def test_structural_fields_are_consistent_and_present(sandbox_dir: Path) -> None:
    before = datetime.now(UTC)
    (sandbox_dir / "a.txt").write_text("a")
    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root, uuid4()).run()
    after = datetime.now(UTC)

    assert result.scan_run.root_path == root.path
    assert before <= result.scan_run.started_at <= result.scan_run.completed_at <= after
