"""View DTO serialization: camelCase wire format, and totality/no-leak
spot checks -- no raw internal object (PolicyDecision,
ExecutionAuthorization, SandboxRoot, StructuralProtection) or a bare
safe=true/ready=true/authorized=true flag ever appears in a serialized
View DTO."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from file_agent.application.managed_roots import ManagedRootStatus
from file_agent.application.managed_roots import ManagedRootView as _ManagedRootDTO
from file_agent.desktop_api import views as v

_FORBIDDEN_SUBSTRINGS = (
    "PolicyDecision",
    "ExecutionAuthorization",
    "SandboxRoot",
    "StructuralProtection",
    "TransactionRequest",
    '"safe":true',
    '"ready":true',
    '"authorized":true',
)


def test_managed_root_view_serializes_camel_case() -> None:
    dto = _ManagedRootDTO(
        uuid4(), Path("C:/Users/Ana/Descargas"), ManagedRootStatus.AVAILABLE
    )
    view = v.managed_root_view(dto)
    dumped = view.model_dump(mode="json", by_alias=True)
    assert set(dumped.keys()) == {"id", "displayPath", "status"}
    assert dumped["status"] == "available"


def test_user_message_view_never_leaks_forbidden_internals() -> None:
    view = v.UserMessageView(
        title="No se pudo agregar esta carpeta.",
        detail="Esta carpeta ya está agregada.",
        severity="error",
        suggested_action="none",
    )
    dumped_json = view.model_dump_json(by_alias=True)
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        assert forbidden not in dumped_json


def test_plan_item_view_field_names_match_product_contract() -> None:
    item = v.PlanItemView(
        action_id=uuid4(),
        filename="invoice.pdf",
        source_display_path="C:/Users/Ana/Descargas/invoice.pdf",
        destination_display_path=None,
        category_label="Documento",
        status="ready",
        title="Listo para organizar",
        detail="Este archivo está listo para organizarse.",
        severity="info",
        selectable=True,
        needs_review_action=False,
    )
    dumped = item.model_dump(mode="json", by_alias=True)
    for expected_key in (
        "actionId",
        "filename",
        "sourceDisplayPath",
        "destinationDisplayPath",
        "categoryLabel",
        "status",
        "title",
        "detail",
        "selectable",
        "needsReviewAction",
    ):
        assert expected_key in dumped
