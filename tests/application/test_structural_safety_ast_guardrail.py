"""FA-016 structural guardrail: application/ never reimplements ad-hoc
marker/exclusion detection -- every live structural-safety decision must go
through structural_safety.find_structural_protection, the ONE shared,
live-reinspecting primitive (see that module's own docstring). A future
accidental call to structural_safety.classify_directory/
is_hard_excluded_directory_name, or a bare os.scandir(...) used to
hand-roll an equivalent check, would silently reintroduce the exact
live-authority-bypass FA-016 exists to close -- this guardrail fails the
build immediately if one appears.

classify_directory/is_hard_excluded_directory_name ARE legitimately called
directly in scanner/scanner.py (the sanctioned scan-time entry point,
reusing already-materialized os.scandir results) -- this guardrail's scope
is strictly application/*.py, mirroring
tests/application/test_managed_root_ast_guardrail.py's identical structure
for FA-015's own single-primitive discipline."""

import ast
from pathlib import Path

APPLICATION_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "file_agent" / "application"
)

_BANNED_CALL_NAMES = {"classify_directory", "is_hard_excluded_directory_name"}


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _offending_calls(tree: ast.Module) -> list[str]:
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # structural_safety.classify_directory(...) / bare classify_directory(...)
        if isinstance(func, ast.Attribute) and func.attr in _BANNED_CALL_NAMES:
            offenders.append(f"line {node.lineno}: {_dotted_name(func)}(")
        if isinstance(func, ast.Name) and func.id in _BANNED_CALL_NAMES:
            offenders.append(f"line {node.lineno}: {func.id}(")
        # bare os.scandir(...) -- the raw primitive find_structural_protection
        # itself wraps; application/ must never call it directly to hand-roll
        # an equivalent structural check.
        if isinstance(func, ast.Attribute) and func.attr == "scandir":
            dotted = _dotted_name(func)
            if dotted == "os.scandir":
                offenders.append(f"line {node.lineno}: os.scandir(")
    return offenders


def test_application_never_reimplements_structural_safety_ad_hoc() -> None:
    source_files = sorted(APPLICATION_DIR.glob("*.py"))
    assert source_files, f"expected application source files under {APPLICATION_DIR}"

    offenders: list[str] = []
    for path in source_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders.extend(f"{path.name}: {v}" for v in _offending_calls(tree))

    assert not offenders, (
        "application/ must route every live structural-safety decision "
        f"through find_structural_protection -- offending call sites: {offenders}"
    )


def test_find_structural_protection_is_actually_used_in_application() -> None:
    """Sanity check against a vacuous guardrail: if a future refactor
    removes every find_structural_protection call from application/ (e.g.
    routing through a new wrapper), this test fails loudly rather than
    letting the guardrail above silently stop testing anything real."""
    source_files = sorted(APPLICATION_DIR.glob("*.py"))

    found = False
    for path in source_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "find_structural_protection"
            ):
                found = True
                break
        if found:
            break

    assert found, (
        "expected at least one application/ file to call "
        "find_structural_protection -- update this guardrail's assumptions "
        "if the call shape genuinely changed"
    )
