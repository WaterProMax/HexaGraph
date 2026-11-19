"""execution_grants

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-19
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_grants",
        sa.Column("grant_id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
    )
    op.create_index("ix_execution_grants_run", "execution_grants", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_execution_grants_run", table_name="execution_grants")
    op.drop_table("execution_grants")