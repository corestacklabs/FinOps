"""
generate_mapper.py
==================
Skill-based Mapper Generator.

Inspects any SaaS usage export CSV, understands its columns semantically,
then auto-generates a FOCUS/CUR mapper.json that drives the transformation
engine — with zero hardcoded vendor logic.

─── How it works ─────────────────────────────────────────────────────────────

  Step 1  Read the input CSV headers (and optionally a few data rows)
  Step 2  Load the FOCUS schema (focus_schema.json)
  Step 3  For each FOCUS column, score every source column against a set of
          semantic pattern groups
  Step 4  Pick the best match (highest score), assign the appropriate transform
  Step 5  Handle special cases:
            - Tags       → gather all contextual columns into tag_sources
            - Dates      → detect format and assign correct date transform
            - Costs      → classify as BilledCost / ListCost / EffectiveCost
            - Static     → ProviderName / ProductFamily inferred from data
  Step 6  Emit mapper.json

─── Semantic pattern groups ───────────────────────────────────────────────────

  Each FOCUS column has a list of (pattern, score, transform) tuples.
  A source column is scored by substring matching (case-insensitive).
  The highest-scoring match wins.  Ties are broken by specificity (score).

─── Usage ────────────────────────────────────────────────────────────────────

  python3 mapper_generator/generate_mapper.py \
      --usage_report  usage_report.csv \
      --schema        schemas/focus_schema.json \
      --output        mappers/my_tool_mapper.json \
      --tool_name     "my_tool" \
      --provider_name "My Provider" \
      [--product_family "Developer Tools"] \
      [--currency USD]

  Or auto-infer tool_name from the usage report filename:
      python3 mapper_generator/generate_mapper.py \
          --usage_report  copilot_usage_march.csv \
          --schema        schemas/focus_schema.json \
          --output        mappers/copilot_mapper.json
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-5s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Semantic pattern catalogue
# ─────────────────────────────────────────────────────────────────────────────
#
# Structure: COLUMN_PATTERNS[focus_col] = list of (source_pattern, score, transform)
#
#   source_pattern : substring (case-insensitive) to match against source column names
#   score          : higher = more specific / confident match
#   transform      : transform key to assign if this pattern wins
#
# Scoring rules:
#   ≥ 10 : almost certainly the right column
#   5-9  : likely, but could be coincidental
#   1-4  : loose / fallback match
#
# ─────────────────────────────────────────────────────────────────────────────

COLUMN_PATTERNS: Dict[str, List[Tuple[str, int, str]]] = {

    # ── Date / period columns ─────────────────────────────────────────────────
    "BillingPeriodStart": [
        ("billing_period_start", 10, "to_iso8601_start"),
        ("billing_start",         9, "to_iso8601_start"),
        ("period_start",          8, "to_iso8601_start"),
        ("start_date",            7, "to_iso8601_start"),
        ("usage_date",            6, "to_iso8601_start"),
        ("date",                  5, "to_iso8601_start"),
        ("day",                   4, "to_iso8601_start"),
        ("timestamp",             3, "to_iso8601_start"),
        ("created_at",            2, "to_iso8601_start"),
        ("time",                  1, "to_iso8601_start"),
    ],
    "BillingPeriodEnd": [
        ("billing_period_end",  10, "to_billing_period_end"),
        ("billing_end",          9, "to_billing_period_end"),
        ("period_end",           8, "to_billing_period_end"),
        ("end_date",             7, "to_billing_period_end"),
        ("usage_date",           5, "to_billing_period_end"),
        ("date",                 4, "to_billing_period_end"),
        ("day",                  3, "to_billing_period_end"),
        ("timestamp",            2, "to_billing_period_end"),
    ],
    "ChargePeriodStart": [
        ("charge_period_start", 10, "to_iso8601_start"),
        ("charge_start",         9, "to_iso8601_start"),
        ("period_start",         8, "to_iso8601_start"),
        ("start_date",           7, "to_iso8601_start"),
        ("usage_date",           6, "to_iso8601_start"),
        ("date",                 5, "to_iso8601_start"),
        ("day",                  4, "to_iso8601_start"),
        ("timestamp",            3, "to_iso8601_start"),
        ("created_at",           2, "to_iso8601_start"),
    ],
    "ChargePeriodEnd": [
        ("charge_period_end",  10, "to_iso8601_end"),
        ("charge_end",          9, "to_iso8601_end"),
        ("period_end",          8, "to_iso8601_end"),
        ("end_date",            7, "to_iso8601_end"),
        ("usage_date",          6, "to_iso8601_end"),
        ("date",                5, "to_iso8601_end"),
        ("day",                 4, "to_iso8601_end"),
        ("timestamp",           3, "to_iso8601_end"),
    ],

    # ── Cost columns ──────────────────────────────────────────────────────────
    "BilledCost": [
        ("net_amount",      10, "identity"),
        ("billed_cost",      9, "identity"),
        ("invoice_amount",   8, "identity"),
        ("charged_amount",   8, "identity"),
        ("amount_due",       7, "identity"),
        ("total_cost",       6, "identity"),
        ("cost_usd",         5, "identity"),
        ("cost",             4, "identity"),
        ("amount",           3, "identity"),
        ("price",            2, "identity"),
    ],
    "EffectiveCost": [
        ("net_amount",       10, "identity"),
        ("effective_cost",    9, "identity"),
        ("amortized_cost",    8, "identity"),
        ("billed_cost",       7, "identity"),
        ("total_cost",        5, "identity"),
        ("cost",              3, "identity"),
    ],
    "ListCost": [
        ("gross_amount",     10, "identity"),
        ("list_cost",         9, "identity"),
        ("list_price",        9, "identity"),
        ("retail_cost",       8, "identity"),
        ("undiscounted_cost", 8, "identity"),
        ("mrp",               7, "identity"),
        ("total_cost",        5, "identity"),
        ("cost",              2, "identity"),
    ],

    # ── Service / product columns ─────────────────────────────────────────────
    "ServiceName": [
        ("service_name",   10, "humanize"),
        ("service",         9, "humanize"),
        ("product_name",    9, "humanize"),
        ("product",         8, "humanize"),
        ("tool_name",       8, "humanize"),
        ("tool",            7, "humanize"),
        ("offering",        6, "humanize"),
        ("application",     5, "humanize"),
        ("app",             4, "humanize"),
    ],
    "SkuId": [
        ("sku_id",    10, "identity"),
        ("sku",        9, "identity"),
        ("product_id", 8, "identity"),
        ("plan_id",    7, "identity"),
        ("plan",       6, "identity"),
        ("tier_id",    7, "identity"),
        ("tier",       5, "identity"),
        ("item_id",    4, "identity"),
    ],
    "UsageType": [
        ("usage_type",    10, "humanize"),
        ("charge_type",    9, "humanize"),
        ("line_item_type", 8, "humanize"),
        ("type",           6, "humanize"),
        ("sku",            5, "humanize"),
        ("plan",           4, "humanize"),
    ],
    "ProductFamily": [
        ("product_family",  10, "humanize"),
        ("family",           9, "humanize"),
        ("category",         7, "humanize"),
        ("product_category", 7, "humanize"),
        ("department",       5, "humanize"),
    ],

    # ── Quantity / unit columns ───────────────────────────────────────────────
    "ConsumedQuantity": [
        ("consumed_quantity", 10, "identity"),
        ("usage_quantity",     9, "identity"),
        ("quantity",           8, "identity"),
        ("qty",                8, "identity"),
        ("total_tokens",       7, "identity"),
        ("tokens",             7, "identity"),
        ("requests",           6, "identity"),
        ("api_calls",          6, "identity"),
        ("seats",              6, "identity"),
        ("licenses",           6, "identity"),
        ("count",              5, "identity"),
        ("amount",             3, "identity"),
        ("usage",              3, "identity"),
    ],
    "ConsumedUnit": [
        ("consumed_unit", 10, "identity"),
        ("unit_type",      9, "identity"),
        ("unit",           8, "identity"),
        ("measure",        7, "identity"),
        ("metric",         6, "identity"),
        ("uom",            5, "identity"),
    ],

    # ── Resource columns ──────────────────────────────────────────────────────
    "ResourceId": [
        ("resource_id",   10, "identity"),
        ("instance_id",    9, "identity"),
        ("account_id",     8, "identity"),
        ("tenant_id",      8, "identity"),
        ("org_id",         7, "identity"),
        ("workspace_id",   7, "identity"),
        ("project_id",     7, "identity"),
        ("user_id",        6, "identity"),
        ("username",       5, "identity"),
        ("user",           4, "identity"),
        ("id",             3, "identity"),
    ],
    "ResourceName": [
        ("resource_name",   10, "identity"),
        ("instance_name",    9, "identity"),
        ("workspace_name",   8, "identity"),
        ("project_name",     8, "identity"),
        ("host_name",        7, "identity"),
        ("hostname",         7, "identity"),
        ("org_name",         6, "identity"),
        ("organization",     6, "identity"),
        ("username",         5, "identity"),
        ("user",             4, "identity"),
        ("name",             3, "identity"),
    ],

    # ── Region column ─────────────────────────────────────────────────────────
    "RegionName": [
        ("region_name",     10, "identity"),
        ("region",           9, "identity"),
        ("location",         8, "identity"),
        ("availability_zone", 7, "identity"),
        ("az",               6, "identity"),
        ("datacenter",       5, "identity"),
        ("data_center",      5, "identity"),
        ("zone",             4, "identity"),
        ("site",             3, "identity"),
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# Tag source detection — columns that should become Tags (contextual metadata)
# ─────────────────────────────────────────────────────────────────────────────

TAG_SOURCE_PATTERNS = [
    "username",
    "user",
    "email",
    "organization",
    "org",
    "team",
    "department",
    "project",
    "repository",
    "repo",
    "workflow",
    "environment",
    "env",
    "cost_center",
    "budget",
    "label",
    "tag",
]

# ─────────────────────────────────────────────────────────────────────────────
# Static value columns — inferred from data, never from a source CSV column
# ─────────────────────────────────────────────────────────────────────────────

STATIC_COLUMNS = {
    "ChargeCategory":  "Usage",
    "ChargeFrequency": "Monthly",
    "BillingCurrency": "USD",
}

# Columns that are always provided via CLI params (never mapped from source columns)
CLI_ONLY_COLUMNS = {"ProviderName", "BillingAccountId", "BillingAccountName"}


# ─────────────────────────────────────────────────────────────────────────────
# Scoring engine
# ─────────────────────────────────────────────────────────────────────────────

def _score_column(source_col: str, patterns: List[Tuple[str, int, str]]) -> Tuple[int, str]:
    """
    Score a source column name against a list of (pattern, score, transform) tuples.

    Returns (best_score, transform_name).  Returns (0, "identity") if no match.
    """
    col_lc = source_col.lower().replace("-", "_")
    best_score = 0
    best_transform = "identity"
    for pattern, score, transform in patterns:
        if pattern in col_lc:
            if score > best_score:
                best_score = score
                best_transform = transform
    return best_score, best_transform


def _find_best_match(
    focus_col: str,
    source_columns: List[str],
    min_score: int = 1,
) -> Optional[Tuple[str, str]]:
    """
    Find the best matching source column for a given FOCUS column.

    Returns (source_column_name, transform) or None if no match above min_score.
    """
    patterns = COLUMN_PATTERNS.get(focus_col, [])
    if not patterns:
        return None

    best_score = 0
    best_source = None
    best_transform = "identity"

    for src_col in source_columns:
        score, transform = _score_column(src_col, patterns)
        if score > best_score:
            best_score = score
            best_source = src_col
            best_transform = transform

    if best_score < min_score:
        return None

    return best_source, best_transform


# ─────────────────────────────────────────────────────────────────────────────
# Tag source detection
# ─────────────────────────────────────────────────────────────────────────────

def _detect_tag_sources(source_columns: List[str]) -> List[str]:
    """
    Identify all source columns that should be included in the Tags field.

    Returns a list of column names matching TAG_SOURCE_PATTERNS.
    """
    result = []
    for col in source_columns:
        col_lc = col.lower().replace("-", "_")
        for pattern in TAG_SOURCE_PATTERNS:
            if pattern in col_lc:
                result.append(col)
                break
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Tool name / product family inference
# ─────────────────────────────────────────────────────────────────────────────

PRODUCT_FAMILY_KEYWORDS: Dict[str, str] = {
    "copilot":    "Developer Tools",
    "github":     "Developer Tools",
    "claude":     "AI / Machine Learning",
    "anthropic":  "AI / Machine Learning",
    "openai":     "AI / Machine Learning",
    "gpt":        "AI / Machine Learning",
    "gemini":     "AI / Machine Learning",
    "jira":       "Project Management",
    "confluence": "Collaboration",
    "slack":      "Collaboration",
    "teams":      "Collaboration",
    "zoom":       "Collaboration",
    "datadog":    "Observability",
    "newrelic":   "Observability",
    "splunk":     "Observability",
    "snowflake":  "Data & Analytics",
    "databricks": "Data & Analytics",
    "tableau":    "Data & Analytics",
    "salesforce": "CRM",
    "hubspot":    "CRM",
    "okta":       "Identity & Security",
    "crowdstrike":"Identity & Security",
    "pagerduty":  "Incident Management",
}


def _infer_product_family(tool_name: str) -> str:
    """Infer ProductFamily from tool_name keywords."""
    tl = tool_name.lower()
    for keyword, family in PRODUCT_FAMILY_KEYWORDS.items():
        if keyword in tl:
            return family
    return "SaaS"


def _infer_tool_name(filename: str, source_columns: List[str], sample_rows: List[Dict]) -> str:
    """
    Infer tool name from:
      1. product / tool / service column value in first data row
      2. Usage report filename stem
    """
    for col in ("product", "tool", "service", "product_name", "service_name"):
        for row in sample_rows[:3]:
            val = ""
            for k, v in row.items():
                if k.lower() == col.lower() and v.strip():
                    val = v.strip()
                    break
            if val:
                # Strip SKU suffixes: "copilot_for_business" → "copilot"
                return re.split(r"[_\-/]", val.lower())[0]

    # Fallback: filename stem
    stem = os.path.splitext(os.path.basename(filename))[0].lower()
    stem = re.sub(r"[_\-]?(usage|report|export|billing|data|mar|apr|jan|feb|jun|jul|aug|sep|oct|nov|dec|\d{4})", "", stem)
    return stem.strip("_-") or "generic_tool"


# ─────────────────────────────────────────────────────────────────────────────
# Mapper generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_mapper(
    source_columns: List[str],
    sample_rows: List[Dict[str, str]],
    focus_schema: Dict[str, Any],
    tool_name: str = "",
    provider_name: str = "",
    product_family: str = "",
    currency: str = "USD",
    filename: str = "",
) -> Dict[str, Any]:
    """
    Core mapper generation function.

    Parameters
    ----------
    source_columns : Header columns from the SaaS usage export
    sample_rows    : First few data rows (used for value inference)
    focus_schema   : Parsed focus_schema.json
    tool_name      : Override for tool detection (optional)
    provider_name  : ProviderName default (optional)
    product_family : ProductFamily static value (optional)
    currency       : BillingCurrency default (default: USD)
    filename       : Source filename (used for tool inference)

    Returns
    -------
    Mapper dict ready to be serialised as JSON.
    """
    if not tool_name:
        tool_name = _infer_tool_name(filename, source_columns, sample_rows)
    if not product_family:
        product_family = _infer_product_family(tool_name)

    focus_columns: List[str] = [c["name"] for c in focus_schema["columns"]]

    # ── Build mappings ────────────────────────────────────────────────────────
    mappings: Dict[str, Any] = {}

    # Detect tag sources early (used when building Tags mapping)
    tag_sources = _detect_tag_sources(source_columns)
    log.info("Detected tag sources: %s", tag_sources)

    for focus_col in focus_columns:

        # Skip columns always provided via CLI
        if focus_col in CLI_ONLY_COLUMNS:
            continue

        # Skip columns with static defaults (handled in "defaults" section)
        if focus_col in STATIC_COLUMNS:
            continue

        # ProductFamily — always static (inferred from tool name)
        if focus_col == "ProductFamily":
            mappings[focus_col] = {
                "transform":    "static",
                "static_value": product_family,
            }
            continue

        # Tags — special multi-source aggregation
        if focus_col == "Tags":
            if tag_sources:
                mappings[focus_col] = {
                    "transform":   "build_tags",
                    "tag_sources": tag_sources,
                }
            else:
                mappings[focus_col] = {
                    "transform":    "static",
                    "static_value": "{}",
                }
            continue

        # All other columns — semantic matching
        match = _find_best_match(focus_col, source_columns)
        if match is not None:
            source_col, transform = match
            mapping: Dict[str, Any] = {
                "source":    source_col,
                "transform": transform,
            }

            # For BilledCost / EffectiveCost / ListCost, attempt to find
            # fallback source columns for richer cost coverage
            if focus_col in ("BilledCost", "EffectiveCost"):
                fallbacks = [
                    c for c in source_columns
                    if any(p in c.lower() for p in ("cost", "amount", "price"))
                    and c != source_col
                ][:2]
                if fallbacks:
                    mapping["fallback_sources"] = fallbacks
                mapping["default_value"] = "0"

            if focus_col == "ListCost":
                fallbacks = [
                    c for c in source_columns
                    if any(p in c.lower() for p in ("gross", "list", "retail", "cost", "amount"))
                    and c != source_col
                ][:2]
                if fallbacks:
                    mapping["fallback_sources"] = fallbacks
                mapping["default_value"] = "0"

            # For ConsumedUnit, add a sensible default
            if focus_col == "ConsumedUnit":
                mapping["default_value"] = _infer_default_unit(tool_name, sample_rows, source_col)

            mappings[focus_col] = mapping
            log.info("  %-25s ← %-30s (transform=%s)", focus_col, source_col, transform)
        else:
            log.debug("  %-25s : no matching source column found", focus_col)

    # ── Defaults section ──────────────────────────────────────────────────────
    defaults: Dict[str, str] = {
        "ChargeCategory":  STATIC_COLUMNS["ChargeCategory"],
        "ChargeFrequency": STATIC_COLUMNS["ChargeFrequency"],
        "BillingCurrency": currency,
    }
    if provider_name:
        defaults["ProviderName"] = provider_name

    # ── Assemble final mapper ─────────────────────────────────────────────────
    mapper: Dict[str, Any] = {
        "meta": {
            "tool_name":      tool_name,
            "generated_at":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_columns": source_columns,
            "focus_version":  "1.0",
            "generator":      "saas_focus_converter/mapper_generator/generate_mapper.py",
        },
        "defaults": defaults,
        "mappings": mappings,
    }

    log.info(
        "Mapper generated: tool=%r, %d explicit mappings, %d defaults",
        tool_name, len(mappings), len(defaults)
    )
    return mapper


def _infer_default_unit(
    tool_name: str,
    sample_rows: List[Dict[str, str]],
    unit_col: str,
) -> str:
    """Infer a ConsumedUnit default from available data."""
    # Try to read from sample data first
    for row in sample_rows[:5]:
        for k, v in row.items():
            if k.lower() == unit_col.lower() and v.strip():
                return v.strip()
    # Keyword-based inference
    tl = tool_name.lower()
    if any(k in tl for k in ("claude", "gpt", "gemini", "llm", "ai")):
        return "Tokens"
    if any(k in tl for k in ("copilot", "jira", "slack", "github")):
        return "Seats"
    if any(k in tl for k in ("datadog", "newrelic", "splunk")):
        return "Events"
    if any(k in tl for k in ("snowflake", "databricks", "bigquery")):
        return "Credits"
    return "Units"


# ─────────────────────────────────────────────────────────────────────────────
# File I/O helpers
# ─────────────────────────────────────────────────────────────────────────────

def read_usage_csv(path: str, sample_limit: int = 10) -> Tuple[List[str], List[Dict]]:
    """
    Read headers and first N rows from a CSV file.

    Returns (column_names, sample_rows).
    """
    log.info("Inspecting usage report: %s", path)
    with open(path, newline="", encoding="utf-8-sig") as fh:
        # Skip Excel-style SEP= directive (e.g. "SEP=," exported by Microsoft)
        first_line = fh.readline()
        if not first_line.strip().upper().startswith("SEP="):
            fh.seek(0)
        reader = csv.DictReader(fh)
        columns = list(reader.fieldnames or [])
        rows = [row for _, row in zip(range(sample_limit), reader)]
    log.info("Found %d columns: %s", len(columns), columns)
    return columns, rows


def read_focus_schema_file(path: str) -> Dict[str, Any]:
    """Load and return the FOCUS schema from focus_schema.json."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_mapper(mapper: Dict[str, Any], output_path: str) -> None:
    """Serialise and write the mapper to a JSON file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(mapper, fh, indent=2, ensure_ascii=False)
    log.info("Mapper written to: %s", output_path)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Inspect a SaaS usage CSV and auto-generate a FOCUS/CUR mapper.json.\n\n"
            "The generated mapper.json drives the transformation engine (main.py) "
            "to convert usage rows into FOCUS-compliant CUR format."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-detect everything from the filename
  python3 mapper_generator/generate_mapper.py \\
      --usage_report copilot_usage.csv \\
      --schema       schemas/focus_schema.json \\
      --output       mappers/copilot_mapper.json

  # Explicit tool metadata
  python3 mapper_generator/generate_mapper.py \\
      --usage_report  usage_report.csv \\
      --schema        schemas/focus_schema.json \\
      --output        mappers/my_tool_mapper.json \\
      --tool_name     my_tool \\
      --provider_name "My Provider" \\
      --product_family "Developer Tools" \\
      --currency      USD
        """,
    )
    p.add_argument(
        "--usage_report", required=True,
        help="Path to SaaS usage export CSV."
    )
    p.add_argument(
        "--schema",
        default=os.path.join(os.path.dirname(__file__), "..", "schemas", "focus_schema.json"),
        help="Path to focus_schema.json (default: schemas/focus_schema.json)."
    )
    p.add_argument(
        "--output", required=True,
        help="Output path for the generated mapper.json (e.g. mappers/copilot_mapper.json)."
    )
    p.add_argument("--tool_name",      default="", help="Tool/vendor name (auto-detected if omitted).")
    p.add_argument("--provider_name",  default="", help="ProviderName for FOCUS output (e.g. GitHub).")
    p.add_argument("--product_family", default="", help="ProductFamily static value (auto-inferred if omitted).")
    p.add_argument("--currency",       default="USD", help="BillingCurrency (default: USD).")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Read inputs
    source_columns, sample_rows = read_usage_csv(args.usage_report)
    focus_schema = read_focus_schema_file(args.schema)

    # Generate mapper
    mapper = generate_mapper(
        source_columns=source_columns,
        sample_rows=sample_rows,
        focus_schema=focus_schema,
        tool_name=args.tool_name,
        provider_name=args.provider_name,
        product_family=args.product_family,
        currency=args.currency,
        filename=args.usage_report,
    )

    # Write mapper
    write_mapper(mapper, args.output)
    print(f"✓ Mapper saved to: {args.output}")


if __name__ == "__main__":
    main()
