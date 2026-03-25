#!/usr/bin/env python3
"""
copilot_to_focus_cur.py
=======================
Standalone converter: GitHub Copilot usage report → AWS FOCUS / CUR-compliant CSV.

Architecture (three-tier value resolution per SKILL_saas_to_cur_converter.md):
  Tier 1 — CLI parameters            (always win)
  Tier 2 — TOOL_FIELD_MAPS["copilot"] (per-row lambdas / column aliases)
  Tier 3 — GENERIC_COLUMN_HEURISTICS  (fuzzy column-name fallback)

Input:
  usage_report.csv  — GitHub Copilot billing export
  saas_template.csv — FOCUS/CUR schema template (row 0 = column names)

Output:
  output_cur.csv    — FOCUS-compliant file, one row per input row

Usage:
  python3 copilot_to_focus_cur.py \\
      --usage_report  usage_report.csv \\
      --cur_template  saas_template.csv \\
      --output        output_cur.csv \\
      --provider_name "GitHub" \\
      --billing_account_id   "your-org-id" \\
      --billing_account_name "Your Org Name"

Optional flags:
  --billing_currency  USD        (default: USD)
  --region_name       "Global"   (default: empty)
  --tag_key           env        inject extra tag into every row
  --tag_value         prod
"""

import argparse
import csv
import json
import logging
import sys
from calendar import monthrange
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-5s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Date helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_date(value: str) -> Optional[datetime]:
    """Parse a date/datetime string into a datetime object (UTC)."""
    value = value.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%d-%m-%Y",
    ):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    log.warning("WARNING  Could not parse date: %r", value)
    return None


def _iso_date(value: str, end_of_day: bool = False) -> str:
    """
    Convert a date string to ISO-8601 UTC.

    _iso_date("2026-03-01")              → "2026-03-01T00:00:00Z"
    _iso_date("2026-03-01", True)        → "2026-03-01T23:59:59Z"
    _iso_date("2026-03-01T14:30:00Z")    → "2026-03-01T00:00:00Z"  (strips time)
    """
    dt = _parse_date(value)
    if dt is None:
        return ""
    if end_of_day:
        return dt.strftime("%Y-%m-%dT23:59:59Z")
    return dt.strftime("%Y-%m-%dT00:00:00Z")


def _billing_period_end(value: str) -> str:
    """
    Return the exclusive end of the billing month (= first instant of next month).

    _billing_period_end("2026-03-01")  → "2026-04-01T00:00:00Z"
    _billing_period_end("2026-12-15")  → "2027-01-01T00:00:00Z"
    """
    dt = _parse_date(value)
    if dt is None:
        return ""
    # Advance to first day of next month
    year, month = dt.year, dt.month
    if month == 12:
        year += 1
        month = 1
    else:
        month += 1
    return f"{year:04d}-{month:02d}-01T00:00:00Z"


# ─────────────────────────────────────────────────────────────────────────────
# Column picker helper
# ─────────────────────────────────────────────────────────────────────────────

def _first_col(row: Dict[str, str], *candidates: str) -> Optional[str]:
    """
    Return the value of the first non-empty column found in *candidates*.
    Matching is case-insensitive and also checks if the candidate is a
    substring of any row key (handles slight naming variations).
    """
    lower_row = {k.lower(): v for k, v in row.items()}
    for candidate in candidates:
        # Exact lowercase match first
        val = lower_row.get(candidate.lower())
        if val is not None and val.strip():
            return val.strip()
        # Substring match (e.g. "date" matches "usage_date")
        for key, val in lower_row.items():
            if candidate.lower() in key and val.strip():
                return val.strip()
    return None


# ─────────────────────────────────────────────────────────────────────────────
# TOOL_FIELD_MAPS
# Tier 2 — tool-specific column mappings.
# Each value is either:
#   str      → source column name (direct copy)
#   callable → lambda(row) → str
# ─────────────────────────────────────────────────────────────────────────────

