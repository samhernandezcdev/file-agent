"""Neutral, shared destination-resolution/inspection module.

Owns the single source of truth for "where would this file go" --
PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY and resolve_destination -- and
the single source of truth for "is that destination safe to write to right
now" -- inspect_destination. Both file_agent.application (apply_item and
OrganizationPlanner) and file_agent.transaction_engine consume this package;
it depends on neither of them. This is the concrete mechanism behind FA-013's
required invariant: given identical filesystem state and identical
destination inputs, Preview (OrganizationPlan) and TransactionEngine agree on
every shared destination-readiness condition, because they call the literal
same function -- not two independently-maintained equivalents.

No filesystem mutation anywhere in this package.
"""

from file_agent.destination._paths import resolve_for_containment
from file_agent.destination.inspection import (
    DestinationConflict,
    DestinationInspection,
    inspect_destination,
)
from file_agent.destination.rules import (
    PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY,
    resolve_destination,
)

__all__ = [
    "PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY",
    "DestinationConflict",
    "DestinationInspection",
    "inspect_destination",
    "resolve_destination",
    "resolve_for_containment",
]
