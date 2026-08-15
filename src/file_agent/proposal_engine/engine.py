"""ProposalEngine — deterministic, explainable destination proposals.

Performs no filesystem I/O of any kind — proposal generation is a pure,
total function over an already-in-memory ClassificationResult. See
docs/SAFETY.md and the FA-006 design plan's non-goals (no renaming, no
organization-root resolution, no authorization).
"""

from collections.abc import Callable
from datetime import UTC, datetime

from file_agent.classifier import ClassificationResult
from file_agent.domain import DomainEvent, EntityType, EventType, FileProposal
from file_agent.proposal_engine.rules import (
    DESTINATION_FOR_CATEGORY,
    PROPOSAL_ENGINE_ID,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ProposalEngine:
    """Proposes a logical destination for a DiscoveredFile from its classification.

    Never raises for a well-formed ClassificationResult — there is no I/O and
    nothing that can fail outside a caller's control. If no destination
    mapping exists for the classified category, the result has
    proposed_destination_category=None and confidence=0.0; this is a normal,
    safe result, not an exception. proposed_name and proposed_destination
    (the FA-001 absolute-path field) are always None — no renaming, no
    organization-root resolution in this ticket.
    """

    def __init__(self, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock

    def propose(self, classification: ClassificationResult) -> FileProposal:
        discovered = classification.discovered_file
        if discovered.sha256 is None:
            raise ValueError(
                "FileProposal requires a hashed DiscoveredFile -- "
                "classification.discovered_file.sha256 is None. Hash before "
                "classifying/proposing; this is a caller sequencing error, "
                "not a per-file business outcome."
            )
        destination = DESTINATION_FOR_CATEGORY.get(classification.category)
        classification_reason = (
            f"classification: category={classification.category.value}, "
            f"confidence={classification.confidence:.2f}, "
            f"classifier={classification.classifier_id}"
        )
        if destination is None:
            mapping_reason = (
                f"no destination mapping exists for category "
                f"{classification.category.value}"
            )
            confidence = 0.0
        else:
            mapping_reason = (
                f"destination mapping: {classification.category.value} -> "
                f"{destination.value}"
            )
            confidence = classification.confidence

        return FileProposal(
            file_id=discovered.id,
            proposed_name=None,
            proposed_destination=None,
            proposed_destination_category=destination,
            category=classification.category,
            confidence=confidence,
            source_classification_confidence=classification.confidence,
            source_classifier_id=classification.classifier_id,
            reasons=(classification_reason, mapping_reason),
            created_at=self._clock(),
            proposal_engine_id=PROPOSAL_ENGINE_ID,
            expected_size=discovered.size_bytes,
            expected_created_at=discovered.created_at,
            expected_modified_at=discovered.modified_at,
            sha256=discovered.sha256,
        )


def propose_for(classification: ClassificationResult) -> FileProposal:
    """Convenience entry point: ``ProposalEngine().propose(classification)``."""
    return ProposalEngine().propose(classification)


def proposal_event(proposal: FileProposal) -> DomainEvent:
    """Maps a FileProposal to a PROPOSAL_CREATED DomainEvent.

    Does not persist anything itself — this package has no dependency on
    file_agent.persistence. A caller passes the returned event straight to
    FileAgentStore.record_event().
    """
    return DomainEvent(
        event_type=EventType.PROPOSAL_CREATED,
        entity_type=EntityType.PROPOSAL,
        entity_id=proposal.id,
        timestamp=proposal.created_at,
        payload={
            "file_id": str(proposal.file_id),
            "category": proposal.category.value,
            "proposed_destination_category": (
                proposal.proposed_destination_category.value
                if proposal.proposed_destination_category is not None
                else None
            ),
            "proposed_name": proposal.proposed_name,
            "confidence": proposal.confidence,
            "source_classification_confidence": proposal.source_classification_confidence,
            "source_classifier_id": proposal.source_classifier_id,
            "reasons": list(proposal.reasons),
            "proposal_engine_id": proposal.proposal_engine_id,
            "expected_size": proposal.expected_size,
            "expected_created_at": proposal.expected_created_at.isoformat(),
            "expected_modified_at": proposal.expected_modified_at.isoformat(),
            "sha256": proposal.sha256,
        },
    )
