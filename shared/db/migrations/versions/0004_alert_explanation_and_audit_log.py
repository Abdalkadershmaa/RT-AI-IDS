"""attack_logs.explanation column + audit_logs table

Adds a JSON column on ``attack_logs`` so the LIME explanation produced by
the inference worker can be persisted alongside the alert and surfaced to
clients (Predict page, dashboard alert detail, Chrome extension). The
column defaults to an empty list so existing rows that predate end-to-end
LIME wiring keep working without a back-fill.

Also adds a new ``audit_logs`` table that records every privileged
action (admin endpoints, tenant lifecycle in Phase 3) on an
append-only timeline. Required for SOX/HIPAA-class deployments.

Revision ID: 0004_alert_explanation_and_audit_log
Revises: 0003_attack_log_query_indexes
Create Date: 2026-04-26 07:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_alert_explanation_and_audit_log"
down_revision: str | None = "0003_attack_log_query_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # JSON is the portable choice (works on both Postgres + SQLite test runs).
    # On Postgres it stores as JSONB-equivalent through SQLAlchemy's JSON type;
    # we don't reach for a JSONB-specific column type so the same migration
    # runs cleanly under the SQLite test harness used by ``pytest`` in CI.
    op.add_column(
        "attack_logs",
        sa.Column(
            "explanation",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("actor", sa.String(255), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target", sa.String(255), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_audit_logs_ts", "audit_logs", ["ts"], unique=False)
    op.create_index("ix_audit_logs_actor", "audit_logs", ["actor"], unique=False)
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor", table_name="audit_logs")
    op.drop_index("ix_audit_logs_ts", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_column("attack_logs", "explanation")
