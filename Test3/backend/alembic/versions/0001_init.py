"""init

Revision ID: 0001
Revises:
Create Date: 2026-11-05

The upgrade is schema-aware: an older Workbench used ``Base.metadata.create_all``
and could create these tables without an ``alembic_version`` row.  We verify the
existing columns and adopt the schema instead of failing or blindly stamping.
"""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_PROJECT_COLUMNS = {"id", "name", "profile", "created_at"}
_RUN_COLUMNS = {
    "id",
    "project_id",
    "status",
    "current_stage",
    "revision",
    "limits_json",
    "idea",
    "paused",
    "created_at",
}
_EVENT_COLUMNS = {"id", "run_id", "seq", "ts", "actor", "kind", "subject", "payload_json"}


def _verify_columns(table: str, expected: set[str]) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    actual = {column["name"] for column in inspector.get_columns(table)}
    missing = expected - actual
    if missing:
        raise RuntimeError(f"{table} schema drift: missing columns {sorted(missing)}")
    return True


def upgrade() -> None:
    if not _verify_columns("project", _PROJECT_COLUMNS):
        op.create_table(
            "project",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("profile", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )
    if not _verify_columns("run", _RUN_COLUMNS):
        op.create_table(
            "run",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), sa.ForeignKey("project.id")),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("current_stage", sa.String(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("limits_json", sa.Text(), nullable=False),
            sa.Column("idea", sa.Text(), nullable=False),
            sa.Column("paused", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )
    if not _verify_columns("event", _EVENT_COLUMNS):
        op.create_table(
            "event",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.String(), sa.ForeignKey("run.id")),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("ts", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("actor", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("subject", sa.String(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("event")
    op.drop_table("run")
    op.drop_table("project")
