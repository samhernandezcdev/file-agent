"""ClassificationResult — the immutable, validated output of classifying one observation."""

from dataclasses import dataclass
from datetime import UTC, datetime

from file_agent.domain import DiscoveredFile, FileCategory


def _normalize_to_utc(value: datetime) -> datetime:
    """Reject naive datetimes; convert any timezone-aware datetime to UTC.

    Duplicated locally rather than importing file_agent.domain._validators'
    private helper — matching the precedent scanner/hasher already set for
    not reaching into another package's private internals.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"classified_at must be timezone-aware, got: {value!r}")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """The outcome of classifying one DiscoveredFile — always produced, never a failure.

    UNKNOWN (confidence 0.0) is a normal value of `category`, not a distinct
    error type — see classifier.py. Invariants are enforced at construction
    because this is the direct input to a durable, persisted FILE_CLASSIFIED
    event: a malformed ClassificationResult must be impossible to construct,
    not merely impossible to use correctly.
    """

    discovered_file: DiscoveredFile
    category: FileCategory
    confidence: float
    reasons: tuple[str, ...]
    classified_at: datetime
    classifier_id: str

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be within [0.0, 1.0], got {self.confidence!r}"
            )
        if not self.reasons:
            raise ValueError("reasons must be non-empty")
        if not self.classifier_id:
            raise ValueError("classifier_id must be non-empty")
        object.__setattr__(self, "classified_at", _normalize_to_utc(self.classified_at))
