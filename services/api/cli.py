"""Flask CLI commands for operator workflows.

Every command is registered under the default Flask CLI group so operators
run them as ``flask <command>`` from inside a container or a host shell
configured with the right environment variables.

Currently provides:

* ``flask retention-prune`` — delete alerts older than
  ``ATTACK_LOG_RETENTION_DAYS``. Designed to be wired up to a cron / systemd
  timer; safe to run repeatedly.
"""

from __future__ import annotations

import click
from flask import Flask

from shared.config import get_settings

from .retention import prune_old_alerts


def register_cli(app: Flask) -> None:
    """Attach all CLI commands to ``app``."""

    @app.cli.command("retention-prune")
    @click.option(
        "--days",
        type=int,
        default=None,
        help=(
            "Override ATTACK_LOG_RETENTION_DAYS for this invocation. "
            "Use 0 to disable pruning."
        ),
    )
    def _retention_prune(days: int | None) -> None:
        """Delete alerts older than the configured retention window."""

        settings = get_settings()
        retention = settings.attack_log_retention_days if days is None else days
        deleted = prune_old_alerts(retention)
        if retention <= 0:
            click.echo("Retention pruning disabled (retention_days <= 0). No rows deleted.")
        else:
            click.echo(f"Deleted {deleted} alert(s) older than {retention} day(s).")
