"""Guardrail: file_agent.structural_safety is stdlib-only -- Round 2/3's
Major 3 fix. Zero imports from scanner, application, persistence, domain,
transaction_engine, recovery_engine, or anywhere else in file_agent. This is
what makes it safe for BOTH scanner/ (scan-time pruning) and application/
(live re-verification) to import it without creating any risk of an import
cycle -- `structural_safety` never imports either of them back."""

import ast
from pathlib import Path

STRUCTURAL_SAFETY_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "file_agent" / "structural_safety"
)


def _file_agent_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "file_agent" or alias.name.startswith("file_agent."):
                    offenders.append(f"import {alias.name}")
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (node.module == "file_agent" or node.module.startswith("file_agent."))
        ):
            offenders.append(f"from {node.module} import ...")
    return offenders


def test_structural_safety_imports_nothing_from_file_agent() -> None:
    source_files = sorted(STRUCTURAL_SAFETY_DIR.glob("*.py"))
    assert source_files, f"expected source files under {STRUCTURAL_SAFETY_DIR}"

    offenders: list[str] = []
    for path in source_files:
        offenders.extend(f"{path.name}: {v}" for v in _file_agent_imports(path))

    assert not offenders, (
        f"structural_safety/ must be stdlib-only -- found file_agent imports: "
        f"{offenders}"
    )


def test_scanner_and_application_actually_import_structural_safety() -> None:
    """Sanity check against a vacuous dependency-direction proof: confirms
    both intended consumers genuinely wire up to this package, so the
    "stdlib-only" guarantee above is meaningfully protecting a real,
    two-directional dependency shape -- not an unused package nobody
    imports."""
    src_root = STRUCTURAL_SAFETY_DIR.parent
    scanner_files = list((src_root / "scanner").glob("*.py"))
    application_files = list((src_root / "application").glob("*.py"))

    def _imports_structural_safety(path: Path) -> bool:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "file_agent.structural_safety" or (
                        alias.name.startswith("file_agent.structural_safety.")
                    ):
                        return True
            if (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
                and (
                    node.module == "file_agent.structural_safety"
                    or node.module.startswith("file_agent.structural_safety.")
                )
            ):
                return True
        return False

    assert any(_imports_structural_safety(p) for p in scanner_files), (
        "expected at least one scanner/ file to import file_agent.structural_safety"
    )
    assert any(_imports_structural_safety(p) for p in application_files), (
        "expected at least one application/ file to import file_agent.structural_safety"
    )
