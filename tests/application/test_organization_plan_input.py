"""OrganizationPlan / preview (FA-013): input ordering and duplicate
semantics (round-3 correction 1). Sequence[UUID], never Iterable[UUID];
duplicates are invalid caller input, rejected before any persistence query
or filesystem observation; caller-supplied order is preserved exactly."""

from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest

from file_agent.application import FileAgentApplicationService
from file_agent.application.errors import DuplicatePolicyDecisionIdError
from file_agent.persistence import AppPaths, FileAgentStore
from file_agent.scanner import SandboxRoot


def test_preserves_caller_order(
    service: FileAgentApplicationService,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("a.pdf", content=b"a")
    make_source_file("b.pdf", content=b"b")
    make_source_file("c.pdf", content=b"c")
    items = service.analyze_scan().items
    by_name = {item.path.name: item.policy_decision_id for item in items}
    ordered_ids = [by_name["c.pdf"], by_name["a.pdf"], by_name["b.pdf"]]

    plan = service.create_organization_plan(ordered_ids)

    assert [item.policy_decision_id for item in plan.items] == ordered_ids
    assert plan.source_policy_decision_ids == tuple(ordered_ids)


def test_duplicate_ids_rejected_before_construction(
    service: FileAgentApplicationService,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("a.pdf", content=b"a")
    item_id = service.analyze_scan().items[0].policy_decision_id

    with pytest.raises(DuplicatePolicyDecisionIdError) as excinfo:
        service.create_organization_plan([item_id, uuid4(), item_id])

    assert excinfo.value.duplicate_ids == (item_id,)


def test_duplicate_validation_happens_before_any_store_interaction(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    """Validated strictly before any persistence query or filesystem
    observation: a store double that raises on ANY record_event/query call
    proves the duplicate check short-circuits before touching the store at
    all. Since build_organization_plan only ever reads (never calls
    record_event), we instead prove zero interaction by wrapping every
    read the planner could call."""
    plain_service = FileAgentApplicationService(sandbox_root, app_paths, store)
    make_source_file("a.pdf", content=b"a")
    item_id = plain_service.analyze_scan().items[0].policy_decision_id

    class ExplodingStore:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(
                f"build_organization_plan touched the store (.{name}) before "
                "validating duplicates"
            )

    exploding_service = FileAgentApplicationService(
        sandbox_root,
        app_paths,
        ExplodingStore(),  # type: ignore[arg-type]
    )

    with pytest.raises(DuplicatePolicyDecisionIdError):
        exploding_service.create_organization_plan([item_id, item_id])


def test_one_id_never_produces_multiple_plan_entries(
    service: FileAgentApplicationService,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("a.pdf", content=b"a")
    make_source_file("app.exe", content=b"exe")
    make_source_file("mystery.xyz123", content=b"???")
    ids = [item.policy_decision_id for item in service.analyze_scan().items]

    plan = service.create_organization_plan(ids)

    seen_item_ids = [item.policy_decision_id for item in plan.items]
    seen_issue_ids = [issue.policy_decision_id for issue in plan.issues]
    all_seen = seen_item_ids + seen_issue_ids
    assert len(all_seen) == len(set(all_seen))


def test_mixed_valid_and_not_found_preserves_relative_order_per_collection(
    service: FileAgentApplicationService,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("a.pdf", content=b"a")
    make_source_file("app.exe", content=b"exe")
    d1, d3 = (item.policy_decision_id for item in service.analyze_scan().items)
    d2 = uuid4()  # NOT_FOUND -> issue

    plan = service.create_organization_plan([d1, d2, d3])

    assert [item.policy_decision_id for item in plan.items] == [d1, d3]
    assert [issue.policy_decision_id for issue in plan.issues] == [d2]
