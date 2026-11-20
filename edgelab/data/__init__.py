"""Data layer: provider clients, Parquet cache, corporate-action adjustment, quality checks.

The first block re-exports the original in-memory Panel container and validators so older code
(`from edgelab.data import Panel`) keeps working.
"""
from .panel import (  # noqa: F401
    DataGapError, Finding, Panel, asof_fundamentals, audit_news_timestamps, audit_survivorship,
    audit_universe_pit, trading_calendar_check, validate_panel,
)
