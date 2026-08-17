"""OrganizationPlan / preview (FA-013): trust boundary and the
shared-destination-inspection agreement invariant between OrganizationPlanner
and TransactionEngine."""

import ast
import inspect
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from file_agent.application import FileAgentApplicationService
from file_agent.scanner import SandboxRoot

PLANNER_FILE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "file_agent"
    / "application"
    / "planner.py"
)

FORBIDDEN_ANNOTATION_SUBSTRINGS = (
    "ExecutionAuthorization",
    "TransactionRequest",
    "PolicyDecision",
    "HumanReviewDecision",
    "DestinationInspection",
    "DestinationConflict",
    "_Prepared",
    "Prepared",
)


def test_create_organization_plan_signature_accepts_only_a_sequence_of_uuids() -> None:
    signature = inspect.signature(FileAgentApplicationService.create_organization_plan)
    params = {
        name: param for name, param in signature.parameters.items() if name != "self"
    }
    assert list(params) == ["policy_decision_ids"]
    annotation = str(params["policy_decision_ids"].annotation)
    assert "Sequence" in annotation
    assert "UUID" in annotation
    for forbidden in FORBIDDEN_ANNOTATION_SUBSTRINGS:
        assert forbidden not in annotation


def test_organization_plan_item_fields_expose_no_trust_bearing_type() -> None:
    from file_agent.application.organization_plan import OrganizationPlanItem

    for field in OrganizationPlanItem.__dataclass_fields__.values():
        annotation = str(field.type)
        for forbidden in FORBIDDEN_ANNOTATION_SUBSTRINGS:
            assert forbidden not in annotation, (
                f"OrganizationPlanItem.{field.name} exposes forbidden type {forbidden}"
            )


def test_planner_never_constructs_execution_authorization() -> None:
    """AST guardrail: application/planner.py contains no
    ExecutionAuthorization(...) call, and no .from_policy_auto(/
    .from_human_approval( call either -- OrganizationPlanner never
    authorizes anything, it only observes."""
    tree = ast.parse(
        PLANNER_FILE.read_text(encoding="utf-8"), filename=str(PLANNER_FILE)
    )
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "ExecutionAuthorization":
            offenders.append(f"line {node.lineno}: ExecutionAuthorization(")
        if isinstance(func, ast.Attribute) and func.attr in (
            "from_policy_auto",
            "from_human_approval",
        ):
            offenders.append(f"line {node.lineno}: .{func.attr}(")

    assert not offenders, f"planner.py constructs authorization: {offenders}"


def test_planner_never_calls_engines_or_records_review() -> None:
    """AST/import-scan guardrail: application/planner.py never imports
    TransactionEngine, RecoveryEngine, or HumanReviewEngine, and never calls
    a .record(/.prepare(/.commit( method -- it only reads."""
    source = PLANNER_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(PLANNER_FILE))

    forbidden_modules = (
        "transaction_engine",
        "recovery_engine",
        "human_review_engine",
        "managed_fs",
    )
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.append(node.module)
    offending_imports = [
        module
        for module in imported_modules
        if any(forbidden in module for forbidden in forbidden_modules)
    ]
    assert not offending_imports, f"planner.py imports: {offending_imports}"

    forbidden_method_calls = {"prepare", "commit", "record"}
    offenders = [
        f"line {node.lineno}: .{node.func.attr}("
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in forbidden_method_calls
    ]
    assert not offenders, f"planner.py calls an engine mutation method: {offenders}"


def test_shared_inspection_agreement_between_planner_and_transaction_engine(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    """The required invariant: given identical filesystem state and
    identical destination inputs, OrganizationPlan and TransactionEngine
    agree on every shared destination-readiness condition, because they
    both call the literal same destination.inspect_destination function."""
    from file_agent.destination import inspection as inspection_module

    make_source_file("invoice.pdf", content=b"pdf")
    item = service.analyze_managed_root(managed_root_id).items[0]
    # Pre-occupy the destination -- both layers should independently detect
    # ALREADY_OCCUPIED via inspect_destination.
    (sandbox_root.path / "Documents" / "invoice.pdf").write_bytes(b"already there")

    calls: list[tuple[Path, Path]] = []
    real_inspect = inspection_module.inspect_destination

    def _spy(sandbox_root_arg, source_path, destination_path):  # type: ignore[no-untyped-def]
        calls.append((source_path, destination_path))
        return real_inspect(sandbox_root_arg, source_path, destination_path)

    # Both application.planner and transaction_engine.preconditions did
    # `from file_agent.destination import inspect_destination`, each
    # creating its own local binding -- both must be patched to observe
    # both call sites through the same spy.
    with (
        patch("file_agent.application.planner.inspect_destination", side_effect=_spy),
        patch(
            "file_agent.transaction_engine.preconditions.inspect_destination",
            side_effect=_spy,
        ),
    ):
        plan = service.create_organization_plan([item.policy_decision_id])
        apply_result = service.apply_item(item.policy_decision_id)

    assert plan.items[0].status.value == "conflict"
    assert plan.items[0].reason_code.value == "destination_occupied"
    assert apply_result.status.value == "rejected"
    assert apply_result.reason_code == "destination_already_exists"

    # Both call sites reached inspect_destination for the identical
    # (source_path, destination_path) pair.
    assert len(calls) == 2
    assert calls[0] == calls[1]
