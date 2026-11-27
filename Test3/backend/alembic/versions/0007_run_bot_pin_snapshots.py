"""run_bot_pin_snapshots

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_COLUMNS = {"run_id", "bot_id", "payload"}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "run_bot_pin_snapshots" in inspector.get_table_names():
        actual = {column["name"] for column in inspector.get_columns("run_bot_pin_snapshots")}
        missing = _COLUMNS - actual
        if missing:
            raise RuntimeError(f"run_bot_pin_snapshots schema drift: missing {sorted(missing)}")
        return
    op.create_table(
        "run_bot_pin_snapshots",
        sa.Column("run_id", sa.String(), primary_key=True),
        sa.Column("bot_id", sa.String(), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    if "run_bot_pin_snapshots" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("run_bot_pin_snapshots")