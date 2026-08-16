"""Language-neutral rendering shapes for the Spanish (and any future
language's) presentation layer. Pure data -- no strings, no translation
logic, no dependency on application/domain at all. es.py is the only module
that fills these in with actual copy.
"""

from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    INFO = "info"
    ATTENTION = "attention"
    ERROR = "error"


class SuggestedAction(str, Enum):
    NONE = "none"
    APPROVE = "approve"
    REANALYZE = "reanalyze"
    REVIEW_CONFLICT = "review_conflict"


@dataclass(frozen=True, slots=True)
class UserMessage:
    title: str
    detail: str
    severity: Severity
    suggested_action: SuggestedAction
