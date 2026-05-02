"""Backward-compatible re-export.

The real implementation lives in :mod:`shared.observability.logging`. This
shim is kept so older imports such as ``from shared.logging_utils import
configure_logging`` continue to work.
"""

from shared.observability import configure_logging

__all__ = ["configure_logging"]
