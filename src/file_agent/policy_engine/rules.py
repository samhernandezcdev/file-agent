"""Fixed policy-eligibility constants: threshold and the AUTO allowlist.

No filesystem I/O, no randomness. AUTO_ELIGIBLE_PAIRS is defined
independently of proposal_engine.rules.DESTINATION_FOR_CATEGORY -- proposal
mapping (what destination FA-006 proposes) and policy authorization (what
FA-007 permits to auto-execute) are separate responsibilities that may
intentionally diverge, even though their v1 contents happen to overlap.
"""

from file_agent.domain import DestinationCategory, FileCategory

POLICY_ENGINE_ID = "rules-v1"
"""Stable identifier for this deterministic policy rule set, persisted with
every decision (see policy_engine.policy_decision_event). Bump this string if
the rules ever change in a way that could produce a different decision for
the same input -- not a version-framework, just an honest label on the
evidence.
"""

AUTO_CONFIDENCE_THRESHOLD = 1.0
"""Minimum proposal confidence required for AUTO eligibility, once a proposal
has already cleared the destination/category/allowlist gates. Expressed as a
named constant compared with `>=` rather than a bare `== 1.0` literal, so a
future ticket introducing genuinely probabilistic evidence can lower it
without changing the engine's control-flow shape -- but today's deterministic
FA-005/FA-006 output is effectively binary (1.0 or 0.0), so this is honestly
`== 1.0` in practice, not a calibrated threshold.
"""

AUTO_ELIGIBLE_PAIRS: frozenset[tuple[FileCategory, DestinationCategory]] = frozenset(
    {
        (FileCategory.DOCUMENT, DestinationCategory.DOCUMENTS),
        (FileCategory.IMAGE, DestinationCategory.IMAGES),
        (FileCategory.AUDIO, DestinationCategory.AUDIO),
        (FileCategory.VIDEO, DestinationCategory.VIDEO),
        (FileCategory.ARCHIVE, DestinationCategory.ARCHIVES),
        (FileCategory.CODE, DestinationCategory.CODE),
        # (EXECUTABLE, EXECUTABLES) deliberately absent -- also independently
        # enforced by the dedicated EXECUTABLE override in engine.py.
    }
)
"""The only (FileCategory, DestinationCategory) pairs eligible for AUTO.
Default-deny: a pair absent from this set can never reach AUTO, regardless of
confidence -- AUTO requires an explicit positive match, not merely the
absence of an earlier rejection."""
