"""Tests for FileProposal."""

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from file_agent.domain import FileCategory, FileProposal


def _make(tmp_path: Path, **overrides: object) -> FileProposal:
    defaults: dict[str, object] = {
        "file_id": uuid4(),
        "proposed_name": "invoice-2026-01.pdf",
        "proposed_destination": tmp_path / "invoices" / "invoice-2026-01.pdf",
        "category": FileCategory.DOCUMENT,
        "confidence": 0.75,
        "source_classification_confidence": 0.75,
        "source_classifier_id": "rules-v1",
        "reasons": ["filename matches invoice pattern"],
        "proposal_engine_id": "rules-v1",
    }
    defaults.update(overrides)
    return FileProposal(**defaults)


def test_valid_construction(tmp_path: Path) -> None:
    proposal = _make(tmp_path)
    assert proposal.category is FileCategory.DOCUMENT


def test_confidence_too_low_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make(tmp_path, confidence=-0.01)


def test_confidence_too_high_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make(tmp_path, confidence=1.01)


@pytest.mark.parametrize("boundary", [0.0, 1.0])
def test_confidence_boundary_accepted(tmp_path: Path, boundary: float) -> None:
    assert _make(tmp_path, confidence=boundary).confidence == boundary


def test_invalid_category_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make(tmp_path, category="not-a-real-category")


def test_empty_reasons_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make(tmp_path, reasons=[])


def test_non_absolute_destination_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make(tmp_path, proposed_destination=Path("relative/invoice.pdf"))


def test_frozen_mutation_raises(tmp_path: Path) -> None:
    proposal = _make(tmp_path)
    with pytest.raises(ValidationError):
        proposal.confidence = 0.9  # type: ignore[misc]


def test_unresolved_proposal_allows_missing_name_and_destination(
    tmp_path: Path,
) -> None:
    proposal = _make(
        tmp_path,
        proposed_name=None,
        proposed_destination=None,
        confidence=0.1,
        reasons=["low confidence, needs human review"],
    )
    assert proposal.proposed_name is None
    assert proposal.proposed_destination is None


def test_empty_string_name_still_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make(tmp_path, proposed_name="")


def test_unknown_field_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make(tmp_path, bogus_field="nope")


# --- M1: reasons is a tuple, not a mutable list --------------------------------


def test_reasons_stored_as_tuple(tmp_path: Path) -> None:
    proposal = _make(tmp_path, reasons=["a", "b"])
    assert proposal.reasons == ("a", "b")
    assert isinstance(proposal.reasons, tuple)


def test_reasons_append_impossible(tmp_path: Path) -> None:
    proposal = _make(tmp_path)
    with pytest.raises(AttributeError):
        proposal.reasons.append("mutated")  # type: ignore[attr-defined]


def test_reasons_item_assignment_impossible(tmp_path: Path) -> None:
    proposal = _make(tmp_path)
    with pytest.raises(TypeError):
        proposal.reasons[0] = "mutated"  # type: ignore[index]
