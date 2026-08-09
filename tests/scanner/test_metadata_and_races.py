"""Tests for TOCTOU handling and Windows timestamp mapping."""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from file_agent.domain import ScanStatus
from file_agent.scanner import DirectoryScanner, SandboxRoot
from file_agent.scanner import scanner as scanner_module
from file_agent.scanner.issues import ScanIssueType
from file_agent.scanner.scanner import DirectoryScanner as ScannerClass


def test_file_vanishing_between_listing_and_stat_is_recoverable(
    monkeypatch: pytest.MonkeyPatch, sandbox_dir: Path
) -> None:
    (sandbox_dir / "gone.txt").write_text("x")
    (sandbox_dir / "stays.txt").write_text("y")

    original_stat_entry = ScannerClass._stat_entry

    def flaky_stat_entry(self: ScannerClass, entry: object) -> object:  # type: ignore[no-untyped-def]
        if getattr(entry, "name", None) == "gone.txt":
            raise FileNotFoundError("vanished")
        return original_stat_entry(self, entry)

    monkeypatch.setattr(ScannerClass, "_stat_entry", flaky_stat_entry)

    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root).run()

    assert {f.filename for f in result.files} == {"stays.txt"}
    not_found = [i for i in result.issues if i.issue_type == ScanIssueType.NOT_FOUND]
    assert len(not_found) == 1


def test_permission_denied_on_file_is_recoverable(
    monkeypatch: pytest.MonkeyPatch, sandbox_dir: Path
) -> None:
    (sandbox_dir / "locked.txt").write_text("x")
    (sandbox_dir / "open.txt").write_text("y")

    original_stat_entry = ScannerClass._stat_entry

    def flaky_stat_entry(self: ScannerClass, entry: object) -> object:  # type: ignore[no-untyped-def]
        if getattr(entry, "name", None) == "locked.txt":
            raise PermissionError("denied")
        return original_stat_entry(self, entry)

    monkeypatch.setattr(ScannerClass, "_stat_entry", flaky_stat_entry)

    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root).run()

    assert {f.filename for f in result.files} == {"open.txt"}
    denied = [
        i for i in result.issues if i.issue_type == ScanIssueType.PERMISSION_DENIED
    ]
    assert len(denied) == 1


def test_permission_denied_listing_subdirectory_skips_subtree(
    monkeypatch: pytest.MonkeyPatch, sandbox_dir: Path
) -> None:
    locked_dir = sandbox_dir / "locked_dir"
    locked_dir.mkdir()
    (locked_dir / "secret.txt").write_text("x")
    (sandbox_dir / "visible.txt").write_text("y")

    real_scandir = os.scandir

    def flaky_scandir(path: object) -> object:
        if Path(str(path)) == locked_dir:
            raise PermissionError("denied")
        return real_scandir(path)  # type: ignore[arg-type]

    monkeypatch.setattr(scanner_module.os, "scandir", flaky_scandir)

    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root).run()

    assert {f.filename for f in result.files} == {"visible.txt"}
    denied = [
        i for i in result.issues if i.issue_type == ScanIssueType.PERMISSION_DENIED
    ]
    assert len(denied) == 1
    assert result.scan_run.status == ScanStatus.COMPLETED


def test_windows_timestamp_mapping(sandbox_dir: Path) -> None:
    target = sandbox_dir / "timed.txt"
    target.write_text("x")
    real_stat = os.stat(target)

    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root).run()

    discovered = next(f for f in result.files if f.filename == "timed.txt")
    assert discovered.created_at == datetime.fromtimestamp(real_stat.st_ctime, tz=UTC)
    assert discovered.modified_at == datetime.fromtimestamp(real_stat.st_mtime, tz=UTC)
