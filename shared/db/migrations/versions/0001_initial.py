"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-26 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attack_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("flow_id", sa.String(length=128), nullable=False),
        sa.Column("source_ip", sa.String(length=64), nullable=False),
        sa.Column("source_port", sa.Integer(), nullable=False),
        sa.Column("destination_ip", sa.String(length=64), nullable=False),
        sa.Column("destination_port", sa.Integer(), nullable=False),
        sa.Column("protocol", sa.String(length=16), nullable=False),
        sa.Column("classification", sa.String(length=64), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("risk_label", sa.String(length=32), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("rationale", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_attack_logs_flow_id", "attack_logs", ["flow_id"])
    op.create_index("ix_attack_logs_source_ip", "attack_logs", ["source_ip"])
    op.create_index("ix_attack_logs_destination_ip", "attack_logs", ["destination_ip"])
    op.create_index("ix_attack_logs_classification", "attack_logs", ["classification"])
    op.create_index("ix_attack_logs_risk_label", "attack_logs", ["risk_label"])
    op.create_index("ix_attack_logs_created_at", "attack_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_attack_logs_created_at", table_name="attack_logs")
    op.drop_index("ix_attack_logs_risk_label", table_name="attack_logs")
    op.drop_index("ix_attack_logs_classification", table_name="attack_logs")
    op.drop_index("ix_attack_logs_destination_ip", table_name="attack_logs")
    op.drop_index("ix_attack_logs_source_ip", table_name="attack_logs")
    op.drop_index("ix_attack_logs_flow_id", table_name="attack_logs")
    op.drop_table("attack_logs")
