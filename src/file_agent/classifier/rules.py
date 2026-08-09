"""Deterministic, extension/filename-only classification rules.

No filesystem I/O, no randomness, no external state — every rule is a pure
function of a DiscoveredFile's already-in-memory fields, so the same input
always produces the same verdict.
"""

from collections.abc import Callable
from dataclasses import dataclass

from file_agent.domain import DiscoveredFile, FileCategory

CLASSIFIER_ID = "rules-v1"
"""Stable identifier for this deterministic rule set, persisted with every
classification (see classifier.classification_event). Bump this string if the
rule tables ever change in a way that could produce different results for the
same input — not a version-framework, just an honest label on the evidence.
"""


@dataclass(frozen=True, slots=True)
class _RuleVerdict:
    category: FileCategory
    confidence: float
    reason: str


_RuleFn = Callable[[DiscoveredFile], "_RuleVerdict | None"]

_EXTENSION_TABLE: dict[str, FileCategory] = {
    # DOCUMENT
    "pdf": FileCategory.DOCUMENT,
    "doc": FileCategory.DOCUMENT,
    "docx": FileCategory.DOCUMENT,
    "odt": FileCategory.DOCUMENT,
    "rtf": FileCategory.DOCUMENT,
    "txt": FileCategory.DOCUMENT,
    "md": FileCategory.DOCUMENT,
    "csv": FileCategory.DOCUMENT,
    "xls": FileCategory.DOCUMENT,
    "xlsx": FileCategory.DOCUMENT,
    "ods": FileCategory.DOCUMENT,
    "ppt": FileCategory.DOCUMENT,
    "pptx": FileCategory.DOCUMENT,
    "odp": FileCategory.DOCUMENT,
    "epub": FileCategory.DOCUMENT,
    # IMAGE
    "jpg": FileCategory.IMAGE,
    "jpeg": FileCategory.IMAGE,
    "png": FileCategory.IMAGE,
    "gif": FileCategory.IMAGE,
    "bmp": FileCategory.IMAGE,
    "svg": FileCategory.IMAGE,
    "webp": FileCategory.IMAGE,
    "tiff": FileCategory.IMAGE,
    "tif": FileCategory.IMAGE,
    "ico": FileCategory.IMAGE,
    "heic": FileCategory.IMAGE,
    # AUDIO
    "mp3": FileCategory.AUDIO,
    "wav": FileCategory.AUDIO,
    "flac": FileCategory.AUDIO,
    "aac": FileCategory.AUDIO,
    "ogg": FileCategory.AUDIO,
    "wma": FileCategory.AUDIO,
    "m4a": FileCategory.AUDIO,
    # VIDEO
    "mp4": FileCategory.VIDEO,
    "mkv": FileCategory.VIDEO,
    "avi": FileCategory.VIDEO,
    "mov": FileCategory.VIDEO,
    "wmv": FileCategory.VIDEO,
    "flv": FileCategory.VIDEO,
    "webm": FileCategory.VIDEO,
    "m4v": FileCategory.VIDEO,
    # ARCHIVE
    "zip": FileCategory.ARCHIVE,
    "rar": FileCategory.ARCHIVE,
    "7z": FileCategory.ARCHIVE,
    "tar": FileCategory.ARCHIVE,
    "gz": FileCategory.ARCHIVE,
    "bz2": FileCategory.ARCHIVE,
    "xz": FileCategory.ARCHIVE,
    "iso": FileCategory.ARCHIVE,
    # CODE — source/scripts that require an explicit interpreter, not launched by name
    "py": FileCategory.CODE,
    "js": FileCategory.CODE,
    "ts": FileCategory.CODE,
    "jsx": FileCategory.CODE,
    "tsx": FileCategory.CODE,
    "java": FileCategory.CODE,
    "c": FileCategory.CODE,
    "cpp": FileCategory.CODE,
    "h": FileCategory.CODE,
    "hpp": FileCategory.CODE,
    "cs": FileCategory.CODE,
    "go": FileCategory.CODE,
    "rs": FileCategory.CODE,
    "rb": FileCategory.CODE,
    "php": FileCategory.CODE,
    "sh": FileCategory.CODE,
    "ps1": FileCategory.CODE,
    "sql": FileCategory.CODE,
    "html": FileCategory.CODE,
    "css": FileCategory.CODE,
    "json": FileCategory.CODE,
    "yaml": FileCategory.CODE,
    "yml": FileCategory.CODE,
    "toml": FileCategory.CODE,
    "xml": FileCategory.CODE,
    # EXECUTABLE — directly launched/loaded by the OS by name
    "exe": FileCategory.EXECUTABLE,
    "msi": FileCategory.EXECUTABLE,
    "dll": FileCategory.EXECUTABLE,
    "bat": FileCategory.EXECUTABLE,
    "cmd": FileCategory.EXECUTABLE,
    "com": FileCategory.EXECUTABLE,  # DOS MZ executable; also used for COM component
    # registrations (dll-like) on modern Windows — both meanings fit EXECUTABLE
    "sys": FileCategory.EXECUTABLE,
    "scr": FileCategory.EXECUTABLE,
}

_SPECIAL_FILENAMES: dict[str, FileCategory] = {
    "dockerfile": FileCategory.CODE,
    "makefile": FileCategory.CODE,
    "readme": FileCategory.DOCUMENT,
    "license": FileCategory.DOCUMENT,
    "changelog": FileCategory.DOCUMENT,
    "authors": FileCategory.DOCUMENT,
    "contributing": FileCategory.DOCUMENT,
    "notice": FileCategory.DOCUMENT,
}


def _rule_extension(discovered: DiscoveredFile) -> _RuleVerdict | None:
    category = _EXTENSION_TABLE.get(discovered.extension)
    if category is None:
        return None
    return _RuleVerdict(
        category=category,
        confidence=1.0,
        reason=f"extension '{discovered.extension}' matched category {category.value}",
    )


def _rule_special_filename(discovered: DiscoveredFile) -> _RuleVerdict | None:
    if discovered.extension:
        return None
    category = _SPECIAL_FILENAMES.get(discovered.filename.lower())
    if category is None:
        return None
    return _RuleVerdict(
        category=category,
        confidence=1.0,
        reason=f"filename '{discovered.filename}' matched a well-known name ({category.value})",
    )


def _rule_dotfile_convention(discovered: DiscoveredFile) -> _RuleVerdict | None:
    """Matches any dot-prefixed filename not already resolved by the extension
    rule — e.g. ".env", ".env.local", ".gitignore", ".gitignore.bak" all match.

    Deliberately NOT gated on `discovered.extension` being empty: pathlib
    assigns a (spurious, for this purpose) suffix to names like ".env.local"
    (extension "local") the same way it does for genuine extensions, but
    that's still a dotfile by convention, not a recognized file type. Rule
    ORDER is what keeps this safe — _rule_extension always runs first, so a
    genuinely recognized extension (e.g. ".hidden.jpg" -> "jpg") already wins
    before this rule is ever reached. This stays the single, narrow dotfile
    convention already in place — not a broader filename heuristic.
    """
    if len(discovered.filename) > 1 and discovered.filename.startswith("."):
        return _RuleVerdict(
            category=FileCategory.OTHER,
            confidence=1.0,
            reason=f"filename '{discovered.filename}' follows dotfile/config naming convention",
        )
    return None


RULES: tuple[_RuleFn, ...] = (
    _rule_extension,
    _rule_special_filename,
    _rule_dotfile_convention,
)
