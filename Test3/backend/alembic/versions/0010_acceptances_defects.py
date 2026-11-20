"""module_acceptances, defects

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_ACCEPTANCE_COLUMNS = {"acceptance_id", "run_id", "module_id", "payload"}
_DEFECT_COLUMNS = {"defect_id", "run_id", "task_code", "payload"}


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
    if not _verify("module_acceptances", _ACCEPTANCE_COLUMNS):
        op.create_table(
            "module_acceptances",
            sa.Column("acceptance_id", sa.String(), primary_key=True),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("module_id", sa.String(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
        )
    if not _verify("defects", _DEFECT_COLUMNS):
        op.create_table(
            "defects",
            sa.Column("defect_id", sa.String(), primary_key=True),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("task_code", sa.String(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    if "defects" in tables:
        op.drop_table("defects")
    if "module_acceptances" in tables:
        op.drop_table("module_acceptances")