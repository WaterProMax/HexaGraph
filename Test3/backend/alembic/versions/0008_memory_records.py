"""memory_records

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_COLUMNS = {
    "mem_id",
    "version",
    "owner_bot_id",
    "project_id",
    "visibility",
    "status",
    "payload",
}

TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_memory_body_immutable
BEFORE UPDATE ON memory_records
WHEN NEW.mem_id = OLD.mem_id AND NEW.version = OLD.version
 AND json_extract(NEW.payload,'$.body') IS NOT json_extract(OLD.payload,'$.body')
BEGIN SELECT RAISE(ABORT, 'memory body is immutable'); END
"""


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "memory_records" in inspector.get_table_names():
        actual = {column["name"] for column in inspector.get_columns("memory_records")}
        missing = _COLUMNS - actual
        if missing:
            raise RuntimeError(f"memory_records schema drift: missing {sorted(missing)}")
    else:
        op.create_table(
            "memory_records",
            sa.Column("mem_id", sa.String(), primary_key=True),
            sa.Column("version", sa.Integer(), primary_key=True),
            sa.Column("owner_bot_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("visibility", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memory_owner "
        "ON memory_records (owner_bot_id, visibility)"
    )
    op.execute(TRIGGER_SQL)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "memory_records" not in inspector.get_table_names():
        return
    op.execute("DROP TRIGGER IF EXISTS trg_memory_body_immutable")
    op.execute("DROP INDEX IF EXISTS ix_memory_owner")
    op.drop_table("memory_records")