TOOL_FIELD_MAPS: Dict[str, Dict[str, Any]] = {

    # ── GitHub Copilot ────────────────────────────────────────────────────────
    # Input columns (from usage_report.csv):
    #   date, product, sku, quantity, unit_type, applied_cost_per_quantity,
    #   gross_amount, discount_amount, net_amount,
    #   username, organization, repository, workflow_path, cost_center_name
    # ─────────────────────────────────────────────────────────────────────────
    "copilot": {

        # ── Billing period ────────────────────────────────────────────────────
        "BillingPeriodStart": lambda r: _iso_date(
            _first_col(r, "date") or "", end_of_day=False
        ),
        "BillingPeriodEnd": lambda r: _billing_period_end(
            _first_col(r, "date") or ""
        ),

        # ── Charge period (daily granularity) ─────────────────────────────────
        "ChargePeriodStart": lambda r: _iso_date(
            _first_col(r, "date") or "", end_of_day=False
        ),
        "ChargePeriodEnd": lambda r: _iso_date(
            _first_col(r, "date") or "", end_of_day=True
        ),

        # ── Service identity ──────────────────────────────────────────────────
        # ServiceName: humanize the 'product' column  ("copilot" → "Copilot")
        "ServiceName": lambda r: (
            _first_col(r, "product") or "Copilot"
        ).replace("_", " ").title(),

        # SkuId: the 'sku' column  (e.g. "copilot_for_business")
        "SkuId": lambda r: _first_col(r, "sku") or "",

        # UsageType: humanize the sku  ("copilot_for_business" → "Copilot For Business")
        "UsageType": lambda r: (
            _first_col(r, "sku") or ""
        ).replace("_", " ").title(),

        # ProductFamily: static label for all Copilot charges
        "ProductFamily": lambda r: "Developer Tools",

        # ChargeCategory / ChargeFrequency are static for Copilot billing
        "ChargeCategory": lambda r: "Usage",
        "ChargeFrequency": lambda r: "Monthly",

        # ── Quantities ────────────────────────────────────────────────────────
        "ConsumedQuantity": lambda r: _first_col(r, "quantity") or "",
        "ConsumedUnit":     lambda r: _first_col(r, "unit_type") or "Units",

        # ── Costs ─────────────────────────────────────────────────────────────
        # net_amount  → what's actually invoiced (BilledCost / EffectiveCost)
        # gross_amount → list price before discounts (ListCost)
        # Note: copilot_premium_request rows have net_amount=0 (fully discounted)
        "BilledCost":    lambda r: _first_col(r, "net_amount") or "0",
        "EffectiveCost": lambda r: _first_col(r, "net_amount") or "0",
        "ListCost":      lambda r: _first_col(r, "gross_amount") or (
            _first_col(r, "net_amount") or "0"
        ),

        # ── Resource identification ───────────────────────────────────────────
        # ResourceId / ResourceName: prefer username, fall back to organization
        "ResourceId": lambda r: (
            _first_col(r, "username") or _first_col(r, "organization") or ""
        ),
        "ResourceName": lambda r: (
            _first_col(r, "username") or _first_col(r, "organization") or ""
        ),

        # ── Tags (JSON map) ───────────────────────────────────────────────────
        "Tags": lambda r: json.dumps(
            {k: v for k, v in {
                "username":       _first_col(r, "username"),
                "organization":   _first_col(r, "organization"),
                "repository":     _first_col(r, "repository"),
                "workflow_path":  _first_col(r, "workflow_path"),
                "cost_center":    _first_col(r, "cost_center_name"),
            }.items() if v},  # exclude None / empty
            separators=(",", ":"),
        ),

        # ── Region ────────────────────────────────────────────────────────────
        # Copilot reports have no region column; let CLI --region_name inject it.
        # If none supplied, leave blank.
        "RegionName": lambda r: "",
    },

    # ── Generic fallback — empty map (relies entirely on heuristics) ──────────
    "generic": {},
}


# ─────────────────────────────────────────────────────────────────────────────
# GENERIC_COLUMN_HEURISTICS
# Tier 3 — fuzzy column-name fallback when a CUR column is not in the tool map.
# ─────────────────────────────────────────────────────────────────────────────

