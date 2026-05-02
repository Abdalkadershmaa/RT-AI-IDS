from __future__ import annotations

from pydantic import BaseModel, Field


class AlertsListQuery(BaseModel):
    """Query string for ``GET /api/v1/alerts``.

    Supports two optional cursor parameters for mobile-friendly pagination:

    * ``since_id`` — return rows with ``id > since_id`` (delta polling; lets a
      mobile client pull only what's new since its last successful response).
    * ``before_id`` — return rows with ``id < before_id`` (infinite-scroll into
      older history without re-downloading the head of the list).

    * ``risk_label`` — exact-match filter for a risk bucket like ``high``.

    The two cursors are mutually exclusive. When neither is supplied the endpoint
    returns the newest ``limit`` rows (legacy behaviour, unchanged).
    """

    limit: int = Field(default=50, ge=1, le=500)
    since_id: int | None = Field(default=None, ge=0)
    before_id: int | None = Field(default=None, ge=1)
    risk_label: str | None = Field(default=None, max_length=32)
