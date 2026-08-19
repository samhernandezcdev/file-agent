"""Fixed constant and pure derivation: the AUTO/REVIEW-eligible logical-to-
physical destination mapping, and the single function that turns a
(sandbox_root, destination_category, filename) triple into the one physical
path a future MOVE would use.

No filesystem I/O, no randomness. This is the single source of truth for
"where would this file go" -- moved here (from its original home in
file_agent.transaction_engine.rules) once it became depended on by three
callers with no ownership relationship to each other: application/service.py
(apply_item), application/planner.py (OrganizationPlanner), and
transaction_engine itself. Callers/UI never choose a physical path; it is
derived only from a trusted sandbox_root + trusted destination_category +
the source file's own filename.
"""

from pathlib import Path

from file_agent.domain import DestinationCategory
from file_agent.scanner import SandboxRoot

PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY: dict[DestinationCategory, str] = {
    DestinationCategory.DOCUMENTS: "Documents",
    DestinationCategory.IMAGES: "Images",
    DestinationCategory.AUDIO: "Audio",
    DestinationCategory.VIDEO: "Video",
    DestinationCategory.ARCHIVES: "Archives",
    DestinationCategory.CODE: "Code",
    DestinationCategory.EXECUTABLES: "Executables",
}
"""One fixed, flat, single-level mapping -- sandbox_root / this value. All
seven DestinationCategory members are covered (not just FA-007's six
AUTO_ELIGIBLE_PAIRS members), deliberately uncoupled from FA-007's own
eligibility table -- same "defined independently, may intentionally diverge"
precedent FA-007 itself established relative to FA-006's own mapping.
"""


def resolve_destination(
    sandbox_root: SandboxRoot, destination_category: DestinationCategory, filename: str
) -> Path:
    """The one function that turns a logical destination_category + filename
    into the physical path a MOVE would use. Every caller that needs a
    destination path -- apply_item, OrganizationPlanner, and
    TransactionEngine's own request-consistency check -- calls this, so
    "what preview shows" and "what apply attempts" can never independently
    drift apart on where a file goes."""
    return (
        sandbox_root.path
        / PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY[destination_category]
        / filename
    )


def resolve_destination_directory(
    sandbox_root: SandboxRoot, destination_category: DestinationCategory
) -> Path:
    """FA-017.2: the parent-folder half of resolve_destination, without a
    filename -- the exact prospective directory destination_engine may be
    asked to create. Same fixed mapping, same no-I/O purity; never a
    caller-supplied path."""
    return (
        sandbox_root.path
        / PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY[destination_category]
    )
