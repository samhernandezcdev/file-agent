"""Guardrail: application/ never constructs a fabricated
PolicyDecision(decision=AUTO) -- via model_copy or any other mechanism -- to
route a REVIEW+APPROVE item through TransactionEngine's authorization check.
Execution authorization must flow exclusively through
ExecutionAuthorization.from_policy_auto/from_human_approval; the persisted
PolicyDecision.decision is never rewritten.

Also proves the corresponding, narrower claim for ExecutionAuthorization
itself: application/ never calls the plain ExecutionAuthorization(...)
constructor directly -- only .from_policy_auto(...)/.from_human_approval(...)
-- even though direct construction is technically possible (it is a plain
Pydantic BaseModel, not a private-constructor type; see
file_agent.domain.authorization's module docstring for why that is an
accepted, documented trust-boundary property rather than a bug)."""

import ast
from pathlib import Path

APPLICATION_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "file_agent" / "application"
)


def _fabrication_sites(tree: ast.AST) -> list[str]:
    """Flags any dict literal shaped like {"decision": SomeEnum.AUTO, ...} --
    the exact fabrication pattern this guardrail exists to catch, regardless
    of which call it's passed to (model_copy, a constructor, or anything
    else)."""
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=False):
            if (
                isinstance(key, ast.Constant)
                and key.value == "decision"
                and isinstance(value, ast.Attribute)
                and value.attr == "AUTO"
            ):
                offenders.append(f"line {node.lineno}: dict with decision=...AUTO")
    return offenders


def test_application_never_fabricates_an_auto_policy_decision() -> None:
    source_files = sorted(APPLICATION_DIR.glob("*.py"))
    assert source_files, f"expected application source files under {APPLICATION_DIR}"

    offenders: list[str] = []
    for path in source_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders.extend(f"{path.name}: {v}" for v in _fabrication_sites(tree))

    assert not offenders, f"AUTO-fabrication pattern found in: {offenders}"


def test_application_never_rewrites_policy_decision_via_model_copy() -> None:
    """No file in application/ calls .model_copy( on a PolicyDecision-typed
    value at all -- the only legitimate model_copy use in this package today
    (DiscoveredFile re-stat in analyze_file) is on a DiscoveredFile, never a
    PolicyDecision."""
    source_files = sorted(APPLICATION_DIR.glob("*.py"))

    offenders: list[str] = []
    for path in source_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "model_copy"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "policy_decision"
            ):
                offenders.append(
                    f"{path.name}:{node.lineno}: policy_decision.model_copy("
                )

    assert not offenders, f"PolicyDecision.model_copy(...) found in: {offenders}"


def test_application_constructs_execution_authorization_only_via_factories() -> None:
    """Every ExecutionAuthorization(...) call in application/ must be a
    .from_policy_auto(...) or .from_human_approval(...) classmethod call --
    never the plain constructor. This is a call-site discipline check, not a
    claim that the plain constructor is inaccessible (it is not -- see the
    module docstring)."""
    source_files = sorted(APPLICATION_DIR.glob("*.py"))

    offenders: list[str] = []
    for path in source_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # Direct construction: ExecutionAuthorization(...)
            if isinstance(func, ast.Name) and func.id == "ExecutionAuthorization":
                offenders.append(f"{path.name}:{node.lineno}: ExecutionAuthorization(")
            # Anything on ExecutionAuthorization other than the two
            # sanctioned factory names.
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "ExecutionAuthorization"
                and func.attr not in ("from_policy_auto", "from_human_approval")
            ):
                offenders.append(
                    f"{path.name}:{node.lineno}: ExecutionAuthorization.{func.attr}("
                )

    assert not offenders, (
        f"non-factory ExecutionAuthorization construction: {offenders}"
    )
