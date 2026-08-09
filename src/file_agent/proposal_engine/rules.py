"""Fixed FileCategory -> DestinationCategory mapping.

No filesystem I/O, no randomness, no organization-root concept — a plain
in-memory lookup table, mirroring the classifier's rules.py precedent.
"""

from file_agent.domain import DestinationCategory, FileCategory

PROPOSAL_ENGINE_ID = "rules-v1"
"""Stable identifier for this deterministic proposal rule set, persisted with
every proposal (see proposal_engine.proposal_event). Bump this string if the
mapping table ever changes in a way that could produce different results for
the same input — not a version-framework, just an honest label on the
evidence.
"""

DESTINATION_FOR_CATEGORY: dict[FileCategory, DestinationCategory] = {
    FileCategory.DOCUMENT: DestinationCategory.DOCUMENTS,
    FileCategory.IMAGE: DestinationCategory.IMAGES,
    FileCategory.AUDIO: DestinationCategory.AUDIO,
    FileCategory.VIDEO: DestinationCategory.VIDEO,
    FileCategory.ARCHIVE: DestinationCategory.ARCHIVES,
    FileCategory.CODE: DestinationCategory.CODE,
    FileCategory.EXECUTABLE: DestinationCategory.EXECUTABLES,
    # OTHER, UNKNOWN: deliberately absent -- no destination can be proposed.
}
