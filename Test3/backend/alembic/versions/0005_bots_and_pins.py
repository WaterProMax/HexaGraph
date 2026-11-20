"""bots and bot_pin_revisions

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_BOT_COLUMNS = {"bot_id", "display_name", "status", "payload", "created_at"}
_PIN_COLUMNS = {"bot_id", "revision", "model", "provider_ref", "skill_bindings", "created_at"}


def _verify(table: str, expected: set[str]) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    actual = {column["name"] for column in inspector.get_columns(table)}
    missing = expected - actual
    if missing:
        raise RuntimeError(f"{table} schema drift: missing {sorted(missing)}")
    return True


def upgrade() -> None:
    if not _verify("bots", _BOT_COLUMNS):
        op.create_table(
            "bots",
            sa.Column("bot_id", sa.String(), primary_key=True),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
        )
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("bots")}
    if "uq_bots_display_name_ci" not in indexes:
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_bots_display_name_ci "
            "ON bots (lower(display_name))"
        )

    if not _verify("bot_pin_revisions", _PIN_COLUMNS):
        op.create_table(
            "bot_pin_revisions",
            sa.Column("bot_id", sa.String(), primary_key=True),
            sa.Column("revision", sa.Integer(), primary_key=True),
            sa.Column("model", sa.String(), nullable=False),
            sa.Column("provider_ref", sa.String(), nullable=False),
            sa.Column("skill_bindings", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    if "bot_pin_revisions" in tables:
        op.drop_table("bot_pin_revisions")
    if "bots" in tables:
        op.execute("DROP INDEX IF EXISTS uq_bots_display_name_ci")
        op.drop_table("bots")