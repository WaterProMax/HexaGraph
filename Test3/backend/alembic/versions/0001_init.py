"""init

Revision ID: 0001
Revises:
Create Date: 2026-11-05
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("profile", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
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
