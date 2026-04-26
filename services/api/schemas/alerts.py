from __future__ import annotations

from pydantic import BaseModel, Field


class AlertsListQuery(BaseModel):
    """Query string for ``GET /api/v1/alerts``."""

    limit: int = Field(default=50, ge=1, le=500)
