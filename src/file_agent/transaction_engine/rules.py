"""Fixed constants: engine provenance and the AUTO-eligible logical-to-physical
destination mapping.

No filesystem I/O, no randomness. PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY
is the first place in the codebase that resolves a DestinationCategory into
any physical path -- FA-006 deliberately deferred this. It is used here only
to VERIFY a caller-supplied destination_path, never to choose one.
"""

from file_agent.domain import DestinationCategory

TRANSACTION_ENGINE_ID = "v1"
"""Stable identifier for this transaction engine's precondition/mutation
logic, persisted with every transaction event. Not "rules-v1": unlike the
classifier/proposal-engine/policy-engine, TransactionEngine has no
interpretive rule table evaluating ambiguous evidence -- its preconditions
are fixed mechanical checks executing an already-authorized decision. Bumped
only if the precondition set or mutation primitive changes in a way that
could alter behavior for the same input.
"""

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
