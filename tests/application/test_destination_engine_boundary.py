"""Guardrail (FA-017.2 Round-2 remediation, Major 2): proves the COMPLETE
production call chain for directory creation is exactly the one approved
path, end to end --

    prepare_destinations               [live ManagedRoot + fresh
      |                                 current-need authorization]
      v
    _prepare_one_destination           [structural safety + leaf
      |                                 validation]
      v
    destination_engine.prepare_destination_directory
      |
      v
    managed_fs.create_directory_no_replace

Round 1 of this remediation already proved the bottom two links (the
mkdir-boundary AST guardrail in
tests/managed_fs/test_mutation_boundary_within_package.py, and
destination_engine's own import/call-site restriction below). What was
still missing: nothing stopped some OTHER method on
FileAgentApplicationService from calling _prepare_one_destination directly,
skipping prepare_destinations' live ManagedRoot resolution and fresh
current-need reconstruction entirely -- i.e. `_prepare_one_destination`
looked private by convention (leading underscore) but was not mechanically
proven reachable from only one caller. This file closes that: every link
in the chain above is proven to have exactly one production caller, so
directory creation is reachable in production from exactly one entry
point: `FileAgentApplicationService.prepare_destinations`."""

import ast
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src" / "file_agent"
SERVICE_FILE = SRC_DIR / "application" / "service.py"
ENGINE_FILE = SRC_DIR / "destination_engine.py"

ENGINE_FUNCTION_NAME = "prepare_destination_directory"
APPROVED_ENGINE_CALLER = "_prepare_one_destination"
APPROVED_PREPARE_ONE_CALLER = "prepare_destinations"


def _imports_destination_engine(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                alias.name == "file_agent.destination_engine"
                or alias.name.startswith("file_agent.destination_engine.")
                for alias in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom) and (
            node.module == "file_agent.destination_engine"
            or (
                node.module is not None
                and node.module.startswith("file_agent.destination_engine.")
            )
        ):
            return True
    return False


def test_destination_engine_is_imported_only_by_application_service() -> None:
    offenders: list[str] = []
    for path in sorted(SRC_DIR.rglob("*.py")):
        if path == ENGINE_FILE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if _imports_destination_engine(tree):
            offenders.append(str(path.relative_to(SRC_DIR)))

    assert offenders == [str(SERVICE_FILE.relative_to(SRC_DIR))], (
        "file_agent.destination_engine must be imported by exactly "
        f"application/service.py and nowhere else in src/file_agent; "
        f"found importers: {offenders or '(none -- has the approved call site moved?)'}"
    )


class _EnclosingCallerVisitor(ast.NodeVisitor):
    """For a target callable -- either a bare module-level function name
    (`prepare_destination_directory(...)`) or a `self.<method>(...)` call
    -- records the name of every function/method that contains a call to
    it. Used to prove each link in the chain has exactly one production
    caller, not just that the target exists somewhere in the file."""

    def __init__(
        self, *, bare_name: str | None = None, self_method_name: str | None = None
    ) -> None:
        self._bare_name = bare_name
        self._self_method_name = self_method_name
        self._stack: list[str] = []
        self.calls_by_function: list[str | None] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        matched = False
        if self._bare_name is not None and isinstance(func, ast.Name):
            matched = func.id == self._bare_name
        elif (
            self._self_method_name is not None
            and isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "self"
        ):
            matched = func.attr == self._self_method_name
        if matched:
            self.calls_by_function.append(self._stack[-1] if self._stack else None)
        self.generic_visit(node)


def _service_tree() -> ast.Module:
    return ast.parse(
        SERVICE_FILE.read_text(encoding="utf-8"), filename=str(SERVICE_FILE)
    )


def test_prepare_destination_directory_is_called_only_from_prepare_one_destination() -> (
    None
):
    visitor = _EnclosingCallerVisitor(bare_name=ENGINE_FUNCTION_NAME)
    visitor.visit(_service_tree())

    assert visitor.calls_by_function, (
        f"expected at least one call to {ENGINE_FUNCTION_NAME}(...) in "
        f"{SERVICE_FILE.name} -- none found; has the call site moved or "
        "been renamed? (this guardrail must be updated deliberately, not "
        "silently pass because the call disappeared)"
    )
    offenders = [c for c in visitor.calls_by_function if c != APPROVED_ENGINE_CALLER]
    assert not offenders, (
        f"{ENGINE_FUNCTION_NAME}(...) must be called only from "
        f"{APPROVED_ENGINE_CALLER} -- also called from: {offenders}"
    )


def test_prepare_one_destination_is_called_only_from_prepare_destinations() -> None:
    """Closes the gap the previous round of this guardrail left open:
    _prepare_one_destination performs structural-safety/leaf validation
    but NOT live ManagedRoot resolution or current-need authorization --
    those live only in prepare_destinations, immediately before it calls
    _prepare_one_destination in a loop over the already-authorized
    category set. If any other method could call _prepare_one_destination
    directly, it would reach real mkdir capability while skipping both of
    those checks entirely."""
    visitor = _EnclosingCallerVisitor(self_method_name=APPROVED_ENGINE_CALLER)
    visitor.visit(_service_tree())

    assert visitor.calls_by_function, (
        f"expected at least one call to self.{APPROVED_ENGINE_CALLER}(...) in "
        f"{SERVICE_FILE.name} -- none found; has the call site moved or been "
        "renamed? (this guardrail must be updated deliberately, not "
        "silently pass because the call disappeared)"
    )
    offenders = [
        c for c in visitor.calls_by_function if c != APPROVED_PREPARE_ONE_CALLER
    ]
    assert not offenders, (
        f"self.{APPROVED_ENGINE_CALLER}(...) must be called only from "
        f"{APPROVED_PREPARE_ONE_CALLER} -- also called from: {offenders}"
    )
