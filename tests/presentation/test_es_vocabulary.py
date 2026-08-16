"""Spanish vocabulary coverage (FA-014 §22): every PlanStatus/
BatchApplyItemStatus has a label; rejection_reason_detail is total (never
raises, never falls through to an empty/English string) for every code this
codebase's rejection vocabularies define, plus for genuinely unknown/future
codes; no raw enum name or forbidden jargon term ever appears in rendered
copy."""

from file_agent.application.dto import ApplicationRejectionReason, BatchApplyItemStatus
from file_agent.application.organization_plan import PlanReasonCode, PlanStatus
from file_agent.domain import RejectionCode
from file_agent.presentation import es

FORBIDDEN_JARGON = (
    "policy_decision",
    "ExecutionAuthorization",
    "hash mismatch",
    "reparse point",
    "event payload",
)


def _all_rendered_strings() -> list[str]:
    strings: list[str] = []
    for status in PlanStatus:
        strings.append(es.plan_status_label(status))
    for status in BatchApplyItemStatus:
        strings.append(es.batch_item_status_label(status))
    for enum_cls in (ApplicationRejectionReason, PlanReasonCode, RejectionCode):
        for member in enum_cls:
            strings.append(es.rejection_reason_detail(member.value))
    strings.append(es.rejection_reason_detail(None))
    strings.append(es.rejection_reason_detail("some_future_unmapped_code"))
    return strings


def test_every_plan_status_has_a_spanish_label() -> None:
    for status in PlanStatus:
        label = es.plan_status_label(status)
        assert label
        assert label.strip() == label


def test_every_batch_item_status_has_a_spanish_label() -> None:
    for status in BatchApplyItemStatus:
        label = es.batch_item_status_label(status)
        assert label
        assert label.strip() == label


def test_rejection_reason_detail_is_total_never_raises_never_empty() -> None:
    for enum_cls in (ApplicationRejectionReason, PlanReasonCode, RejectionCode):
        for member in enum_cls:
            detail = es.rejection_reason_detail(member.value)
            assert detail

    assert es.rejection_reason_detail(None)
    assert es.rejection_reason_detail("totally_unrecognized_future_code")


def test_unmapped_code_renders_the_safe_generic_fallback() -> None:
    fallback = es.rejection_reason_detail(None)
    assert fallback == es.rejection_reason_detail("brand_new_code_from_a_future_ticket")
    assert "no se realizó ningún cambio" in fallback.lower()


def test_no_forbidden_jargon_or_raw_enum_name_in_any_rendered_string() -> None:
    for text in _all_rendered_strings():
        for jargon in FORBIDDEN_JARGON:
            assert jargon not in text
        for status in PlanStatus:
            assert f"PlanStatus.{status.name}" not in text
        for status in BatchApplyItemStatus:
            assert f"BatchApplyItemStatus.{status.name}" not in text


def test_designated_product_contract_strings() -> None:
    """A small, explicitly-called-out set of exact-string checks -- not the
    entire vocabulary table, to avoid brittleness on ordinary copy edits."""
    assert es.plan_status_label(PlanStatus.READY) == "Listo para organizar"
    assert es.plan_status_label(PlanStatus.REVIEW_REQUIRED) == "Necesita tu aprobación"
    assert es.batch_item_status_label(BatchApplyItemStatus.APPLIED) == "Organizado"
    assert (
        es.rejection_reason_detail(None)
        == "No pudimos completar esta acción de forma segura. "
        "No se realizó ningún cambio en este archivo."
    )
