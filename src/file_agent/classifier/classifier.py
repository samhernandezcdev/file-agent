"""FileClassifier — deterministic, explainable classification of a DiscoveredFile.

Performs no filesystem I/O of any kind (not even a stat()) — classification
is a pure, total function over a DiscoveredFile's already-in-memory fields.
See docs/SAFETY.md and the FA-005 design plan's "no content inspection"
decision.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from file_agent.classifier.result import ClassificationResult
from file_agent.classifier.rules import CLASSIFIER_ID, RULES
from file_agent.domain import (
    DiscoveredFile,
    DomainEvent,
    EntityType,
    EventType,
    FileCategory,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FileClassifier:
    """Classifies a DiscoveredFile using a fixed, ordered set of deterministic rules.

    Never raises for a well-formed DiscoveredFile — there is no I/O and
    nothing that can fail outside a caller's control. If no rule matches,
    the result is UNKNOWN with confidence 0.0; this is a normal, safe
    result, not an exception.
    """

    def __init__(self, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock

    def classify(self, discovered: DiscoveredFile) -> ClassificationResult:
        reasons: list[str] = []
        for rule in RULES:
            verdict = rule(discovered)
            if verdict is not None:
                return ClassificationResult(
                    discovered_file=discovered,
                    category=verdict.category,
                    confidence=verdict.confidence,
                    reasons=(verdict.reason,),
                    classified_at=self._clock(),
                    classifier_id=CLASSIFIER_ID,
                )
            reasons.append(_miss_reason(rule, discovered))

        return ClassificationResult(
            discovered_file=discovered,
            category=FileCategory.UNKNOWN,
            confidence=0.0,
            reasons=tuple(reasons),
            classified_at=self._clock(),
            classifier_id=CLASSIFIER_ID,
        )


def _miss_reason(
    rule: Callable[[DiscoveredFile], object], discovered: DiscoveredFile
) -> str:
    name = rule.__name__.removeprefix("_rule_")
    return f"{name}: no match (extension={discovered.extension!r}, filename={discovered.filename!r})"


def classify_file(discovered: DiscoveredFile) -> ClassificationResult:
    """Convenience entry point: ``FileClassifier().classify(discovered)``."""
    return FileClassifier().classify(discovered)


def classification_event(result: ClassificationResult) -> DomainEvent:
    """Maps a ClassificationResult to a FILE_CLASSIFIED DomainEvent.

    Does not persist anything itself — this package has no dependency on
    file_agent.persistence. A caller passes the returned event straight to
    FileAgentStore.record_event().
    """
    return DomainEvent(
        event_type=EventType.FILE_CLASSIFIED,
        entity_type=EntityType.FILE,
        entity_id=result.discovered_file.id,
        timestamp=result.classified_at,
        payload={
            "category": result.category.value,
            "confidence": result.confidence,
            "reasons": list(result.reasons),
            "path": str(result.discovered_file.path),
            "classifier_id": result.classifier_id,
        },
    )
