"""Compact JSON diagnostics for tracing one Grill Gate frame through monitoring and persistence."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime


def log_diagnostic(logger: logging.Logger, event: str, *, level: int = logging.INFO,
                   category: str = "MONITORING", **fields) -> None:
    """Write a single-line structured record. Frame-level records are emitted only at DEBUG."""
    if not logger.isEnabledFor(level):
        return
    payload = {"component": "grill_gate", "diagnostic": event, **fields}
    logger.log(level, "[GRILL_GATE][%s] %s", category.upper(),
               json.dumps(payload, default=_json_default, separators=(",", ":")))


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (tuple, set)):
        return list(value)
    if hasattr(value, "item"):
        return value.item()
    return str(value)
