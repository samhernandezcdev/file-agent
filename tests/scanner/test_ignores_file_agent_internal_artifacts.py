"""FileAgent-owned internal artifacts (currently: RecoveryEngine's reserved
restore-temp namespace) must be invisible to organization scanning -- no
DiscoveredFile, no FILE_DISCOVERED event, no hashing/classification/
proposal/policy, at the sandbox root and in recursively scanned
subdirectories. Uses reserved_artifacts.is_file_agent_internal_artifact as
the single source of truth for the reserved naming convention -- no prefix
matching is duplicated here."""

from pathlib import Path
from uuid import uuid4

from file_agent.reserved_artifacts import RESTORE_TEMP_PREFIX
from file_agent.scanner import DirectoryScanner, SandboxRoot


def _reserved_name() -> str:
    return f"{RESTORE_TEMP_PREFIX}{uuid4().hex}.partial"


def test_root_level_internal_artifact_is_skipped(sandbox_dir: Path) -> None:
    (sandbox_dir / "normal.pdf").write_bytes(b"real content")
    reserved_name = _reserved_name()
    (sandbox_dir / reserved_name).write_bytes(b"internal staging artifact")

    result = DirectoryScanner(SandboxRoot.from_path(sandbox_dir), uuid4()).run()

    discovered_names = {f.filename for f in result.files}
    assert discovered_names == {"normal.pdf"}
    assert reserved_name not in discovered_names


def test_recursive_internal_artifact_is_skipped(sandbox_dir: Path) -> None:
    folder = sandbox_dir / "folder"
    folder.mkdir()
    (folder / "normal.txt").write_bytes(b"real content")
    reserved_name = _reserved_name()
    (folder / reserved_name).write_bytes(b"internal staging artifact")

    result = DirectoryScanner(SandboxRoot.from_path(sandbox_dir), uuid4()).run()

    discovered_names = {f.filename for f in result.files}
    assert discovered_names == {"normal.txt"}
    assert reserved_name not in discovered_names


def test_near_miss_names_remain_normal_scanner_candidates(sandbox_dir: Path) -> None:
    """Names that merely contain similar text but do not match the reserved
    prefix (checked via is_file_agent_internal_artifact, not duplicated
    matching) must still be discovered."""
    near_misses = [
        "file_agent_restore.foo.partial",  # missing the leading dot
        "x.file_agent_restore.foo.partial",  # prefix not at the start
    ]
    for name in near_misses:
        (sandbox_dir / name).write_bytes(b"looks similar but is not reserved")

    result = DirectoryScanner(SandboxRoot.from_path(sandbox_dir), uuid4()).run()

    discovered_names = {f.filename for f in result.files}
    assert discovered_names == set(near_misses)


def test_skipped_artifact_produces_no_file_discovered_event(sandbox_dir: Path) -> None:
    reserved_name = _reserved_name()
    (sandbox_dir / reserved_name).write_bytes(b"internal staging artifact")

    result = DirectoryScanner(SandboxRoot.from_path(sandbox_dir), uuid4()).run()

    assert result.files == ()
    assert result.events == ()
    assert result.issues == ()
    assert result.scan_run.files_discovered == 0
