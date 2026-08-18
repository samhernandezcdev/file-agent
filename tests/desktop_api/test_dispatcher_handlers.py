"""Exercises all 14 handlers through dispatcher.dispatch() against a real
FileAgentApplicationService (no subprocess -- fast, in-process). Proves
each command reaches a normal `ok: true` result carrying a View DTO
(camelCase, no forbidden internal object), and that unknown commands and
invalid params are rejected without ever touching the service."""

from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from file_agent.application import FileAgentApplicationService
from file_agent.desktop_api.dispatcher import dispatch
from file_agent.desktop_api.errors import UnknownCommandError
from file_agent.scanner import SandboxRoot


def test_unknown_command_raises_before_touching_service(
    service: FileAgentApplicationService,
) -> None:
    with pytest.raises(UnknownCommandError):
        dispatch("file_agent.run_arbitrary_code", {}, service)


def test_invalid_params_returns_terminal_rejection_not_an_exception(
    service: FileAgentApplicationService,
) -> None:
    outcome = dispatch("managed_roots.remove", {"managedRootId": "not-a-uuid"}, service)
    assert outcome.ok is False
    assert outcome.error_kind == "invalid_params"


def test_managed_roots_add_list_remove_round_trip(
    service: FileAgentApplicationService, sandbox_root: SandboxRoot
) -> None:
    add_outcome = dispatch(
        "managed_roots.add", {"path": str(sandbox_root.path)}, service
    )
    assert add_outcome.ok is True
    assert add_outcome.result is not None
    assert add_outcome.result["status"] == "available"
    managed_root_id = add_outcome.result["id"]

    list_outcome = dispatch("managed_roots.list", {}, service)
    assert list_outcome.ok is True
    assert list_outcome.result is not None
    assert any(r["id"] == managed_root_id for r in list_outcome.result["roots"])

    remove_outcome = dispatch(
        "managed_roots.remove", {"managedRootId": managed_root_id}, service
    )
    assert remove_outcome.ok is True
    assert remove_outcome.result is not None
    assert remove_outcome.result["status"] == "succeeded"


def test_managed_roots_add_registration_rejection_is_product_rejection(
    service: FileAgentApplicationService, tmp_path: Path
) -> None:
    """A drive root (or any ManagedRootRegistrationError) must render as a
    normal product_rejection frame -- never an uncaught exception."""
    outcome = dispatch(
        "managed_roots.add", {"path": str(Path(tmp_path.anchor))}, service
    )
    assert outcome.ok is False
    assert outcome.error_kind == "product_rejection"


def test_full_analyze_plan_review_apply_flow(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("invoice.pdf", content=b"pdf content")

    analysis = dispatch(
        "analysis.run", {"managedRootId": str(managed_root_id)}, service
    )
    assert analysis.ok is True
    assert analysis.result is not None
    assert analysis.result["outcome"] == "ok"
    items = analysis.result["items"]
    assert len(items) == 1
    action_id = items[0]["policyDecisionId"]

    reanalyze = dispatch(
        "analysis.reanalyze_file", {"fileId": items[0]["fileId"]}, service
    )
    assert reanalyze.ok is True

    plan = dispatch("plan.create", {"policyDecisionIds": [action_id]}, service)
    assert plan.ok is True
    assert plan.result is not None
    assert plan.result["outcome"] == "ok"
    plan_item = plan.result["items"][0]
    assert plan_item["actionId"] == action_id
    assert "status" in plan_item and "title" in plan_item and "detail" in plan_item

    apply_outcome = dispatch("apply.item", {"policyDecisionId": action_id}, service)
    assert apply_outcome.ok is True
    assert apply_outcome.result is not None
    assert apply_outcome.result["status"] == "succeeded"
    transaction_id = apply_outcome.result["transactionId"]
    assert transaction_id is not None

    undo_outcome = dispatch(
        "recovery.undo_transaction", {"transactionId": transaction_id}, service
    )
    assert undo_outcome.ok is True
    assert undo_outcome.result is not None
    assert undo_outcome.result["status"] == "succeeded"


def test_apply_items_batch_and_history(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("a.pdf", content=b"a")
    make_source_file("b.pdf", content=b"b")
    analysis = dispatch(
        "analysis.run", {"managedRootId": str(managed_root_id)}, service
    )
    assert analysis.result is not None
    action_ids = [item["policyDecisionId"] for item in analysis.result["items"]]

    batch = dispatch("apply.items", {"policyDecisionIds": action_ids}, service)
    assert batch.ok is True
    assert batch.result is not None
    assert batch.result["outcome"] == "ok"
    batch_id = batch.result["batchId"]

    detail = dispatch("history.get_batch", {"batchId": batch_id}, service)
    assert detail.ok is True
    assert detail.result is not None
    assert detail.result["outcome"] == "found"

    recent = dispatch("history.list_recent", {}, service)
    assert recent.ok is True
    assert recent.result is not None
    assert any(row["batchId"] == batch_id for row in recent.result["rows"])


def test_review_approve_and_skip(
    service: FileAgentApplicationService,
) -> None:
    """A nonexistent policy_decision_id is a normal, well-formed rejection
    -- never an uncaught exception -- for both approve and skip."""
    fake_id = str(uuid4())
    approve = dispatch("review.approve", {"policyDecisionId": fake_id}, service)
    assert approve.ok is True
    assert approve.result is not None
    assert approve.result["status"] == "rejected"

    skip = dispatch("review.skip", {"policyDecisionId": fake_id}, service)
    assert skip.ok is True
    assert skip.result is not None
    assert skip.result["status"] == "rejected"


def test_apply_items_empty_selection_is_product_rejection(
    service: FileAgentApplicationService,
) -> None:
    outcome = dispatch("apply.items", {"policyDecisionIds": []}, service)
    assert outcome.ok is False
    assert outcome.error_kind == "product_rejection"


def test_restore_capture_unknown_id_is_normal_rejection(
    service: FileAgentApplicationService,
) -> None:
    outcome = dispatch("recovery.restore_capture", {"captureId": str(uuid4())}, service)
    assert outcome.ok is True
    assert outcome.result is not None
    assert outcome.result["status"] == "rejected"


def test_analysis_run_unavailable_managed_root(
    service: FileAgentApplicationService,
) -> None:
    outcome = dispatch("analysis.run", {"managedRootId": str(uuid4())}, service)
    assert outcome.ok is True
    assert outcome.result is not None
    assert outcome.result["outcome"] == "managed_root_unavailable"
