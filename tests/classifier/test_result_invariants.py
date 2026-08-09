"""Tests for ClassificationResult's construction-time invariants."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import pytest

from file_agent.classifier import ClassificationResult, FileClassifier, classify_file
from file_agent.classifier.rules import CLASSIFIER_ID
from file_agent.domain import DiscoveredFile, FileCategory


def _valid_kwargs(discovered: DiscoveredFile) -> dict[str, object]:
    return {
        "discovered_file": discovered,
        "category": FileCategory.DOCUMENT,
        "confidence": 1.0,
        "reasons": ("a reason",),
        "classified_at": datetime.now(UTC),
        "classifier_id": "rules-v1",
    }


def test_confidence_below_zero_rejected(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    kwargs = _valid_kwargs(make_discovered_file("C:/sandbox/a.txt"))
    kwargs["confidence"] = -0.01
    with pytest.raises(ValueError, match="confidence"):
        ClassificationResult(**kwargs)  # type: ignore[arg-type]


def test_confidence_above_one_rejected(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    kwargs = _valid_kwargs(make_discovered_file("C:/sandbox/a.txt"))
    kwargs["confidence"] = 1.01
    with pytest.raises(ValueError, match="confidence"):
        ClassificationResult(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("boundary", [0.0, 1.0])
def test_confidence_boundary_accepted(
    make_discovered_file: Callable[..., DiscoveredFile], boundary: float
) -> None:
    kwargs = _valid_kwargs(make_discovered_file("C:/sandbox/a.txt"))
    kwargs["confidence"] = boundary
    assert ClassificationResult(**kwargs).confidence == boundary  # type: ignore[arg-type]


def test_empty_reasons_rejected(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    kwargs = _valid_kwargs(make_discovered_file("C:/sandbox/a.txt"))
    kwargs["reasons"] = ()
    with pytest.raises(ValueError, match="reasons"):
        ClassificationResult(**kwargs)  # type: ignore[arg-type]


def test_empty_classifier_id_rejected(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    kwargs = _valid_kwargs(make_discovered_file("C:/sandbox/a.txt"))
    kwargs["classifier_id"] = ""
    with pytest.raises(ValueError, match="classifier_id"):
        ClassificationResult(**kwargs)  # type: ignore[arg-type]


def test_naive_classified_at_rejected(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    kwargs = _valid_kwargs(make_discovered_file("C:/sandbox/a.txt"))
    kwargs["classified_at"] = datetime(2026, 1, 1)  # noqa: DTZ001 -- intentionally naive
    with pytest.raises(ValueError, match="timezone-aware"):
        ClassificationResult(**kwargs)  # type: ignore[arg-type]


def test_aware_non_utc_classified_at_normalized_to_utc(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    kwargs = _valid_kwargs(make_discovered_file("C:/sandbox/a.txt"))
    plus_two = timezone(timedelta(hours=2))
    local = datetime(2026, 1, 1, 12, 0, 0, tzinfo=plus_two)
    kwargs["classified_at"] = local
    result = ClassificationResult(**kwargs)  # type: ignore[arg-type]
    assert result.classified_at.tzinfo == UTC
    assert result.classified_at.hour == 10


def test_file_classifier_always_sets_classifier_id(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    result = FileClassifier().classify(make_discovered_file("C:/sandbox/a.txt"))
    assert result.classifier_id == CLASSIFIER_ID


def test_classify_file_convenience_also_sets_classifier_id(
    make_discovered_file: Callable[..., DiscoveredFile],
) -> None:
    result = classify_file(make_discovered_file("C:/sandbox/a.unknownext"))
    assert result.classifier_id == CLASSIFIER_ID