GENERIC_COLUMN_HEURISTICS: Dict[str, List[str]] = {
    "ServiceName":       ["service_name", "service", "product", "tool"],
    "SkuId":             ["sku_id", "sku", "product_id"],
    "UsageType":         ["usage_type", "type", "charge_type"],
    "ProductFamily":     ["product_family", "family", "category"],
    "ConsumedQuantity":  ["quantity", "usage_quantity", "amount", "count"],
    "ConsumedUnit":      ["unit_type", "unit", "measure"],
    "BilledCost":        ["net_amount", "billed_cost", "cost", "total_cost"],
    "EffectiveCost":     ["effective_cost", "net_amount", "cost"],
    "ListCost":          ["list_cost", "gross_amount", "list_price"],
    "ResourceId":        ["resource_id", "id", "resource"],
    "ResourceName":      ["resource_name", "name", "instance"],
    "RegionName":        ["region_name", "region", "location"],
    "Tags":              ["tags", "labels", "metadata"],
    "ChargePeriodStart": ["charge_period_start", "start_date", "date", "period_start"],
    "ChargePeriodEnd":   ["charge_period_end", "end_date", "period_end"],
    "BillingPeriodStart":["billing_period_start", "billing_start", "date"],
    "BillingPeriodEnd":  ["billing_period_end", "billing_end"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Tool detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_tool(rows: List[Dict[str, str]], filename: str) -> str:
    """
    Identify which TOOL_FIELD_MAPS key to use.

    Checks (in order):
      1. product / tool / service column value in the first data row
      2. The usage report filename (lowercased)

    Returns the matching key, or "generic" if nothing matches.
    """
    # Candidate column names that might hold a tool/product identifier
    PRODUCT_COLS = ("product", "tool", "service", "product_name")

    if rows:
        first = rows[0]
        for col in PRODUCT_COLS:
            value = _first_col(first, col) or ""
            value_lc = value.lower()
            for key in TOOL_FIELD_MAPS:
                if key == "generic":
                    continue
                if key in value_lc:
                    log.info(
                        "Detected tool from data: %r  →  map key %r", value, key
                    )
                    return key

    # Filename fallback
    fname_lc = filename.lower()
    for key in TOOL_FIELD_MAPS:
        if key == "generic":
            continue
        if key in fname_lc:
            log.info("Detected tool from filename: %r  →  map key %r", filename, key)
            return key

    log.warning("WARNING  Could not detect tool — falling back to 'generic' map")
    return "generic"


# ─────────────────────────────────────────────────────────────────────────────
# Value resolution (three-tier)
# ─────────────────────────────────────────────────────────────────────────────

def resolve_value(
    cur_col: str,
    row: Dict[str, str],
    tool_map: Dict[str, Any],
    cli_params: Dict[str, str],
) -> str:
    """
    Resolve the value for a single CUR column using three-tier priority:

      Tier 1 — CLI parameters (always win)
      Tier 2 — Tool-specific map (direct column alias or lambda)
      Tier 3 — Generic heuristics (fuzzy column-name matching)
    """
    # Tier 1 — CLI
    if cur_col in cli_params and cli_params[cur_col]:
        return cli_params[cur_col]

    # Tier 2 — Tool map
    if cur_col in tool_map:
        mapping = tool_map[cur_col]
        if callable(mapping):
            result = mapping(row)
            return str(result) if result is not None else ""
        elif isinstance(mapping, str):
            val = _first_col(row, mapping)
            return val or ""
        return str(mapping)

    # Tier 3 — Generic heuristics
    if cur_col in GENERIC_COLUMN_HEURISTICS:
        for candidate in GENERIC_COLUMN_HEURISTICS[cur_col]:
            val = _first_col(row, candidate)
            if val:
                return val

    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Extra tag injection (--tag_key / --tag_value)
# ─────────────────────────────────────────────────────────────────────────────

def apply_extra_tag(
    out_row: Dict[str, str],
    tag_key: str,
    tag_value: str,
) -> None:
    """
    Inject an additional key-value pair into the Tags field of out_row.
    Handles both empty Tags and existing JSON tags.
    Modifies out_row in-place.
    """
    if not tag_key:
        return
    existing = out_row.get("Tags", "")
    try:
        tags = json.loads(existing) if existing else {}
    except json.JSONDecodeError:
        tags = {}
    tags[tag_key] = tag_value
    out_row["Tags"] = json.dumps(tags, separators=(",", ":"))


# ─────────────────────────────────────────────────────────────────────────────
# Template reader
# ─────────────────────────────────────────────────────────────────────────────

def read_template_columns(template_path: str) -> List[str]:
    """
    Read the CUR/FOCUS template and return column names from row 0.
    Rows 1-4 are metadata and are ignored.
    """
    log.info("Reading CUR template: %s", template_path)
    with open(template_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        columns = next(reader)  # row 0 = column names
    columns = [c.strip() for c in columns]
    log.info("CUR schema has %d columns: %s", len(columns), columns)
    return columns


# ─────────────────────────────────────────────────────────────────────────────
# Main conversion engine
# ─────────────────────────────────────────────────────────────────────────────

def convert(
    usage_path: str,
    template_path: str,
    output_path: str,
    cli_params: Dict[str, str],
    tag_key: str = "",
    tag_value: str = "",
    chunk_size: int = 500,
) -> int:
    """
    Convert a SaaS usage report CSV to FOCUS/CUR format.

    Returns the number of data rows written.
    """
    # 1. Read CUR schema from template (row 0 only)
    cur_columns = read_template_columns(template_path)

    # 2. Load usage report into memory (needed for tool detection sampling)
    log.info("Sampling usage report to detect tool: %s", usage_path)
    with open(usage_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        log.warning("WARNING  Usage report is empty — no rows to convert.")
        return 0

    log.info("Usage report loaded: %d data rows", len(rows))

    # 3. Detect tool
    import os
    fname = os.path.basename(usage_path)
    tool_key = detect_tool(rows, fname)
    tool_map = TOOL_FIELD_MAPS.get(tool_key, {})
    log.info("Using tool map: %r (%d explicit mappings)", tool_key, len(tool_map))

    # 4. Stream-write the output
    written = 0
    with open(output_path, "w", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=cur_columns, extrasaction="ignore")
        writer.writeheader()

        for i, row in enumerate(rows):
            out_row: Dict[str, str] = {}
            for col in cur_columns:
                out_row[col] = resolve_value(col, row, tool_map, cli_params)

            # Extra tag injection
            if tag_key:
                apply_extra_tag(out_row, tag_key, tag_value)

            writer.writerow(out_row)
            written += 1

            if written % chunk_size == 0:
                log.info("  … wrote %d rows so far", written)

    log.info("Conversion complete. %d data rows written to: %s", written, output_path)
    return written


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Convert GitHub Copilot usage report → AWS FOCUS / CUR-compliant CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Minimal (defaults: USD, no region)
  python3 copilot_to_focus_cur.py \\
      --usage_report usage_report.csv \\
      --cur_template saas_template.csv \\
      --output       output_cur.csv \\
      --provider_name "GitHub" \\
      --billing_account_id "org-CoreStack-Engg" \\
      --billing_account_name "CoreStack Engineering"

  # With region and extra tag
  python3 copilot_to_focus_cur.py \\
      --usage_report usage_report.csv \\
      --cur_template saas_template.csv \\
      --output       output_cur.csv \\
      --provider_name "GitHub" \\
      --billing_account_id "org-CoreStack-Engg" \\
      --billing_account_name "CoreStack Engineering" \\
      --region_name "Global" \\
      --tag_key env --tag_value prod
        """,
    )

    # Required file paths
    io_grp = p.add_argument_group("I/O files")
    io_grp.add_argument(
        "--usage_report", default="usage_report.csv",
        help="Path to the SaaS usage report CSV (default: usage_report.csv).",
    )
    io_grp.add_argument(
        "--cur_template", default="saas_template.csv",
        help="Path to the FOCUS/CUR schema template CSV (default: saas_template.csv).",
    )
    io_grp.add_argument(
        "--output", default="output_cur.csv",
        help="Path to write the FOCUS-compliant output CSV (default: output_cur.csv).",
    )

    # Required billing metadata (Tier 1 CLI overrides)
    req_grp = p.add_argument_group("Required billing metadata")
    req_grp.add_argument(
        "--provider_name", default="GitHub",
        help="SaaS provider name (e.g. GitHub). Default: GitHub.",
    )
    req_grp.add_argument(
        "--billing_account_id", default="",
        help="Provider-assigned billing account ID.",
    )
    req_grp.add_argument(
        "--billing_account_name", default="",
        help="Provider-assigned billing account name.",
    )

    # Optional billing metadata
    opt_grp = p.add_argument_group("Optional billing metadata")
    opt_grp.add_argument(
        "--billing_currency", default="USD",
        help="Currency code (default: USD).",
    )
    opt_grp.add_argument(
        "--region_name", default="",
        help="Geographic region (e.g. 'Global'). Leave empty if not applicable.",
    )
    opt_grp.add_argument(
        "--charge_category", default="Usage",
        help="Charge category (default: Usage).",
    )
    opt_grp.add_argument(
        "--charge_frequency", default="Monthly",
        help="Charge frequency (default: Monthly).",
    )

    # Extra tag injection
    tag_grp = p.add_argument_group("Extra tag injection")
    tag_grp.add_argument(
        "--tag_key", default="",
        help="Tag key to inject into every output row's Tags field.",
    )
    tag_grp.add_argument(
        "--tag_value", default="",
        help="Tag value paired with --tag_key.",
    )

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Build the Tier 1 CLI parameter dict (only non-empty values are included,
    # so they don't accidentally overwrite tool-map lambdas with empty strings)
    cli_params: Dict[str, str] = {}

    if args.provider_name:
        cli_params["ProviderName"] = args.provider_name
    if args.billing_account_id:
        cli_params["BillingAccountId"] = args.billing_account_id
    if args.billing_account_name:
        cli_params["BillingAccountName"] = args.billing_account_name
    if args.billing_currency:
        cli_params["BillingCurrency"] = args.billing_currency
    if args.region_name:
        cli_params["RegionName"] = args.region_name
    if args.charge_category:
        cli_params["ChargeCategory"] = args.charge_category
    if args.charge_frequency:
        cli_params["ChargeFrequency"] = args.charge_frequency

    log.info("CLI params: %s", cli_params)

    convert(
        usage_path=args.usage_report,
        template_path=args.cur_template,
        output_path=args.output,
        cli_params=cli_params,
        tag_key=args.tag_key,
        tag_value=args.tag_value,
    )


if __name__ == "__main__":
    main()
