"""Fixed constant: engine provenance."""

RECOVERY_ENGINE_ID = "v1"
"""Stable identifier for this recovery engine's precondition/mutation logic,
persisted with every recovery event. Not "rules-v1": like TransactionEngine/
VaultEngine/HumanReviewEngine, RecoveryEngine has no interpretive rule table
evaluating ambiguous evidence -- its preconditions are fixed mechanical
checks. Bumped only if the precondition set or mutation sequence changes in
a way that could alter behavior for the same input.
"""
