"""
transformer.py
==============
Mapper-driven, stateless transformation engine.

Converts any SaaS usage CSV into a FOCUS/CUR-compliant CSV using a JSON
mapper configuration.  Zero SaaS-vendor logic lives here — all field
mappings, transforms, and defaults are read from the mapper at runtime.

─── Three-Tier Value Resolution ──────────────────────────────────────────────

  Tier 1 — CLI Overrides (cli_params dict, passed at construction)
            Always win.  Used for ProviderName, BillingAccountId, etc.

  Tier 2 — Mapper Config  (mapper.json "mappings" section)
            Per-column instructions: source column, transform, fallbacks,
            static values, tag sources, default_value.

  Tier 3 — Mapper Defaults (mapper.json "defaults" section)
            Static default values for columns not covered by mappings.
            e.g. "ChargeCategory": "Usage"

  Fallback — Empty string (never None in output)

─── Mapper JSON structure (mapper["mappings"][focus_col]) ───────────────────

  {
    "source": "source_column_name",         // look up this col from the row
    "transform": "to_iso8601_start",        // transform to apply after lookup
    "fallback_sources": ["col_b", "col_c"], // try these if source is empty
    "default_value": "Units",               // emit this if all sources empty
    "static_value": "GitHub",              // ignore source entirely; emit fixed string
    "tag_sources": ["username", "org"],    // for build_tags transform only
    "sources": ["col_a", "col_b"]          // for first_non_empty transform
  }

─── Validation ───────────────────────────────────────────────────────────────

  validate_required_columns() raises ValueError listing all required FOCUS
  columns that would be empty, so problems are caught before any rows are
  written.
"""

from __future__ import annotations

import csv
import json
import logging
import os
from typing import Any, Dict, List, Optional

from transform_engine.field_transformations import (
    TRANSFORM_REGISTRY,
    apply_transform,
    _lookup_column,
)

log = logging.getLogger(__name__)

# FOCUS required columns — must never be empty in the output
REQUIRED_FOCUS_COLUMNS: List[str] = [
    "ProviderName",
    "BillingAccountId",
    "BillingAccountName",
    "BillingCurrency",
    "BillingPeriodEnd",
    "BillingPeriodStart",
    "BilledCost",
    "EffectiveCost",
    "ListCost",
    "ChargeCategory",
    "ChargeFrequency",
    "ChargePeriodEnd",
    "ChargePeriodStart",
    "ServiceName",
]


# ─────────────────────────────────────────────────────────────────────────────
# MapperDrivenTransformer
# ─────────────────────────────────────────────────────────────────────────────

