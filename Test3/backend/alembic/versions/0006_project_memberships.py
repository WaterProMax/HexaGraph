"""project_memberships

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_COLUMNS = {"project_id", "bot_id", "role_in_project", "is_leader", "payload"}


def _existing() -> bool:
    inspector = sa.inspect(op.get_bind())
    if "project_memberships" not in inspector.get_table_names():
        return False
    actual = {column["name"] for column in inspector.get_columns("project_memberships")}
    missing = _COLUMNS - actual
    if missing:
        raise RuntimeError(f"project_memberships schema drift: missing {sorted(missing)}")
    return True


def upgrade() -> None:
    if not _existing():
        op.create_table(
            "project_memberships",
            sa.Column("project_id", sa.String(), primary_key=True),
            sa.Column("bot_id", sa.String(), sa.ForeignKey("bots.bot_id"), primary_key=True),
            sa.Column("role_in_project", sa.String(), nullable=False),
            sa.Column("is_leader", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("payload", sa.JSON(), nullable=False),
        )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_project_one_leader "
        "ON project_memberships (project_id) WHERE is_leader = 1"
    )


def downgrade() -> None:
    if "project_memberships" in sa.inspect(op.get_bind()).get_table_names():
        op.execute("DROP INDEX IF EXISTS uq_project_one_leader")
        op.drop_table("project_memberships")