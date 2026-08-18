"""FA-016 Spanish presentation: content-level assertions for the new
protected-tree/structural-protection messages -- totality (None for the
"nothing to report" case, never an empty/misleading message) and that
PROTECTED renders distinct copy from BLOCKED (policy-level refusal)."""

from pathlib import Path

from file_agent.application.organization_plan import PlanStatus
from file_agent.presentation import es
from file_agent.structural_safety import (
    ProjectMarkerType,
    StructuralProtection,
    StructuralProtectionKind,
)


def test_protected_trees_summary_message_none_when_nothing_found() -> None:
    assert es.protected_trees_summary_message([]) is None


def test_protected_trees_summary_message_present_when_found() -> None:
    membership = StructuralProtection(
        kind=StructuralProtectionKind.PROTECTED_TREE,
        root_path=Path("C:/Downloads/project").resolve(),
        marker=ProjectMarkerType.PYPROJECT_TOML,
        marker_path=Path("C:/Downloads/project/pyproject.toml").resolve(),
        excluded_name=None,
    )
    message = es.protected_trees_summary_message([membership])
    assert message is not None
    assert message.title
    assert message.detail
    assert "proyecto" in message.detail.lower()


def test_structural_protection_note_none_when_zero() -> None:
    assert es.structural_protection_note(0) is None


def test_structural_protection_note_present_when_positive() -> None:
    note = es.structural_protection_note(2)
    assert note is not None
    assert "proyecto" in note.lower()


def test_protected_status_renders_distinct_copy_from_blocked() -> None:
    protected_label = es.plan_status_label(PlanStatus.PROTECTED)
    blocked_label = es.plan_status_label(PlanStatus.BLOCKED)
    assert protected_label != blocked_label


def test_structurally_protected_reason_detail() -> None:
    detail = es.rejection_reason_detail("structurally_protected")
    assert detail == "Esta carpeta está protegida y no se organizará."