class MapperDrivenTransformer:
    """
    Converts SaaS usage rows to FOCUS/CUR rows using a declarative mapper.

    Parameters
    ----------
    mapper      : Parsed mapper.json as a dict
    schema      : Ordered list of FOCUS output column names (from template row 0)
    cli_params  : Dict of Tier-1 override values (e.g. {"ProviderName": "GitHub"})
    """

    def __init__(
        self,
        mapper: Dict[str, Any],
        schema: List[str],
        cli_params: Optional[Dict[str, str]] = None,
    ) -> None:
        self.mapper = mapper
        self.schema = schema
        self.cli_params: Dict[str, str] = cli_params or {}
        self.mappings: Dict[str, Any] = mapper.get("mappings", {})
        self.defaults: Dict[str, str] = mapper.get("defaults", {})

        # Validate all transform names declared in the mapper
        self._validate_transforms()

    # ── Public API ────────────────────────────────────────────────────────────

    def transform_row(self, row: Dict[str, str]) -> Dict[str, str]:
        """Transform one input row into one FOCUS-compliant output row."""
        out: Dict[str, str] = {}
        for col in self.schema:
            out[col] = self._resolve(col, row)
        return out

    def validate_required_columns(
        self, sample_row: Dict[str, str]
    ) -> List[str]:
        """
        Check that all required FOCUS columns produce non-empty values
        for the given sample row.

        Returns a list of column names that would be empty.
        Raises ValueError if any required column would be empty.
        """
        empty: List[str] = []
        test_out = self.transform_row(sample_row)
        for col in REQUIRED_FOCUS_COLUMNS:
            if not test_out.get(col, "").strip():
                empty.append(col)
        if empty:
            raise ValueError(
                f"The following required FOCUS columns are empty for at least one row "
                f"(check mapper, CLI params, and input CSV):\n  {', '.join(empty)}"
            )
        return []

    # ── Internal resolution ───────────────────────────────────────────────────

    def _resolve(self, focus_col: str, row: Dict[str, str]) -> str:
        """
        Resolve one FOCUS column value using three-tier priority.
        """
        # ── Tier 1: CLI override ──────────────────────────────────────────────
        cli_val = self.cli_params.get(focus_col, "")
        if cli_val:
            return cli_val

        # ── Tier 2: Mapper config ─────────────────────────────────────────────
        mapping = self.mappings.get(focus_col)
        if mapping is not None:
            return self._apply_mapping(focus_col, mapping, row)

        # ── Tier 3: Mapper defaults ───────────────────────────────────────────
        default = self.defaults.get(focus_col, "")
        return default

    def _apply_mapping(
        self,
        focus_col: str,
        mapping: Dict[str, Any],
        row: Dict[str, str],
    ) -> str:
        """Apply a single mapping instruction to produce an output value."""
        transform_name = mapping.get("transform", "identity")

        # ── Static value (no source column needed) ───────────────────────────
        if transform_name == "static" or "static_value" in mapping:
            return str(mapping.get("static_value", ""))

        # ── build_tags: multi-column JSON aggregation ────────────────────────
        if transform_name == "build_tags":
            return apply_transform("build_tags", "", row=row, config=mapping)

        # ── first_non_empty: try multiple source columns ─────────────────────
        if transform_name == "first_non_empty":
            sources = mapping.get("sources", [])
            for src in sources:
                val = _lookup_column(row, src)
                if val:
                    break
            else:
                val = ""
            default = mapping.get("default_value", "")
            return val or default

        # ── Standard: single source column + optional fallbacks ─────────────
        source_col = mapping.get("source", "")
        raw_value = ""

        if source_col:
            raw_value = _lookup_column(row, source_col)

        # Try fallback sources if primary is empty
        if not raw_value:
            for fallback in mapping.get("fallback_sources", []):
                raw_value = _lookup_column(row, fallback)
                if raw_value:
                    break

        # Apply default_value if still empty
        if not raw_value:
            raw_value = mapping.get("default_value", "")

        if not raw_value:
            return ""

        # Apply transform
        try:
            return apply_transform(transform_name, raw_value, row=row, config=mapping)
        except ValueError as exc:
            log.error("Column %r: %s", focus_col, exc)
            return raw_value

    # ── Internal validation ───────────────────────────────────────────────────

    def _validate_transforms(self) -> None:
        """Warn about any unrecognised transform names found in the mapper."""
        for col, mapping in self.mappings.items():
            if not isinstance(mapping, dict):
                continue
            t = mapping.get("transform", "identity")
            if t not in TRANSFORM_REGISTRY:
                log.warning(
                    "Mapper: column %r references unknown transform %r — "
                    "will fall back to identity",
                    col, t,
                )


# ─────────────────────────────────────────────────────────────────────────────
# Extra-tag injection (post-processing)
# ─────────────────────────────────────────────────────────────────────────────

def inject_extra_tag(
    out_row: Dict[str, str], tag_key: str, tag_value: str
) -> None:
    """
    Inject one additional key-value pair into the Tags column of out_row.
    Handles both empty Tags and existing JSON tags.  Modifies in-place.
    """
    if not tag_key:
        return
    existing = out_row.get("Tags", "")
    try:
        tags = json.loads(existing) if existing and existing != "{}" else {}
    except json.JSONDecodeError:
        tags = {}
    tags[tag_key] = tag_value
    out_row["Tags"] = json.dumps(tags, separators=(",", ":"))


# ─────────────────────────────────────────────────────────────────────────────
# Template reader
# ─────────────────────────────────────────────────────────────────────────────

