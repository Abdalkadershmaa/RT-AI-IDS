"""Attack-log retention helpers.

The detection pipeline writes one row per inference, so the ``attack_logs``
table grows roughly linearly with traffic. To prevent unbounded growth (and
to give operators a knob for compliance windows), this module exposes a
single function — :func:`prune_old_alerts` — that deletes rows older than
``ATTACK_LOG_RETENTION_DAYS``.

The function is invoked by the ``retention-prune`` Flask CLI command (see
:mod:`services.api.cli`) and can also be scheduled directly from cron /
systemd timers / Kubernetes CronJobs without a running web process.

A retention of ``0`` (the explicit "keep forever" sentinel) makes
:func:`prune_old_alerts` a no-op, which is useful for forensic deployments
where alerts must be retained indefinitely.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from shared.db import AttackLog, session_scope

logger = logging.getLogger(__name__)


def prune_old_alerts(retention_days: int) -> int:
    """Delete alerts older than ``retention_days`` and return the row count.

    Parameters
    ----------
    retention_days:
        Window in days; rows whose ``created_at`` is strictly older than
        ``now - retention_days`` are deleted. Values ``<= 0`` are treated as
        "retain forever" and the function returns ``0`` without touching
        the database.
    """

    if retention_days <= 0:
        logger.info("retention_prune_disabled retention_days=%d", retention_days)
        return 0

    cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
    with session_scope() as session:
        result = session.execute(delete(AttackLog).where(AttackLog.created_at < cutoff))
        deleted = int(result.rowcount or 0)
    logger.info(
        "retention_prune_completed retention_days=%d cutoff=%s deleted=%d",
        retention_days,
        cutoff.isoformat(),
        deleted,
    )
    return deleted
