"""attack_logs: model_version + model_dataset columns

Adds two nullable columns so each persisted alert records the model build
that produced it. Existing rows stay ``NULL`` (back-fill is intentionally
skipped — historical alerts predate the metadata).

Revision ID: 0002_attack_logs_model_metadata
Revises: 0001_initial
Create Date: 2026-04-28 17:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_attack_logs_model_metadata"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "attack_logs",
        sa.Column("model_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "attack_logs",
        sa.Column("model_dataset", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("attack_logs", "model_dataset")
    op.drop_column("attack_logs", "model_version")
