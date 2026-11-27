"""discussion_messages

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_COLUMNS = {"session_id", "seq", "kind", "bot_id", "round", "payload", "created_at"}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "discussion_messages" in inspector.get_table_names():
        actual = {
            column["name"] for column in inspector.get_columns("discussion_messages")
        }
        missing = _COLUMNS - actual
        if missing:
            raise RuntimeError(
                f"discussion_messages schema drift: missing {sorted(missing)}"
            )
    else:
        op.create_table(
            "discussion_messages",
            sa.Column("session_id", sa.String(), primary_key=True),
            sa.Column("seq", sa.Integer(), primary_key=True),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("bot_id", sa.String(), nullable=True),
            sa.Column("round", sa.Integer(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_discussion_messages_session "
        "ON discussion_messages (session_id)"
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "discussion_messages" not in inspector.get_table_names():
        return
    op.execute("DROP INDEX IF EXISTS ix_discussion_messages_session")
    op.drop_table("discussion_messages")