def read_focus_schema(template_path: str) -> List[str]:
    """
    Read the FOCUS/CUR template CSV and return column names from row 0.
    Rows 1-4 are metadata/documentation and are skipped.
    """
    log.info("Reading FOCUS template schema: %s", template_path)
    with open(template_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        columns = [c.strip() for c in next(reader)]
    log.info("Schema: %d columns → %s", len(columns), columns)
    return columns


# ─────────────────────────────────────────────────────────────────────────────
# Mapper loader
# ─────────────────────────────────────────────────────────────────────────────

def load_mapper(mapper_path: str) -> Dict[str, Any]:
    """
    Load and parse a mapper.json file.

    Raises FileNotFoundError / json.JSONDecodeError with helpful messages.
    """
    if not os.path.exists(mapper_path):
        raise FileNotFoundError(
            f"Mapper file not found: {mapper_path}\n"
            f"Run mapper_generator/generate_mapper.py first to auto-generate it."
        )
    log.info("Loading mapper: %s", mapper_path)
    with open(mapper_path, encoding="utf-8") as fh:
        mapper = json.load(fh)
    tool = mapper.get("meta", {}).get("tool_name", "unknown")
    n_mappings = len(mapper.get("mappings", {}))
    log.info(
        "Mapper loaded: tool=%r, %d explicit mappings, %d defaults",
        tool, n_mappings, len(mapper.get("defaults", {}))
    )
    return mapper


# ─────────────────────────────────────────────────────────────────────────────
# Core conversion pipeline
# ─────────────────────────────────────────────────────────────────────────────

def convert(
    usage_path: str,
    mapper_path: str,
    template_path: str,
    output_path: str,
    cli_params: Optional[Dict[str, str]] = None,
    tag_key: str = "",
    tag_value: str = "",
    validate: bool = True,
    chunk_size: int = 500,
) -> int:
    """
    Full pipeline: usage CSV + mapper.json + FOCUS template → FOCUS CUR CSV.

    Returns the number of data rows written.

    Parameters
    ----------
    usage_path    : Path to SaaS usage export CSV
    mapper_path   : Path to mapper.json (generate with generate_mapper.py)
    template_path : Path to saas_template.csv (defines output column order)
    output_path   : Path to write the FOCUS-compliant output CSV
    cli_params    : Tier-1 override values (ProviderName, BillingAccountId, …)
    tag_key       : Extra tag key to inject into every output row
    tag_value     : Extra tag value
    validate      : Run required-field validation before writing (default True)
    chunk_size    : Log progress every N rows
    """
    cli_params = cli_params or {}

    # 1. Load schema, mapper, transformer
    schema = read_focus_schema(template_path)
    mapper = load_mapper(mapper_path)

    # Merge mapper-level defaults into CLI params (CLI still wins)
    mapper_defaults = mapper.get("defaults", {})
    merged_cli: Dict[str, str] = {**mapper_defaults, **cli_params}

    transformer = MapperDrivenTransformer(mapper, schema, merged_cli)

    # 2. Load input rows
    log.info("Loading usage report: %s", usage_path)
    with open(usage_path, newline="", encoding="utf-8-sig") as fh:
        # Skip Excel-style SEP= directive (e.g. "SEP=," exported by Microsoft)
        first_line = fh.readline()
        if not first_line.strip().upper().startswith("SEP="):
            fh.seek(0)
        reader = csv.DictReader(fh)
        rows = list(reader)

    if not rows:
        log.warning("Usage report is empty — no rows to convert.")
        return 0

    log.info("Loaded %d data rows from usage report.", len(rows))

    # 3. Optional validation on first row
    if validate:
        log.info("Validating required FOCUS columns against first row…")
        try:
            transformer.validate_required_columns(rows[0])
            log.info("Validation passed — all required columns are populated.")
        except ValueError as exc:
            log.error("Validation FAILED:\n%s", exc)
            raise

    # 4. Transform and stream-write output
    written = 0
    with open(output_path, "w", newline="", encoding="utf-8") as out_fh:
        writer = csv.DictWriter(out_fh, fieldnames=schema, extrasaction="ignore")
        writer.writeheader()

        for row in rows:
            out_row = transformer.transform_row(row)

            # Post-process: inject extra tag
            if tag_key:
                inject_extra_tag(out_row, tag_key, tag_value)

            writer.writerow(out_row)
            written += 1

            if written % chunk_size == 0:
                log.info("  … %d rows written", written)

    log.info("Conversion complete: %d rows → %s", written, output_path)
    return written
