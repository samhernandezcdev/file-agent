"""managed roots

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-16 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

import file_agent.persistence.orm
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "managed_roots",
        sa.Column("id", file_agent.persistence.orm.GUIDText(length=36), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            file_agent.persistence.orm.UTCDateTimeText(length=32),
            nullable=False,
        ),
        sa.Column(
            "removed_at",
            file_agent.persistence.orm.UTCDateTimeText(length=32),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_managed_roots_active_path",
        "managed_roots",
        ["path"],
        unique=True,
        sqlite_where=sa.text("removed_at IS NULL"),
    )
    op.add_column(
        "file_observations",
        sa.Column(
            "managed_root_id",
            file_agent.persistence.orm.GUIDText(length=36),
            nullable=True,
        ),
    )
    with op.batch_alter_table("file_observations") as batch_op:
        batch_op.create_foreign_key(
            "fk_file_observations_managed_root_id",
            "managed_roots",
            ["managed_root_id"],
            ["id"],
        )
    op.create_index(
        "ix_file_observations_managed_root_id",
        "file_observations",
        ["managed_root_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_file_observations_managed_root_id", table_name="file_observations"
    )
    with op.batch_alter_table("file_observations") as batch_op:
        batch_op.drop_constraint(
            "fk_file_observations_managed_root_id", type_="foreignkey"
        )
    op.drop_column("file_observations", "managed_root_id")
    op.drop_index("ux_managed_roots_active_path", table_name="managed_roots")
    op.drop_table("managed_roots")
