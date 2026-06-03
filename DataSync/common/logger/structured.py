"""Small helpers for structured, bounded DataSync logs."""

from __future__ import annotations

import logging
from typing import Any, Mapping

DEFAULT_MAX_VALUE_CHARS = 500
DEFAULT_MAX_ITEMS = 5
DEFAULT_MAX_DEPTH = 2


def _configured_limits() -> tuple[int, int]:
    try:
        from core.settings import settings

        max_value_chars = int(settings.observability.log_max_value_chars)
        max_items = int(settings.observability.log_sample_limit)
    except Exception:
        return DEFAULT_MAX_VALUE_CHARS, DEFAULT_MAX_ITEMS
    return max(80, max_value_chars), max(0, max_items)


def sanitize_log_value(
    value: Any,
    *,
    max_value_chars: int = DEFAULT_MAX_VALUE_CHARS,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> Any:
    """Return a compact value that is safe to attach to logs.

    The goal is not to preserve full payloads; detailed bad data belongs in
    dead-letter/job detail records, while logs should remain bounded.
    """
    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        if len(value) <= max_value_chars:
            return value
        return f"{value[:max_value_chars]}...<truncated:{len(value)}>"

    if max_depth <= 0:
        return f"<{type(value).__name__}>"

    if isinstance(value, Mapping):
        items = list(value.items())
        normalized = {
            str(key): sanitize_log_value(
                item_value,
                max_value_chars=max_value_chars,
                max_items=max_items,
                max_depth=max_depth - 1,
            )
            for key, item_value in items[:max_items]
        }
        if len(items) > max_items:
            normalized["_truncated_items"] = len(items) - max_items
        return normalized

    if isinstance(value, (list, tuple, set, frozenset)):
        values = list(value)
        normalized = [
            sanitize_log_value(
                item,
                max_value_chars=max_value_chars,
                max_items=max_items,
                max_depth=max_depth - 1,
            )
            for item in values[:max_items]
        ]
        if len(values) > max_items:
            normalized.append({"_truncated_items": len(values) - max_items})
        return normalized

    text = str(value)
    if len(text) <= max_value_chars:
        return text
    return f"{text[:max_value_chars]}...<truncated:{len(text)}>"


def build_log_extra(
    **fields: Any,
) -> dict:
    """Build logging ``extra`` with bounded ``extra_data`` fields."""
    max_value_chars, max_items = _configured_limits()
    return {
        "extra_data": {
            key: sanitize_log_value(
                value,
                max_value_chars=max_value_chars,
                max_items=max_items,
            )
            for key, value in fields.items()
            if value is not None
        }
    }


def format_log_fields(**fields: Any) -> str:
    """Format stable key-value fields for plain text Docker logs."""
    parts = []
    for key, value in fields.items():
        if value is None:
            continue
        compact = sanitize_log_value(value, max_value_chars=120, max_items=3, max_depth=1)
        parts.append(f"{key}={compact}")
    return " ".join(parts)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    /,
    **fields: Any,
) -> None:
    """Emit a compact text message plus structured ``extra_data`` fields."""
    message = event
    text_fields = format_log_fields(**fields)
    if text_fields:
        message = f"{message} {text_fields}"
    logger.log(level, message, extra=build_log_extra(event=event, **fields))
