"""run_execution_state

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-19
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "run_execution_state" in inspector.get_table_names():
        # Older Workbench ``create_all()`` may already have created this table.
        # Verify the expected columns instead of silently stamping over drift.
        columns = {column["name"] for column in inspector.get_columns("run_execution_state")}
        expected = {
            "run_id",
            "execution_profile",
            "approved_baseline_hashes",
            "approved_plan_hash",
            "allowed_tool_refs",
            "updated_at",
        }
        if not expected <= columns:
            raise RuntimeError(f"run_execution_state schema drift: missing {sorted(expected - columns)}")
        return
    op.create_table(
        "run_execution_state",
        sa.Column("run_id", sa.String(), primary_key=True),
        sa.Column("execution_profile", sa.String(), nullable=False),
        sa.Column("approved_baseline_hashes", sa.Text(), nullable=False),
        sa.Column("approved_plan_hash", sa.String(), nullable=False),
        sa.Column("allowed_tool_refs", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "run_execution_state" in sa.inspect(bind).get_table_names():
        op.drop_table("run_execution_state")
