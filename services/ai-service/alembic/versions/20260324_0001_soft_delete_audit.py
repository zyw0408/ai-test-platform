"""add soft delete and audit support

Revision ID: 20260324_0001
Revises: 
Create Date: 2026-03-24 03:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_0001"
down_revision = None
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column in {item["name"] for item in inspector.get_columns(table)}


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    if _has_table("requirements") and not _has_column("requirements", "deleted_at"):
        op.add_column("requirements", sa.Column("deleted_at", sa.Text(), nullable=True))
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_requirements_fts
            ON requirements
            USING GIN (
                to_tsvector(
                    'simple',
                    COALESCE(title, '') || ' ' || COALESCE(content, '') || ' ' || COALESCE(tags_json, '')
                )
            )
            """
        )
    if _has_table("entities") and not _has_column("entities", "deleted_at"):
        op.add_column("entities", sa.Column("deleted_at", sa.Text(), nullable=True))
    if not _has_table("audit_logs"):
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Text(), primary_key=True, nullable=False),
            sa.Column("actor_id", sa.Text(), nullable=True),
            sa.Column("action", sa.Text(), nullable=False),
            sa.Column("target_type", sa.Text(), nullable=False),
            sa.Column("target_id", sa.Text(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
        op.create_index(
            "idx_audit_logs_target",
            "audit_logs",
            ["target_type", "target_id", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS idx_requirements_fts")
    if _has_table("audit_logs"):
        op.drop_index("idx_audit_logs_target", table_name="audit_logs")
        op.drop_table("audit_logs")
    if _has_table("requirements") and _has_column("requirements", "deleted_at"):
        op.drop_column("requirements", "deleted_at")
    if _has_table("entities") and _has_column("entities", "deleted_at"):
        op.drop_column("entities", "deleted_at")
