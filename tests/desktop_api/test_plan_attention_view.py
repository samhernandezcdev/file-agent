"""FA-017.1 §18: PlanAttentionView aggregation -- grouped by the item's
actual destination_path.parent (not merely by reason_code), Python-composed
copy only, and no leak of reason_code onto the wire."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from file_agent.application.organization_plan import (
    OrganizationPlan,
    OrganizationPlanItem,
    OrganizationPlanSummary,
    PlanReasonCode,
    PlanStatus,
)
from file_agent.desktop_api import views as v
from file_agent.domain import DestinationCategory, FileCategory, PolicyOutcome


def _plan_item(
    *,
    filename: str,
    status: PlanStatus,
    reason_code: PlanReasonCode | None,
    destination_path: Path | None,
    category: FileCategory = FileCategory.DOCUMENT,
    destination_category: DestinationCategory | None = None,
) -> OrganizationPlanItem:
    return OrganizationPlanItem(
        file_id=uuid4(),
        proposal_id=uuid4(),
        policy_decision_id=uuid4(),
        source_path=Path(f"C:/sandbox/{filename}"),
        filename=filename,
        category=category,
        destination_category=destination_category,
        destination_path=destination_path,
        policy_outcome=PolicyOutcome.AUTO,
        human_review_outcome=None,
        status=status,
        reason_code=reason_code,
        reason="irrelevant prose, never rendered directly",
    )


def _plan(items: tuple[OrganizationPlanItem, ...]) -> OrganizationPlan:
    summary = OrganizationPlanSummary(
        files_total=len(items),
        ready=sum(1 for i in items if i.status is PlanStatus.READY),
        review_required=sum(1 for i in items if i.status is PlanStatus.REVIEW_REQUIRED),
        conflicts=sum(1 for i in items if i.status is PlanStatus.CONFLICT),
        invalid=0,
        blocked=0,
        skipped=0,
        no_action=0,
        protected=0,
        issues=0,
    )
    return OrganizationPlan(
        id=uuid4(),
        created_at=datetime.now(UTC),
        root_path=Path("C:/sandbox"),
        managed_root_id=uuid4(),
        source_policy_decision_ids=tuple(i.policy_decision_id for i in items),
        items=items,
        issues=(),
        summary=summary,
    )


def test_two_distinct_missing_parents_produce_two_attention_entries() -> None:
    items = (
        _plan_item(
            filename="a.pdf",
            status=PlanStatus.CONFLICT,
            reason_code=PlanReasonCode.DESTINATION_PARENT_MISSING,
            destination_path=Path("C:/sandbox/Documents/a.pdf"),
        ),
        _plan_item(
            filename="b.pdf",
            status=PlanStatus.CONFLICT,
            reason_code=PlanReasonCode.DESTINATION_PARENT_MISSING,
            destination_path=Path("C:/sandbox/Documents/b.pdf"),
        ),
        _plan_item(
            filename="c.jpg",
            status=PlanStatus.CONFLICT,
            reason_code=PlanReasonCode.DESTINATION_PARENT_MISSING,
            destination_path=Path("C:/sandbox/Images/c.jpg"),
            category=FileCategory.IMAGE,
        ),
    )
    attentions = v._missing_destination_folder_attentions(items)

    assert len(attentions) == 2
    by_label = {a.destination_label: a for a in attentions}
    assert set(by_label) == {"Documents", "Images"}
    assert by_label["Documents"].affected_filenames == ("a.pdf", "b.pdf")
    assert by_label["Images"].affected_filenames == ("c.jpg",)
    for attention in attentions:
        assert attention.variant == "missing_destination_folder"


def test_non_conflict_and_other_reason_codes_are_excluded() -> None:
    items = (
        _plan_item(
            filename="ready.pdf",
            status=PlanStatus.READY,
            reason_code=None,
            destination_path=None,
        ),
        _plan_item(
            filename="review.pdf",
            status=PlanStatus.REVIEW_REQUIRED,
            reason_code=PlanReasonCode.REVIEW_REQUIRED,
            destination_path=None,
        ),
        _plan_item(
            filename="occupied.pdf",
            status=PlanStatus.CONFLICT,
            reason_code=PlanReasonCode.DESTINATION_OCCUPIED,
            destination_path=Path("C:/sandbox/Documents/occupied.pdf"),
        ),
    )
    assert v._missing_destination_folder_attentions(items) == ()


def test_attention_message_never_leaks_reason_code_and_uses_composed_copy() -> None:
    items = (
        _plan_item(
            filename="invoice.pdf",
            status=PlanStatus.CONFLICT,
            reason_code=PlanReasonCode.DESTINATION_PARENT_MISSING,
            destination_path=Path("C:/sandbox/Documents/invoice.pdf"),
        ),
    )
    (attention,) = v._missing_destination_folder_attentions(items)
    dumped = attention.model_dump_json(by_alias=True)
    assert "destination_parent_missing" not in dumped
    assert "reason_code" not in dumped
    assert attention.category_label == "Documento"
    assert attention.message.title == "Falta preparar esta carpeta"
    assert "Documents" in attention.message.detail
    assert attention.message.suggested_action == "reanalyze"


def test_plan_view_computes_attentions_field() -> None:
    items = (
        _plan_item(
            filename="invoice.pdf",
            status=PlanStatus.CONFLICT,
            reason_code=PlanReasonCode.DESTINATION_PARENT_MISSING,
            destination_path=Path("C:/sandbox/Documents/invoice.pdf"),
        ),
    )
    plan = _plan(items)
    view = v.plan_view(plan)
    assert len(view.attentions) == 1
    assert view.attentions[0].variant == "missing_destination_folder"
    # Additive-only: existing per-item fields are untouched by this change.
    assert view.items[0].status == "conflict"
    assert view.items[0].selectable is False
