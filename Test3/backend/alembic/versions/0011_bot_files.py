"""bot_files

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_COLUMNS = {"file_id", "bot_id", "filename", "chars", "content", "created_at"}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "bot_files" in inspector.get_table_names():
        actual = {column["name"] for column in inspector.get_columns("bot_files")}
        missing = _COLUMNS - actual
        if missing:
            raise RuntimeError(f"bot_files schema drift: missing {sorted(missing)}")
    else:
        op.create_table(
            "bot_files",
            sa.Column("file_id", sa.String(), primary_key=True),
            sa.Column("bot_id", sa.String(), sa.ForeignKey("bots.bot_id"), nullable=False),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("chars", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
        )
    op.execute("CREATE INDEX IF NOT EXISTS ix_bot_files_bot ON bot_files (bot_id)")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "bot_files" not in inspector.get_table_names():
        return
    op.execute("DROP INDEX IF EXISTS ix_bot_files_bot")
    op.drop_table("bot_files")
