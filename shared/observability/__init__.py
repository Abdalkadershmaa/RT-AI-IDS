"""Cross-service observability primitives (structured logging, correlation IDs)."""

from .logging import bind_correlation_id, configure_logging, get_correlation_id

__all__ = ["bind_correlation_id", "configure_logging", "get_correlation_id"]
