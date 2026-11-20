"""skill_definitions

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_COLUMNS = {"skill_id", "version", "payload"}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "skill_definitions" in inspector.get_table_names():
        actual = {column["name"] for column in inspector.get_columns("skill_definitions")}
        missing = _COLUMNS - actual
        if missing:
            raise RuntimeError(f"skill_definitions schema drift: missing {sorted(missing)}")
        return
    op.create_table(
        "skill_definitions",
        sa.Column("skill_id", sa.String(), primary_key=True),
        sa.Column("version", sa.String(), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    if "skill_definitions" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("skill_definitions")