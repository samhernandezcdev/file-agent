"""Fixed constant: engine provenance.

No filesystem I/O, no randomness.
"""

VAULT_ENGINE_ID = "v1"
"""Stable identifier for this vault engine's capture logic, persisted with
every vault event. Not "rules-v1": like TransactionEngine/HumanReviewEngine,
VaultEngine has no interpretive rule table evaluating ambiguous evidence --
its capture algorithm is a fixed mechanical procedure. Bumped only if the
capture algorithm or publication primitive changes in a way that could alter
behavior for the same input.
"""
