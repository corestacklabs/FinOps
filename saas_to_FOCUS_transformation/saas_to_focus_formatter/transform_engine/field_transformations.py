"""
field_transformations.py
========================
Pure, stateless transformation functions for FOCUS/CUR field conversion.

Every function signature is:
    fn(value: str, row: dict | None = None, config: dict | None = None) -> str

─── Transform Registry ────────────────────────────────────────────────────────
All registered names (used inside mapper.json "transform" key):

  identity              — return value unchanged
  to_iso8601_start      — parse any date string → YYYY-MM-DDT00:00:00Z
  to_iso8601_end        — parse any date string → YYYY-MM-DDT23:59:59Z
  to_billing_period_end — first instant of the NEXT month → YYYY-MM-01T00:00:00Z
  humanize              — replace _/- with spaces, title-case
  title_case            — title-case only (no symbol replacement)
  to_uppercase          — full uppercase
  to_lowercase          — full lowercase
  strip_whitespace      — strip leading/trailing whitespace
  to_decimal            — coerce to decimal string, empty → "0"
  build_tags            — build compact JSON map from config["tag_sources"]
  static                — return config["static_value"] (value arg is ignored)
  first_non_empty       — return first non-empty value from config["sources"]

─── Extending ────────────────────────────────────────────────────────────────
To add a new transform:
  1. Define fn(value, row=None, config=None) -> str
  2. Add it to TRANSFORM_REGISTRY with a unique key
  3. Reference the key in any mapper.json "transform" field
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Date helpers (shared with generator and transformer)
# ─────────────────────────────────────────────────────────────────────────────

_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%Y-%m-%dT%H:%M:%S.%fZ",
)


def _parse_dt(value: str) -> Optional[datetime]:
    """Parse a date/datetime string into a UTC-aware datetime. Returns None on failure."""
    value = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    log.warning("Could not parse date string: %r", value)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Transform functions
# ─────────────────────────────────────────────────────────────────────────────

def identity(value: str, row: Optional[Dict] = None, config: Optional[Dict] = None) -> str:
    """Return the value unchanged."""
    return value


def to_iso8601_start(
    value: str, row: Optional[Dict] = None, config: Optional[Dict] = None
) -> str:
    """
    Convert any date string to ISO-8601 UTC start-of-day.
    "2026-03-15" → "2026-03-15T00:00:00Z"
    """
    if not value:
        return ""
    dt = _parse_dt(value)
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%dT00:00:00Z")


def to_iso8601_end(
    value: str, row: Optional[Dict] = None, config: Optional[Dict] = None
) -> str:
    """
    Convert any date string to ISO-8601 UTC end-of-day.
    "2026-03-15" → "2026-03-15T23:59:59Z"
    """
    if not value:
        return ""
    dt = _parse_dt(value)
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%dT23:59:59Z")


def to_billing_period_end(
    value: str, row: Optional[Dict] = None, config: Optional[Dict] = None
) -> str:
    """
    Return the exclusive end of the billing month — first instant of next month.
    "2026-03-15" → "2026-04-01T00:00:00Z"
    "2026-12-01" → "2027-01-01T00:00:00Z"
    """
    if not value:
        return ""
    dt = _parse_dt(value)
    if dt is None:
        return ""
    year, month = dt.year, dt.month
    if month == 12:
        year += 1
        month = 1
    else:
        month += 1
    return f"{year:04d}-{month:02d}-01T00:00:00Z"


def humanize(
    value: str, row: Optional[Dict] = None, config: Optional[Dict] = None
) -> str:
    """
    Replace underscores and hyphens with spaces, then title-case.
    "copilot_for_business"  → "Copilot For Business"
    "datadog-apm-metrics"   → "Datadog Apm Metrics"
    """
    return re.sub(r"[_\-]+", " ", value).title()


def title_case(
    value: str, row: Optional[Dict] = None, config: Optional[Dict] = None
) -> str:
    """Title-case the value without symbol replacement."""
    return value.title()


def to_uppercase(
    value: str, row: Optional[Dict] = None, config: Optional[Dict] = None
) -> str:
    return value.upper()


def to_lowercase(
    value: str, row: Optional[Dict] = None, config: Optional[Dict] = None
) -> str:
    return value.lower()


def strip_whitespace(
    value: str, row: Optional[Dict] = None, config: Optional[Dict] = None
) -> str:
    return value.strip()


def to_decimal(
    value: str, row: Optional[Dict] = None, config: Optional[Dict] = None
) -> str:
    """
    Coerce value to a decimal string. Empty or unparseable → "0".
    Strips currency symbols, commas, and whitespace before parsing.
    """
    clean = re.sub(r"[^\d.\-]", "", value.strip())
    if not clean:
        return "0"
    try:
        float(clean)
        return clean
    except ValueError:
        log.warning("Could not coerce to decimal: %r → returning '0'", value)
        return "0"


def build_tags(
    value: str, row: Optional[Dict] = None, config: Optional[Dict] = None
) -> str:
    """
    Build a compact JSON map from a list of (tag_key, source_column) pairs.

    config["tag_sources"] must be one of:
      - list of column names → tag key = column name
        e.g. ["username", "organization"] → {"username": "alice", "organization": "CoreStack-Engg"}
      - list of [tag_key, source_col] pairs → explicit key renaming
        e.g. [["user", "username"], ["org", "organization"]] → {"user": "alice", "org": "CoreStack-Engg"}

    None/empty source values are excluded from the output JSON.
    """
    if row is None or config is None:
        return "{}"
    sources = config.get("tag_sources", [])
    tags: Dict[str, str] = {}
    for item in sources:
        if isinstance(item, list) and len(item) == 2:
            tag_key, src_col = item
        elif isinstance(item, str):
            tag_key = item
            src_col = item
        else:
            continue
        # Case-insensitive column lookup
        val = _lookup_column(row, src_col)
        if val:
            tags[tag_key] = val
    return json.dumps(tags, separators=(",", ":")) if tags else "{}"


def static_value(
    value: str, row: Optional[Dict] = None, config: Optional[Dict] = None
) -> str:
    """Return config["static_value"], ignoring the source column value."""
    if config is None:
        return ""
    return str(config.get("static_value", ""))


def first_non_empty(
    value: str, row: Optional[Dict] = None, config: Optional[Dict] = None
) -> str:
    """
    Return the first non-empty value found by looking up each column in
    config["sources"] (a list of column names) from the current row.

    Falls back to the provided `value` if nothing is found.
    """
    if row is None or config is None:
        return value
    for src in config.get("sources", []):
        v = _lookup_column(row, src)
        if v:
            return v
    return value


# ─────────────────────────────────────────────────────────────────────────────
# Internal helper
# ─────────────────────────────────────────────────────────────────────────────

def _lookup_column(row: Dict[str, str], column: str) -> str:
    """
    Case-insensitive column lookup.  Also tries substring matching as a fallback
    so that "date" matches "usage_date" or "billing_date".
    """
    lower_row: Dict[str, str] = {k.lower(): v for k, v in row.items()}

    # 1. Exact lowercase match
    val = lower_row.get(column.lower(), "")
    if val.strip():
        return val.strip()

    # 2. Substring match (column name is contained in any row key)
    col_lc = column.lower()
    for key, val in lower_row.items():
        if col_lc in key and val.strip():
            return val.strip()

    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Transform Registry
# ─────────────────────────────────────────────────────────────────────────────

# Maps the string names used in mapper.json → callable transform functions.
# "static" is handled separately in the transformer (not via this registry).

TRANSFORM_REGISTRY: Dict[str, Callable] = {
    "identity":              identity,
    "to_iso8601_start":      to_iso8601_start,
    "to_iso8601_end":        to_iso8601_end,
    "to_billing_period_end": to_billing_period_end,
    "humanize":              humanize,
    "title_case":            title_case,
    "to_uppercase":          to_uppercase,
    "to_lowercase":          to_lowercase,
    "strip_whitespace":      strip_whitespace,
    "to_decimal":            to_decimal,
    "build_tags":            build_tags,
    "static":                static_value,
    "first_non_empty":       first_non_empty,
}


def apply_transform(
    transform_name: str,
    value: str,
    row: Optional[Dict[str, str]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Apply a named transform to `value`.

    Raises ValueError if transform_name is not registered.
    """
    fn = TRANSFORM_REGISTRY.get(transform_name)
    if fn is None:
        raise ValueError(
            f"Unknown transform: {transform_name!r}. "
            f"Available: {sorted(TRANSFORM_REGISTRY)}"
        )
    result = fn(value, row=row, config=config)
    return str(result) if result is not None else ""
