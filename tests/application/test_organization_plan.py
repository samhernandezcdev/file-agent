"""OrganizationPlan / preview (FA-013): basic plan construction, policy vs
review vs readiness semantics, destination preview, summary invariants, and
failure semantics."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from file_agent.application import (
    FileAgentApplicationService,
    PlanReasonCode,
    PlanStatus,
)
from file_agent.destination import resolve_destination
from file_agent.domain import (
    DestinationCategory,
    DomainEvent,
    EntityType,
    EventType,
    HumanReviewOutcome,
    PolicyDecision,
    PolicyOutcome,
    ReviewSource,
)
from file_agent.persistence import FileAgentStore
from file_agent.policy_engine import policy_decision_event
from file_agent.scanner import SandboxRoot


def test_multiple_files_produce_one_plan_with_all_items(
    service: FileAgentApplicationService,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("invoice.pdf", content=b"pdf")
    make_source_file("app.exe", content=b"exe")
    make_source_file("mystery.xyz123", content=b"???")
    analysis = service.analyze_scan()

    plan = service.create_organization_plan(
        [item.policy_decision_id for item in analysis.items]
    )

    assert len(plan.items) == 3
    assert plan.issues == ()
    statuses = {item.status for item in plan.items}
    assert PlanStatus.READY in statuses
    assert PlanStatus.REVIEW_REQUIRED in statuses
    assert PlanStatus.NO_ACTION in statuses


def test_auto_item_is_ready(
    service: FileAgentApplicationService,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("invoice.pdf", content=b"pdf")
    item = service.analyze_scan().items[0]
    assert item.policy_outcome is PolicyOutcome.AUTO

    plan = service.create_organization_plan([item.policy_decision_id])

    plan_item = plan.items[0]
    assert plan_item.status is PlanStatus.READY
    assert plan_item.reason_code is None
    assert plan_item.policy_outcome is PolicyOutcome.AUTO
    assert plan_item.destination_path == sandbox_root.path / "Documents" / "invoice.pdf"


def test_review_without_decision_is_review_required(
    service: FileAgentApplicationService,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("app.exe", content=b"exe")
    item = service.analyze_scan().items[0]
    assert item.policy_outcome is PolicyOutcome.REVIEW

    plan = service.create_organization_plan([item.policy_decision_id])

    plan_item = plan.items[0]
    assert plan_item.status is PlanStatus.REVIEW_REQUIRED
    assert plan_item.reason_code is PlanReasonCode.REVIEW_REQUIRED
    assert plan_item.human_review_outcome is None
    # destination is still shown even though not yet authorized
    assert plan_item.destination_path == sandbox_root.path / "Executables" / "app.exe"


def test_block_item_is_blocked(
    service: FileAgentApplicationService,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("report.pdf", content=b"pdf")
    item = service.analyze_scan().items[0]
    blocked = PolicyDecision(
        proposal_id=item.proposal_id,
        file_id=item.file_id,
        decision=PolicyOutcome.BLOCK,
        reasons=("blocked for test",),
        evaluated_at=datetime.now(UTC),
        policy_engine_id="policy-v1",
        source_category=item.category,
        destination_category=item.proposed_destination_category,
        proposal_confidence=item.confidence,
        proposal_engine_id="rules-v1",
    )
    store.record_event(policy_decision_event(blocked))

    plan = service.create_organization_plan([blocked.id])

    plan_item = plan.items[0]
    assert plan_item.status is PlanStatus.BLOCKED
    assert plan_item.reason_code is PlanReasonCode.POLICY_BLOCK
    assert plan_item.policy_outcome is PolicyOutcome.BLOCK


def test_unknown_extension_is_no_action(
    service: FileAgentApplicationService,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("mystery.xyz123", content=b"???")
    item = service.analyze_scan().items[0]
    assert item.proposed_destination_category is None

    plan = service.create_organization_plan([item.policy_decision_id])

    plan_item = plan.items[0]
    assert plan_item.status is PlanStatus.NO_ACTION
    assert plan_item.reason_code is PlanReasonCode.NO_DESTINATION_PROPOSED
    assert plan_item.destination_path is None


def test_review_with_genuine_approve_is_ready_and_preserves_review_policy_outcome(
    service: FileAgentApplicationService,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("app.exe", content=b"exe")
    item = service.analyze_scan().items[0]
    review = service.approve_review(item.policy_decision_id)
    assert review.status.value == "succeeded"

    plan = service.create_organization_plan([item.policy_decision_id])

    plan_item = plan.items[0]
    assert plan_item.status is PlanStatus.READY
    # the critical invariant: policy_outcome stays REVIEW, never rewritten to AUTO
    assert plan_item.policy_outcome is PolicyOutcome.REVIEW
    assert plan_item.human_review_outcome is HumanReviewOutcome.APPROVE
    assert plan_item.destination_path == sandbox_root.path / "Executables" / "app.exe"


def test_review_with_skip_is_skipped(
    service: FileAgentApplicationService,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("app.exe", content=b"exe")
    item = service.analyze_scan().items[0]
    service.skip_review(item.policy_decision_id)

    plan = service.create_organization_plan([item.policy_decision_id])

    plan_item = plan.items[0]
    assert plan_item.status is PlanStatus.SKIPPED
    assert plan_item.reason_code is PlanReasonCode.HUMAN_SKIPPED
    assert plan_item.policy_outcome is PolicyOutcome.REVIEW


def test_ambiguous_review_history_is_invalid_not_conflict(
    service: FileAgentApplicationService,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    """Round-2 correction 1: persisted-history ambiguity is INVALID, never
    CONFLICT -- CONFLICT is reserved for filesystem/destination readiness
    problems only."""
    make_source_file("app.exe", content=b"exe")
    item = service.analyze_scan().items[0]

    # Two genuine, conflicting HUMAN_REVIEW_RECORDED events for the same
    # policy_decision_id -- simulates corrupted/duplicated history.
    for outcome in (HumanReviewOutcome.APPROVE, HumanReviewOutcome.SKIP):
        event = DomainEvent(
            event_type=EventType.HUMAN_REVIEW_RECORDED,
            entity_type=EntityType.HUMAN_REVIEW,
            entity_id=uuid4(),
            timestamp=datetime.now(UTC),
            payload={
                "review_id": str(uuid4()),
                "policy_decision_id": str(item.policy_decision_id),
                "proposal_id": str(item.proposal_id),
                "file_id": str(item.file_id),
                "outcome": outcome.value,
                "destination_category": item.proposed_destination_category.value
                if item.proposed_destination_category
                else None,
                "review_source": ReviewSource.USER.value,
                "note": None,
                "policy_engine_id": "policy-v1",
                "proposal_engine_id": "rules-v1",
                "human_review_engine_id": "rules-v1",
            },
        )
        store.record_event(event)

    plan = service.create_organization_plan([item.policy_decision_id])

    plan_item = plan.items[0]
    assert plan_item.status is PlanStatus.INVALID
    assert plan_item.reason_code is PlanReasonCode.AMBIGUOUS_REVIEW_HISTORY


def test_destination_path_matches_what_apply_item_would_use(
    service: FileAgentApplicationService,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("invoice.pdf", content=b"pdf")
    item = service.analyze_scan().items[0]

    plan = service.create_organization_plan([item.policy_decision_id])

    expected = resolve_destination(
        sandbox_root, DestinationCategory.DOCUMENTS, "invoice.pdf"
    )
    assert plan.items[0].destination_path == expected


def test_destination_occupied_is_conflict(
    service: FileAgentApplicationService,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("invoice.pdf", content=b"pdf")
    item = service.analyze_scan().items[0]
    (sandbox_root.path / "Documents" / "invoice.pdf").write_bytes(b"already there")

    plan = service.create_organization_plan([item.policy_decision_id])

    plan_item = plan.items[0]
    assert plan_item.status is PlanStatus.CONFLICT
    assert plan_item.reason_code is PlanReasonCode.DESTINATION_OCCUPIED


def test_destination_parent_missing_is_conflict(
    service: FileAgentApplicationService,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("invoice.pdf", content=b"pdf")
    item = service.analyze_scan().items[0]
    (sandbox_root.path / "Documents").rmdir()

    plan = service.create_organization_plan([item.policy_decision_id])

    plan_item = plan.items[0]
    assert plan_item.status is PlanStatus.CONFLICT
    assert plan_item.reason_code is PlanReasonCode.DESTINATION_PARENT_MISSING


def test_source_already_at_destination_is_no_action(
    service: FileAgentApplicationService,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    already_placed = sandbox_root.path / "Documents" / "invoice.pdf"
    already_placed.write_bytes(b"pdf")
    item_id = service.analyze_scan().items[0].policy_decision_id

    plan = service.create_organization_plan([item_id])

    plan_item = plan.items[0]
    assert plan_item.status is PlanStatus.NO_ACTION
    assert plan_item.reason_code is PlanReasonCode.SOURCE_ALREADY_AT_DESTINATION


def test_zero_filesystem_mutation_from_preview(
    service: FileAgentApplicationService,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    source = make_source_file("invoice.pdf", content=b"pdf")
    item = service.analyze_scan().items[0]

    service.create_organization_plan([item.policy_decision_id])

    assert source.exists()
    assert source.read_bytes() == b"pdf"
    assert not (sandbox_root.path / "Documents" / "invoice.pdf").exists()


def test_not_found_policy_decision_id_becomes_plan_issue(
    service: FileAgentApplicationService,
) -> None:
    unknown_id = uuid4()

    plan = service.create_organization_plan([unknown_id])

    assert plan.items == ()
    assert len(plan.issues) == 1
    assert plan.issues[0].policy_decision_id == unknown_id
    assert plan.issues[0].reason_code == "policy_decision_not_found"


def test_summary_counts_match_items_and_issues(
    service: FileAgentApplicationService,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("invoice.pdf", content=b"pdf")
    make_source_file("app.exe", content=b"exe")
    make_source_file("mystery.xyz123", content=b"???")
    analysis = service.analyze_scan()
    ids = [item.policy_decision_id for item in analysis.items]
    ids.append(uuid4())  # one NOT_FOUND -> issue

    plan = service.create_organization_plan(ids)

    summary = plan.summary
    assert summary.files_total == len(plan.items)
    assert (
        summary.ready
        + summary.review_required
        + summary.conflicts
        + summary.invalid
        + summary.blocked
        + summary.skipped
        + summary.no_action
        == summary.files_total
    )
    assert summary.issues == len(plan.issues) == 1
