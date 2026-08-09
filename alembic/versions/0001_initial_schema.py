"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-08 22:14:40.629039

"""

from collections.abc import Sequence

import sqlalchemy as sa

import file_agent.persistence.orm
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "domain_events",
        sa.Column("id", file_agent.persistence.orm.GUIDText(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column(
            "timestamp",
            file_agent.persistence.orm.UTCDateTimeText(length=32),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column(
            "entity_id", file_agent.persistence.orm.GUIDText(length=36), nullable=False
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_domain_events_entity",
        "domain_events",
        ["entity_type", "entity_id"],
        unique=False,
    )
    op.create_index(
        "ix_domain_events_timestamp", "domain_events", ["timestamp"], unique=False
    )
    op.create_table(
        "scans",
        sa.Column("id", file_agent.persistence.orm.GUIDText(length=36), nullable=False),
        sa.Column("root_path", sa.String(), nullable=False),
        sa.Column(
            "started_at",
            file_agent.persistence.orm.UTCDateTimeText(length=32),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            file_agent.persistence.orm.UTCDateTimeText(length=32),
            nullable=True,
        ),
        sa.Column("files_discovered", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed')",
            name="ck_scans_status_valid",
        ),
        sa.CheckConstraint(
            "files_discovered >= 0", name="ck_scans_files_discovered_nonneg"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "file_observations",
        sa.Column("id", file_agent.persistence.orm.GUIDText(length=36), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            file_agent.persistence.orm.UTCDateTimeText(length=32),
            nullable=False,
        ),
        sa.Column(
            "modified_at",
            file_agent.persistence.orm.UTCDateTimeText(length=32),
            nullable=False,
        ),
        sa.Column(
            "discovered_at",
            file_agent.persistence.orm.UTCDateTimeText(length=32),
            nullable=False,
        ),
        sa.Column(
            "discovered_by_scan_id",
            file_agent.persistence.orm.GUIDText(length=36),
            nullable=True,
        ),
        sa.CheckConstraint(
            "sha256 IS NULL OR length(sha256) = 64",
            name="ck_file_observations_sha256_len",
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_file_observations_size_nonneg"),
        sa.ForeignKeyConstraint(["discovered_by_scan_id"], ["scans.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_file_observations_path", "file_observations", ["path"], unique=False
    )
    op.create_index(
        "ix_file_observations_scan_id",
        "file_observations",
        ["discovered_by_scan_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_file_observations_scan_id", table_name="file_observations")
    op.drop_index("ix_file_observations_path", table_name="file_observations")
    op.drop_table("file_observations")
    op.drop_table("scans")
    op.drop_index("ix_domain_events_timestamp", table_name="domain_events")
    op.drop_index("ix_domain_events_entity", table_name="domain_events")
    op.drop_table("domain_events")
