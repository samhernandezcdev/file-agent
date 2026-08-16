"""resolve_destination is the single physical-path derivation shared by
apply_item, OrganizationPlanner, and TransactionEngine's own request-
consistency check."""

from file_agent.destination import (
    PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY,
    resolve_destination,
)
from file_agent.domain import DestinationCategory
from file_agent.scanner import SandboxRoot


def test_resolves_within_the_configured_physical_directory(
    sandbox_root: SandboxRoot,
) -> None:
    result = resolve_destination(
        sandbox_root, DestinationCategory.DOCUMENTS, "report.pdf"
    )

    assert result == sandbox_root.path / "Documents" / "report.pdf"


def test_covers_every_destination_category(sandbox_root: SandboxRoot) -> None:
    for category in DestinationCategory:
        result = resolve_destination(sandbox_root, category, "file.bin")
        expected_dir = PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY[category]
        assert result == sandbox_root.path / expected_dir / "file.bin"


def test_preserves_the_exact_filename(sandbox_root: SandboxRoot) -> None:
    result = resolve_destination(
        sandbox_root, DestinationCategory.IMAGES, "vacation photo (final).JPG"
    )

    assert result.name == "vacation photo (final).JPG"
