"""Fixed provenance constant. No fixed mapping table -- HumanReviewEngine
validates structural linkage and outcome-vs-destination consistency, it
does not classify or map anything."""

HUMAN_REVIEW_ENGINE_ID = "v1"
"""Stable identifier for this human-review validation/recording logic,
persisted with every recorded review. Not "rules-v1": HumanReviewEngine
validates and records an already-made human decision -- fixed mechanical
checks, not an interpretive rule table over ambiguous evidence (same
reasoning TransactionEngine used for its own "v1", not "rules-v1", id).
Bump this string only if the validation logic changes in a way that could
alter what's accepted for the same input.
"""
