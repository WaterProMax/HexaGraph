"""discussion_sessions, discussion_proposals, discussion_reviews

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_SESSION_COLUMNS = {"session_id", "project_id", "status", "payload"}
_PROPOSAL_COLUMNS = {
    "proposal_id",
    "session_id",
    "author_bot_id",
    "round",
    "sealed",
    "body_md",
}
_REVIEW_COLUMNS = {
    "review_id",
    "session_id",
    "reviewer_bot_id",
    "proposal_id",
    "payload",
}


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
    if not _verify("discussion_sessions", _SESSION_COLUMNS):
        op.create_table(
            "discussion_sessions",
            sa.Column("session_id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
        )
    if not _verify("discussion_proposals", _PROPOSAL_COLUMNS):
        op.create_table(
            "discussion_proposals",
            sa.Column("proposal_id", sa.String(), primary_key=True),
            sa.Column("session_id", sa.String(), nullable=False),
            sa.Column("author_bot_id", sa.String(), nullable=False),
            sa.Column("round", sa.Integer(), nullable=False),
            sa.Column("sealed", sa.Integer(), nullable=False),
            sa.Column("body_md", sa.Text(), nullable=False),
            sa.UniqueConstraint(
                "session_id",
                "author_bot_id",
                "round",
                name="uq_discussion_proposals_author_round",
            ),
        )
    if not _verify("discussion_reviews", _REVIEW_COLUMNS):
        op.create_table(
            "discussion_reviews",
            sa.Column("review_id", sa.String(), primary_key=True),
            sa.Column("session_id", sa.String(), nullable=False),
            sa.Column("reviewer_bot_id", sa.String(), nullable=False),
            sa.Column("proposal_id", sa.String(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.UniqueConstraint(
                "session_id",
                "reviewer_bot_id",
                "proposal_id",
                name="uq_discussion_reviews_reviewer_proposal",
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    if "discussion_reviews" in tables:
        op.drop_table("discussion_reviews")
    if "discussion_proposals" in tables:
        op.drop_table("discussion_proposals")
    if "discussion_sessions" in tables:
        op.drop_table("discussion_sessions")