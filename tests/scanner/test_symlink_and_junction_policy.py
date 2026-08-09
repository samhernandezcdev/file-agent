"""Tests for symlink/junction classification policy edge cases."""

import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from file_agent.scanner import DirectoryScanner, SandboxRoot
from file_agent.scanner.issues import ScanIssueSeverity, ScanIssueType
from file_agent.scanner.scanner import DirectoryScanner as ScannerClass


def test_unclassified_reparse_point_skipped_and_not_discovered(
    monkeypatch: pytest.MonkeyPatch, sandbox_dir: Path
) -> None:
    plain_file = sandbox_dir / "placeholder.txt"
    plain_file.write_text("x")

    original_stat_entry = ScannerClass._stat_entry

    def fake_stat_entry(self: ScannerClass, entry: object) -> object:  # type: ignore[no-untyped-def]
        real = original_stat_entry(self, entry)
        if getattr(entry, "name", None) == "placeholder.txt":
            return SimpleNamespace(
                st_file_attributes=real.st_file_attributes
                | stat.FILE_ATTRIBUTE_REPARSE_POINT,
                st_mode=real.st_mode,
                st_size=real.st_size,
                st_ctime=real.st_ctime,
                st_mtime=real.st_mtime,
            )
        return real

    monkeypatch.setattr(ScannerClass, "_stat_entry", fake_stat_entry)

    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root).run()

    assert result.files == ()
    unsupported = [
        i
        for i in result.issues
        if i.issue_type == ScanIssueType.UNSUPPORTED_REPARSE_POINT
    ]
    assert len(unsupported) == 1
    assert unsupported[0].severity == ScanIssueSeverity.WARNING


def test_directory_symlink_to_own_parent_does_not_loop(sandbox_dir: Path) -> None:
    sub = sandbox_dir / "sub"
    sub.mkdir()
    (sub / "file.txt").write_text("x")
    cycle_link = sub / "parent_link"
    try:
        cycle_link.symlink_to(sandbox_dir, target_is_directory=True)
    except OSError:
        pytest.skip(
            "symlink creation requires elevated privilege or Developer Mode on this host"
        )

    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root).run()

    assert {f.filename for f in result.files} == {"file.txt"}
