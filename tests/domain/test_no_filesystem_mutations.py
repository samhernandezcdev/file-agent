"""Guardrail: the domain layer must never call filesystem-mutating APIs.

This turns docs/SAFETY.md's read-only requirement into an executable check
instead of relying solely on code review.
"""

from pathlib import Path

FORBIDDEN_TOKENS = [
    "os.remove",
    "os.unlink",
    "os.rmdir",
    ".unlink(",
    ".rename(",
    ".replace(",
    "shutil.move",
    "shutil.rmtree",
]

DOMAIN_DIR = Path(__file__).resolve().parents[2] / "src" / "file_agent" / "domain"


def test_no_domain_source_file_mutates_the_filesystem() -> None:
    domain_files = sorted(DOMAIN_DIR.glob("*.py"))
    assert domain_files, f"expected domain source files under {DOMAIN_DIR}"

    offenders: list[str] = []
    for path in domain_files:
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            if token in text:
                offenders.append(f"{path.name}: {token!r}")

    assert not offenders, f"forbidden filesystem-mutation tokens found: {offenders}"
