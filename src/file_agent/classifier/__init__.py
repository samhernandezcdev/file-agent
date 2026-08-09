"""Deterministic, explainable file classification.

Given a DiscoveredFile, answers "what kind of file does this appear to be?"
using fixed extension/filename rules — no filesystem I/O, no LLM, no
randomness. UNKNOWN is a normal, safe result, never an exception. Does not
decide where a file should go, what it should be renamed to, or whether it
should be organized — see docs/SAFETY.md and the FA-005 design plan.
"""

from file_agent.classifier.classifier import (
    FileClassifier,
    classification_event,
    classify_file,
)
from file_agent.classifier.result import ClassificationResult
from file_agent.classifier.rules import CLASSIFIER_ID

__all__ = [
    "CLASSIFIER_ID",
    "ClassificationResult",
    "FileClassifier",
    "classification_event",
    "classify_file",
]
