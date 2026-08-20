"""FA-017.3: PlanItemView.needs_review_action is a pure function of status
-- True only for REVIEW_REQUIRED -- computed server-side so React never
needs to compare the raw status string to decide whether to offer
Aprobar/Omitir."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from file_agent.application.organization_plan import (
    OrganizationPlanItem,
    PlanReasonCode,
    PlanStatus,
)
from file_agent.desktop_api import views as v
from file_agent.domain import FileCategory, PolicyOutcome


def _plan_item(
    *, status: PlanStatus, reason_code: PlanReasonCode | None
) -> OrganizationPlanItem:
    return OrganizationPlanItem(
        file_id=uuid4(),
        proposal_id=uuid4(),
        policy_decision_id=uuid4(),
        source_path=Path("C:/sandbox/report.pdf"),
        filename="report.pdf",
        category=FileCategory.DOCUMENT,
        destination_category=None,
        destination_path=None,
        policy_outcome=PolicyOutcome.AUTO,
        human_review_outcome=None,
        status=status,
        reason_code=reason_code,
        reason="irrelevant prose, never rendered directly",
    )


def test_review_required_item_needs_review_action() -> None:
    view = v.plan_item_view(
        _plan_item(
            status=PlanStatus.REVIEW_REQUIRED,
            reason_code=PlanReasonCode.REVIEW_REQUIRED,
        )
    )
    assert view.needs_review_action is True


def test_ready_item_does_not_need_review_action() -> None:
    view = v.plan_item_view(_plan_item(status=PlanStatus.READY, reason_code=None))
    assert view.needs_review_action is False


def test_every_non_review_required_status_does_not_need_review_action() -> None:
    for status in PlanStatus:
        if status is PlanStatus.REVIEW_REQUIRED:
            continue
        view = v.plan_item_view(_plan_item(status=status, reason_code=None))
        assert view.needs_review_action is False, status
