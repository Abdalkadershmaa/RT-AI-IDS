"""attack_logs query indexes

Adds composite B-tree indexes to accelerate newest-first alert listing and
risk-label filtered queries.

Revision ID: 0003_attack_log_query_indexes
Revises: 0002_attack_logs_model_metadata
Create Date: 2026-05-01 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_attack_log_query_indexes"
down_revision: str | None = "0002_attack_logs_model_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_attack_logs_created_at_id",
        "attack_logs",
        ["created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_attack_logs_risk_label_created_at",
        "attack_logs",
        ["risk_label", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_attack_logs_risk_label_created_at", table_name="attack_logs")
    op.drop_index("ix_attack_logs_created_at_id", table_name="attack_logs")
