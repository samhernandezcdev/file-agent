"""Happy-path enumeration tests for DirectoryScanner."""

from pathlib import Path

from file_agent.scanner import DirectoryScanner, SandboxRoot


def test_nested_files_discovered(sandbox_dir: Path) -> None:
    (sandbox_dir / "a.txt").write_text("a")
    nested = sandbox_dir / "sub"
    nested.mkdir()
    (nested / "b.PDF").write_text("b")
    (nested / "LICENSE").write_text("no ext")
    (nested / "archive.tar.gz").write_text("gz")

    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root).run()

    discovered_names = {f.filename for f in result.files}
    assert discovered_names == {"a.txt", "b.PDF", "LICENSE", "archive.tar.gz"}
    extensions = {f.filename: f.extension for f in result.files}
    assert extensions["b.PDF"] == "pdf"
    assert extensions["LICENSE"] == ""
    assert extensions["archive.tar.gz"] == "gz"


def test_empty_directories_produce_no_issues(sandbox_dir: Path) -> None:
    (sandbox_dir / "empty").mkdir()
    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root).run()
    assert result.files == ()
    assert result.issues == ()
    assert result.scan_run.files_discovered == 0


def test_files_discovered_count_matches(sandbox_dir: Path) -> None:
    for i in range(5):
        (sandbox_dir / f"f{i}.txt").write_text(str(i))
    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root).run()
    assert len(result.files) == 5
    assert result.scan_run.files_discovered == 5
    assert len(result.events) == 5


def test_sha256_is_none_for_discovered_files(sandbox_dir: Path) -> None:
    (sandbox_dir / "a.txt").write_text("a")
    root = SandboxRoot.from_path(sandbox_dir)
    result = DirectoryScanner(root).run()
    assert result.files[0].sha256 is None
