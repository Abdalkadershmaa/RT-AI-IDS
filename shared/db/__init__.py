"""Flask-free database layer shared by every service."""

from .engine import dispose_engine, get_engine, get_sessionmaker, session_scope
from .models import AttackLog, AuditLog, Base, severity_for

__all__ = [
    "AttackLog",
    "AuditLog",
    "Base",
    "dispose_engine",
    "get_engine",
    "get_sessionmaker",
    "session_scope",
    "severity_for",
]
