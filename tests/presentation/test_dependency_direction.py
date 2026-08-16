"""Guardrail: file_agent.presentation sits at the very top of the
dependency graph. Nothing in application/domain/destination/any engine may
ever import it -- messages are rendered strictly after a decision is
already final and must never be able to feed back into authorization or
control flow."""

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "file_agent"
NON_PRESENTATION_PACKAGES = (
    "application",
    "classifier",
    "destination",
    "domain",
    "hasher",
    "human_review_engine",
    "managed_fs",
    "persistence",
    "policy_engine",
    "proposal_engine",
    "recovery_engine",
    "scanner",
    "transaction_engine",
    "vault_engine",
)


def _imports_presentation(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "file_agent.presentation" or alias.name.startswith(
                    "file_agent.presentation."
                ):
                    return True
        if isinstance(node, ast.ImportFrom) and (
            node.module == "file_agent.presentation"
            or (
                node.module is not None
                and node.module.startswith("file_agent.presentation.")
            )
        ):
            return True
    return False


def test_no_non_presentation_package_imports_presentation() -> None:
    offenders: list[str] = []
    for package in NON_PRESENTATION_PACKAGES:
        package_dir = SRC_ROOT / package
        if not package_dir.is_dir():
            continue
        for path in package_dir.rglob("*.py"):
            if _imports_presentation(path):
                offenders.append(str(path.relative_to(SRC_ROOT)))
    assert not offenders, f"forbidden file_agent.presentation import in: {offenders}"


def test_top_level_package_init_does_not_import_presentation() -> None:
    assert not _imports_presentation(SRC_ROOT / "__init__.py")
