"""Lightweight tests for scripts/demo_preview.py's pure helper functions.

DEV-DEMO-001 is a developer/demo utility, not product code -- this is
intentionally a small, focused test file, not a full test subsystem. It
loads the script by file path (it is not part of the installed file_agent
package) and exercises only its pure, side-effect-free helpers.
"""

import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "demo_preview.py"


@pytest.fixture(scope="module")
def demo_preview() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("demo_preview", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_relative_returns_em_dash_for_none(demo_preview: types.ModuleType) -> None:
    assert demo_preview._relative(None, Path("C:/root")) == "—"


def test_relative_returns_relative_path_when_inside_root(
    demo_preview: types.ModuleType,
) -> None:
    root = Path("C:/root")
    result = demo_preview._relative(root / "Documents" / "a.pdf", root)
    assert result == str(Path("Documents") / "a.pdf")


def test_relative_falls_back_to_absolute_path_when_outside_root(
    demo_preview: types.ModuleType,
) -> None:
    root = Path("C:/root")
    outside = Path("C:/elsewhere/a.pdf")
    assert demo_preview._relative(outside, root) == str(outside)


def test_seed_fixtures_produces_the_documented_fixture_set(
    demo_preview: types.ModuleType, tmp_path: Path
) -> None:
    demo_preview._seed_fixtures(tmp_path)

    for name in (
        "invoice.pdf",
        "photo.jpg",
        "archive.zip",
        "script.py",
        "setup.exe",
        "mystery.xyz123",
        "report.pdf",
    ):
        assert (tmp_path / name).is_file(), f"missing fixture: {name}"

    # the deliberate conflict: destination pre-occupied by DIFFERENT content
    conflict_target = tmp_path / "Documents" / "report.pdf"
    assert conflict_target.is_file()
    assert (tmp_path / "report.pdf").read_bytes() != conflict_target.read_bytes()


def test_snapshot_detects_content_changes(
    demo_preview: types.ModuleType, tmp_path: Path
) -> None:
    demo_preview._seed_fixtures(tmp_path)
    before = demo_preview._snapshot(tmp_path)

    (tmp_path / "invoice.pdf").write_bytes(b"changed content")

    after = demo_preview._snapshot(tmp_path)
    assert before != after
    assert demo_preview._snapshot(tmp_path) == after  # stable/idempotent re-snapshot


def test_script_never_calls_apply_items() -> None:
    """demo_preview.py stays a read-only preview under every flag
    combination -- apply_items() (a real, mutating batch-apply call) must
    never appear in its source at all."""
    source = _SCRIPT_PATH.read_text(encoding="utf-8")
    assert "apply_items" not in source


def test_lang_es_flag_renders_spanish_section_headings_and_reasons() -> None:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), "--lang", "es"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "No pudimos" in result.stdout or "Necesita tu aprobación" in result.stdout
    assert "CONFLICTS" not in result.stdout


def test_default_lang_keeps_raw_technical_rendering_unchanged() -> None:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "CONFLICTS" in result.stdout
