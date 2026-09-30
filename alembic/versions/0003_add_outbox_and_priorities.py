"""add outbox and priorities

Revision ID: 0003_add_outbox_and_priorities
Revises: 0002_add_idempotency_and_tracing
Create Date: 2026-09-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_add_outbox_and_priorities"
down_revision = "0002_add_idempotency_and_tracing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Adding priority and execution_token to jobs
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("priority", sa.Integer(), server_default="5", nullable=False))
        batch_op.add_column(sa.Column("execution_token", sa.String(length=64), nullable=True))
        batch_op.create_index("ix_jobs_priority", ["priority"])

    # Create outbox_events table
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"])
    op.create_index("ix_outbox_events_status", "outbox_events", ["status"])
    op.create_index("ix_outbox_events_created_at", "outbox_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_outbox_events_created_at", table_name="outbox_events")
    op.drop_index("ix_outbox_events_status", table_name="outbox_events")
    op.drop_index("ix_outbox_events_event_type", table_name="outbox_events")
    op.drop_table("outbox_events")

    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_index("ix_jobs_priority")
        batch_op.drop_column("execution_token")
        batch_op.drop_column("priority")
