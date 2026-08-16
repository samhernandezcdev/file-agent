"""Fixed constant: engine provenance.

The AUTO-eligible logical-to-physical destination mapping
(PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY) and its derivation function
(resolve_destination) moved to file_agent.destination.rules as of FA-013 --
promoted to a neutral module once it became depended on by three callers
with no ownership relationship to each other (apply_item, OrganizationPlanner,
and this package's own check_destination_category_physical_path).
"""

TRANSACTION_ENGINE_ID = "v1"
"""Stable identifier for this transaction engine's precondition/mutation
logic, persisted with every transaction event. Not "rules-v1": unlike the
classifier/proposal-engine/policy-engine, TransactionEngine has no
interpretive rule table evaluating ambiguous evidence -- its preconditions
are fixed mechanical checks executing an already-authorized decision. Bumped
only if the precondition set or mutation primitive changes in a way that
could alter behavior for the same input.
"""
