"""add idempotency and tracing

Revision ID: 0002_add_idempotency_and_tracing
Revises: 0001_initial
Create Date: 2026-07-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_add_idempotency_and_tracing"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Adding columns to jobs
    op.add_column("jobs", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.add_column("jobs", sa.Column("correlation_id", sa.String(length=128), nullable=True))
    
    # Adding unique constraint to jobs
    # Using batch_alter_table for SQLite compatibility
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.create_unique_constraint("uq_job_owner_idempotency", ["owner_id", "idempotency_key"])

    # Adding columns to job_attempts
    op.add_column("job_attempts", sa.Column("correlation_id", sa.String(length=128), nullable=True))


def downgrade() -> None:
    # Downgrade job_attempts
    with op.batch_alter_table("job_attempts", schema=None) as batch_op:
        batch_op.drop_column("correlation_id")
        
    # Downgrade jobs
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_constraint("uq_job_owner_idempotency", type_="unique")
        batch_op.drop_column("correlation_id")
        batch_op.drop_column("idempotency_key")
