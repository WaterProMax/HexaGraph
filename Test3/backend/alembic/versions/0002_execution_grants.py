"""execution_grants

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-19

If an older Workbench already created ``execution_grants`` through
``create_all()``, verify the expected columns/index and adopt it.  This is not a
``stamp``: the column set is checked and drift fails the upgrade.
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_COLUMNS = {"grant_id", "run_id", "status", "payload"}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "execution_grants" not in inspector.get_table_names():
        op.create_table(
            "execution_grants",
            sa.Column("grant_id", sa.String(), primary_key=True),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("payload", sa.Text(), nullable=False),
        )
        op.create_index("ix_execution_grants_run", "execution_grants", ["run_id"])
        return
    actual = {column["name"] for column in inspector.get_columns("execution_grants")}
    missing = _COLUMNS - actual
    if missing:
        raise RuntimeError(f"execution_grants schema drift: missing columns {sorted(missing)}")
    indexes = {index["name"] for index in inspector.get_indexes("execution_grants")}
    if "ix_execution_grants_run" not in indexes:
        op.create_index("ix_execution_grants_run", "execution_grants", ["run_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "execution_grants" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("execution_grants")}
    if "ix_execution_grants_run" in indexes:
        op.drop_index("ix_execution_grants_run", table_name="execution_grants")
    op.drop_table("execution_grants")
