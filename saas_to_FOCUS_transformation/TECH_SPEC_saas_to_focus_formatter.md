# Technical Specification
## SaaS Usage → FOCUS/CUR Converter (`saas_to_focus_formatter`)

**Version:** 1.2
**Date:** 2026-03-05
**Status:** Implemented
**Author:** CoreStack Engineering

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Repository Layout](#2-repository-layout)
3. [Data Flow](#3-data-flow)
4. [Component Design](#4-component-design)
   - 4.1 [CLI — `main.py`](#41-cli--mainpy)
   - 4.2 [Mapper Generator — `generate_mapper.py`](#42-mapper-generator--generate_mapperpy)
   - 4.3 [Transformation Engine — `transformer.py`](#43-transformation-engine--transformerpy)
   - 4.4 [Transform Functions — `field_transformations.py`](#44-transform-functions--field_transformationspy)
   - 4.5 [S3 Upload — `_upload_to_s3()`](#45-s3-upload--_upload_to_s3)
5. [Mapper JSON Schema](#5-mapper-json-schema)
6. [Three-Tier Value Resolution](#6-three-tier-value-resolution)
7. [FOCUS Output Schema](#7-focus-output-schema)
8. [Semantic Scoring Algorithm](#8-semantic-scoring-algorithm)
9. [Date Parsing](#9-date-parsing)
10. [Error Handling](#10-error-handling)
11. [CLI Reference](#11-cli-reference)
12. [Configuration — Default Paths](#12-configuration--default-paths)
13. [Testing Strategy](#13-testing-strategy)
14. [Extension Points](#14-extension-points)
15. [Known Limitations](#15-known-limitations)

---

## 1. Architecture Overview

```
┌──────────────────────┐     ┌─────────────────────────────┐
│  usage_report.csv    │ OR  │  usage_reports/  (folder)   │
│  (single-file mode)  │     │  ├── copilot_mar.csv        │
└─────────┬────────────┘     │  ├── copilot_apr.csv        │
          │                  │  └── claude_mar.csv         │
          │                  └─────────────┬───────────────┘
          └──────────────────┬─────────────┘
                             │  (batch: processed in queue)
                             ▼
          │
          ▼
┌─────────────────────────────────────────────────────────┐
│  Mapper Generator  (mapper_generator/generate_mapper.py) │
│                                                         │
│  ┌─ Reads CSV headers + 10 sample rows                  │
│  ├─ Loads focus_schema.json                             │
│  ├─ Semantic scoring: source col → FOCUS col            │
│  ├─ Detects tag sources, date cols, cost cols           │
│  └─ Emits mappers/<tool>_mapper.json                    │
└─────────┬───────────────────────────────────────────────┘
          │
          ▼  (declarative)
  mappers/<tool>_mapper.json
          │
          ▼
┌─────────────────────────────────────────────────────────┐
│  Transformation Engine  (transform_engine/)              │
│                                                         │
│  transformer.py                                         │
│  ├─ Loads mapper + FOCUS template schema                │
│  ├─ Three-tier resolver (CLI > mapping > defaults)      │
│  └─ Calls field_transformations.py per cell             │
│                                                         │
│  field_transformations.py                               │
│  └─ 13 pure transform functions + TRANSFORM_REGISTRY    │
└─────────┬───────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────┐
│  focus_cur_output.csv  (single-file mode)        │
│  focus_cur_outputs/    (batch mode)              │
│  ├── copilot_mar_focus_cur.csv                   │
│  ├── copilot_apr_focus_cur.csv                   │
│  └── claude_mar_focus_cur.csv                    │
└──────────────┬───────────────────────────────────┘
               │  (if [s3] bucket configured)
               ▼
┌──────────────────────────────────────────────────┐
│  AWS S3  (optional — boto3 required)             │
│  s3://<bucket>/<prefix>/                         │
│  ├── copilot_mar_focus_cur.csv                   │
│  ├── copilot_apr_focus_cur.csv                   │
│  └── claude_mar_focus_cur.csv                    │
└──────────────────────────────────────────────────┘
```

**Design principle:** All vendor-specific logic is in `mapper.json`. The engine is vendor-agnostic — it never needs to know the SaaS provider's name.

---

## 2. Repository Layout

```
saas_to_focus_formatter/       ← project root (cd here before running)
│
├── main.py                    ← CLI: generate | transform | run
│
├── mapper_generator/
│   ├── __init__.py
│   └── generate_mapper.py     ← mapper auto-generation from CSV
│
├── transform_engine/
│   ├── __init__.py
│   ├── transformer.py         ← mapper-driven conversion engine
│   └── field_transformations.py  ← 13 pure transform functions
│
├── schemas/
│   └── focus_schema.json      ← FOCUS 1.0 column reference
│
├── mappers/                   ← one JSON per SaaS vendor
│   └── copilot_mapper.json    ← GitHub Copilot (reference)
│
├── tests/
│   ├── test_field_transformations.py  ← 63 tests
│   ├── test_transformer.py            ← 38 tests
│   ├── test_generate_mapper.py        ← 50 tests
│   └── test_main.py                   ← 20 tests (batch helpers)
│
└── README.md

── (workspace root, one level up) ──
../usage_report.csv          ← SaaS vendor export (single-file input)
../usage_reports/            ← Folder of SaaS exports  (batch input)
../saas_template.csv         ← FOCUS column order template
../focus_cur_output.csv      ← FOCUS CUR output (single-file mode)
../focus_cur_outputs/        ← Output folder (batch mode)
```

---

## 3. Data Flow

In **batch mode** (`--usage_dir`), Steps 1–7 below execute once per input file. The mapper is re-resolved per file in `run` mode (tool detection → `mappers/<tool>_mapper.json`); in `transform` mode the same `--mapper` is used for all files.

```
Input files (per processing unit):
  usage_report.csv   — vendor export (columns vary per vendor)
  saas_template.csv  — defines FOCUS output column order (row 0)
  mapper.json        — column mappings, transforms, defaults

Step 1 — Schema load
  read_focus_schema(saas_template.csv)
  → List[str]  (23 FOCUS column names in order)

Step 2 — Mapper load
  load_mapper(mapper.json)
  → Dict  { meta, defaults, mappings }

Step 3 — Transformer init
  MapperDrivenTransformer(mapper, schema, cli_params)
  → Merges mapper defaults + CLI params into merged_cli
  → Validates all transform names in mapper

Step 4 — CSV read
  csv.DictReader(usage_report.csv)
  → List[Dict[str, str]]  (all rows in memory)

Step 5 — Optional validation
  transformer.validate_required_columns(rows[0])
  → Raises ValueError listing empty required columns

Step 6 — Row-by-row transformation
  for row in rows:
    out_row = transformer.transform_row(row)
    inject_extra_tag(out_row, tag_key, tag_value)   # if --tag_key supplied
    writer.writerow(out_row)

Step 7 — Local output
  focus_cur_output.csv  — 23 columns, N rows

Step 8 — S3 upload (if configured)
  _upload_to_s3(local_path, args)
  → boto3.Session → s3.upload_file(local_path, bucket, s3_key)
  → s3_uri = "s3://<bucket>/<prefix>/<filename>"
  → non-fatal: exception logged as WARNING, does not fail the file
```

---

## 4. Component Design

### 4.1 CLI — `main.py`

Entry point. Parses arguments and dispatches to sub-command handlers.

**Sub-commands:**

| Command | Handler | Description |
|---------|---------|-------------|
| `generate` | `cmd_generate()` | Generate mapper from a single CSV |
| `transform` | `cmd_transform()` | Convert one file or a folder of files using existing mapper |
| `run` | `cmd_run()` | generate + transform in one command; batch-aware |

**Input source group (mutually exclusive on `transform` and `run`):**

| Flag | Description |
|------|-------------|
| `--usage_report FILE` | Single SaaS export CSV |
| `--usage_dir DIR` | Folder of CSVs; all `*.csv` files processed in alphabetical order |

**Shared argument groups:**

- `_add_common_args()` — `--schema`, `--provider_name`, `--billing_account_id`, `--billing_account_name`, `--billing_currency`, `--tool_name`, `--product_family`
- `_add_output_args()` — `--cur_template`, `--output` (single-file), `--output_dir` (batch), `--region_name`, `--charge_category`, `--charge_frequency`, `--tag_key`, `--tag_value`, `--skip_validation`

**Batch helper functions:**

| Function | Signature | Purpose |
|----------|-----------|---------|
| `_get_input_files(args)` | `(args)` → `List[str]` | Returns sorted CSV paths from `--usage_dir` or wraps `--usage_report` in a list |
| `_resolve_output_path(input_path, args)` | `(str, args)` → `str` | Returns `<output_dir>/<stem>_focus_cur.csv` in batch mode, or `args.output` in single-file mode |

**`_build_cli_params(args)`** — builds the Tier-1 override dict. Only non-empty values are included, so empty CLI flags don't overwrite mapper defaults.

**Default paths** (resolved relative to `main.py` location):

```python
DEFAULT_SCHEMA   = <project_root>/schemas/focus_schema.json
DEFAULT_TEMPLATE = <project_root>/../saas_template.csv
DEFAULT_MAPPERS_DIR = <project_root>/mappers/
```

---

### 4.2 Mapper Generator — `generate_mapper.py`

Produces a `mapper.json` by statically analysing a SaaS CSV.

**Key functions:**

| Function | Signature | Purpose |
|----------|-----------|---------|
| `generate_mapper()` | `(source_columns, sample_rows, focus_schema, ...)` → `Dict` | Core mapper generation |
| `_find_best_match()` | `(focus_col, source_columns)` → `(src, transform) \| None` | Best-scoring source column for a FOCUS col |
| `_score_column()` | `(source_col, patterns)` → `(score, transform)` | Score one column against a pattern list |
| `_detect_tag_sources()` | `(source_columns)` → `List[str]` | Find contextual columns for Tags |
| `_infer_tool_name()` | `(filename, source_cols, sample_rows)` → `str` | Infer vendor name |
| `_infer_product_family()` | `(tool_name)` → `str` | Map tool name to ProductFamily |
| `_infer_default_unit()` | `(tool_name, sample_rows, unit_col)` → `str` | Infer ConsumedUnit default |
| `read_usage_csv()` | `(path)` → `(columns, rows)` | Read CSV headers + sample |
| `write_mapper()` | `(mapper, output_path)` → None | Serialise mapper to JSON |

**Columns skipped by generator:**

- `CLI_ONLY_COLUMNS = {"ProviderName", "BillingAccountId", "BillingAccountName"}` — always provided via CLI
- `STATIC_COLUMNS = {"ChargeCategory", "ChargeFrequency", "BillingCurrency"}` — written to `defaults` section

---

### 4.3 Transformation Engine — `transformer.py`

**`MapperDrivenTransformer`** — stateless per row, constructed once per pipeline run.

```python
class MapperDrivenTransformer:
    def __init__(self, mapper, schema, cli_params): ...
    def transform_row(self, row) -> Dict[str, str]: ...
    def validate_required_columns(self, sample_row) -> List[str]: ...
    def _resolve(self, focus_col, row) -> str: ...        # three-tier
    def _apply_mapping(self, focus_col, mapping, row) -> str: ...
    def _validate_transforms(self): ...                   # warn on unknown
```

**`inject_extra_tag(out_row, tag_key, tag_value)`** — post-processing: merges one extra k/v into the `Tags` JSON column. Handles empty, valid, and malformed JSON gracefully.

**`read_focus_schema(template_path)`** — reads column names from row 0 of `saas_template.csv`. Rows 1–4 are metadata/docs and are skipped.

**`load_mapper(mapper_path)`** — reads and validates mapper JSON. Raises `FileNotFoundError` with a helpful remediation message.

**`convert()`** — top-level pipeline function. Coordinates schema load → mapper load → transformer init → CSV read → validation → row transform → CSV write.

---

### 4.4 Transform Functions — `field_transformations.py`

All functions share the signature:
```python
fn(value: str, row: Dict | None = None, config: Dict | None = None) -> str
```

| Function | Transform name | Input → Output |
|----------|---------------|----------------|
| `identity` | `identity` | unchanged |
| `to_iso8601_start` | `to_iso8601_start` | date → `YYYY-MM-DDT00:00:00Z` |
| `to_iso8601_end` | `to_iso8601_end` | date → `YYYY-MM-DDT23:59:59Z` |
| `to_billing_period_end` | `to_billing_period_end` | date → first instant of next month |
| `humanize` | `humanize` | `snake_case`/`kebab-case` → Title Case |
| `title_case` | `title_case` | Title Case (no symbol replacement) |
| `to_uppercase` | `to_uppercase` | UPPER |
| `to_lowercase` | `to_lowercase` | lower |
| `strip_whitespace` | `strip_whitespace` | trim leading/trailing spaces |
| `to_decimal` | `to_decimal` | `"$1,234.56"` → `"1234.56"` |
| `build_tags` | `build_tags` | columns → compact JSON map |
| `static_value` | `static` | → `config["static_value"]` |
| `first_non_empty` | `first_non_empty` | first non-empty value from `config["sources"]` |

**`TRANSFORM_REGISTRY`** — `Dict[str, Callable]` maps string names (used in mapper JSON) to callables. Extend by adding a new entry.

**`apply_transform(name, value, row, config)`** — public entry point used by the engine. Raises `ValueError` with available names listed if `name` is not registered.

**`_lookup_column(row, column)`** — case-insensitive column lookup with substring fallback (e.g. `"date"` matches `"usage_date"`).

**`_parse_dt(value)`** — tries 7 date formats in order; returns `datetime` or `None`.

---

### 4.5 S3 Upload — `_upload_to_s3()`

Optional post-processing step in `main.py`, called after `convert()` succeeds.

```python
def _upload_to_s3(local_path: str, args: argparse.Namespace) -> Optional[str]:
    ...
```

**Activation:** Only executes if `args.s3_bucket` is non-empty (set via CLI or `config.ini [s3] bucket`).

**boto3 import:** Deferred — `import boto3` inside the function body. The core pipeline has zero runtime dependency on boto3; the import only happens when S3 upload is requested. An `ImportError` with install instructions is raised if boto3 is not installed.

**S3 key construction:**
```python
s3_key = f"{prefix}/{filename}" if prefix else filename
```

**Credentials:** Standard boto3 resolution chain — environment variables → `~/.aws/credentials` (named profile via `s3.profile`) → IAM instance role → ECS task role. No credentials are stored in config files.

**Error handling:** S3 upload exceptions are caught in the caller (`cmd_transform`, `cmd_run`) and logged as `WARNING`. The file is not marked as failed in `run_state.json`; local output is always retained.

**Configuration keys (from `config.ini [s3]` section):**

| Key | CLI flag | Default | Description |
|-----|----------|---------|-------------|
| `bucket` | `--s3_bucket` | none | S3 bucket name; enables upload when set |
| `prefix` | `--s3_prefix` | `""` (bucket root) | Key prefix (folder path) |
| `region` | `--s3_region` | SDK default | AWS region |
| `profile` | `--s3_profile` | default credential chain | Named AWS credentials profile |

---

## 5. Mapper JSON Schema

```jsonc
{
  "meta": {
    "tool_name":      "copilot",           // vendor identifier
    "generated_at":   "2026-03-03T10:43:47Z",
    "source_columns": ["date", "product", ...],  // original CSV headers
    "focus_version":  "1.0",
    "generator":      "..."
  },

  "defaults": {
    // Tier-3: static fallbacks for columns not covered in "mappings"
    "ChargeCategory":  "Usage",
    "ChargeFrequency": "Monthly",
    "BillingCurrency": "USD",
    "ProviderName":    "GitHub"            // optional; CLI always wins
  },

  "mappings": {
    // One entry per FOCUS output column that requires derivation
    "<FocusColumn>": {
      "source":           "<source_col>",  // look up this column in the row
      "transform":        "<fn_name>",     // transform to apply
      "fallback_sources": ["<col2>", ...], // try if source is empty
      "default_value":    "<str>",         // emit if all sources empty
      "static_value":     "<str>",         // static output; ignores source
      "tag_sources":      ["<col1>", ...], // for build_tags only
      "sources":          ["<col1>", ...]  // for first_non_empty only
    }
  }
}
```

**Mapping types:**

| Type | Required fields | When to use |
|------|-----------------|-------------|
| Source + transform | `source`, `transform` | Standard column mapping |
| Fallback chain | `source`, `fallback_sources`, `default_value` | Cost columns |
| Static | `transform: "static"`, `static_value` | ProductFamily, fixed strings |
| Multi-source tags | `transform: "build_tags"`, `tag_sources` | Tags column |
| First non-empty | `transform: "first_non_empty"`, `sources` | Compound resource IDs |

---

## 6. Three-Tier Value Resolution

For every FOCUS column in every row:

```
Tier 1 — CLI params  (merged_cli dict)
  If merged_cli[focus_col] is non-empty → return it
  Applies to: ProviderName, BillingAccountId, BillingAccountName,
              BillingCurrency, RegionName, ChargeCategory, ChargeFrequency

Tier 2 — mapper["mappings"][focus_col]
  If mapping exists → _apply_mapping(focus_col, mapping, row)
    a. static: return static_value
    b. build_tags: aggregate tag_sources columns → JSON
    c. first_non_empty: try each source in order
    d. standard: lookup source → fallbacks → default_value → apply transform

Tier 3 — mapper["defaults"][focus_col]
  If default exists → return it

Fallback — ""  (empty string, never None)
```

**Key behaviour:** `merged_cli = {**mapper["defaults"], **cli_params}` — mapper defaults are merged with CLI params before being passed to the transformer, so CLI always wins but mapper defaults can seed values that don't need to be passed on every run.

---

## 7. FOCUS Output Schema

23 columns defined in `schemas/focus_schema.json` and ordered by `saas_template.csv`:

| # | Column | Required | Type |
|---|--------|:--------:|------|
| 1 | `ProviderName` | ✅ | string |
| 2 | `BillingAccountId` | ✅ | string |
| 3 | `BillingAccountName` | ✅ | string |
| 4 | `BillingCurrency` | ✅ | string (ISO 4217) |
| 5 | `BillingPeriodEnd` | ✅ | datetime (`YYYY-MM-01T00:00:00Z`) |
| 6 | `BillingPeriodStart` | ✅ | datetime (`YYYY-MM-DDT00:00:00Z`) |
| 7 | `BilledCost` | ✅ | decimal string |
| 8 | `EffectiveCost` | ✅ | decimal string |
| 9 | `ListCost` | ✅ | decimal string |
| 10 | `ChargeCategory` | ✅ | string (typically `Usage`) |
| 11 | `ChargeFrequency` | ✅ | string (typically `Monthly`) |
| 12 | `ChargePeriodEnd` | ✅ | datetime (`YYYY-MM-DDT23:59:59Z`) |
| 13 | `ChargePeriodStart` | ✅ | datetime (`YYYY-MM-DDT00:00:00Z`) |
| 14 | `ServiceName` | ✅ | string |
| 15 | `ConsumedQuantity` | — | decimal string |
| 16 | `ConsumedUnit` | — | string |
| 17 | `RegionName` | — | string |
| 18 | `ResourceId` | — | string |
| 19 | `ResourceName` | — | string |
| 20 | `SkuId` | — | string |
| 21 | `Tags` | — | compact JSON `{"k":"v"}` |
| 22 | `UsageType` | — | string |
| 23 | `ProductFamily` | — | string |

**`saas_template.csv` row structure:**

| Row | Content |
|-----|---------|
| 0 | Column names (authoritative order) |
| 1 | Required / optional |
| 2 | Data types |
| 3 | Descriptions |
| 4 | Example values |

---

## 8. Semantic Scoring Algorithm

Used by `generate_mapper.py` to auto-map source CSV columns to FOCUS columns.

### Algorithm

```python
for each FOCUS column in COLUMN_PATTERNS:
    for each source column in CSV:
        score, transform = _score_column(source_col, patterns)
    best_source = source_col with highest score
    if best_score >= min_score (default 1):
        add to mappings
```

### Score thresholds

| Score | Confidence |
|-------|-----------|
| ≥ 10 | Exact / near-exact match (e.g. `net_amount` → `BilledCost`) |
| 5–9 | Strong likely match (e.g. `cost` → `BilledCost`) |
| 1–4 | Weak/fallback match (e.g. `amount` → `BilledCost`) |

### Pattern matching

```python
col_lc = source_col.lower().replace("-", "_")
for pattern, score, transform in patterns:
    if pattern in col_lc:   # substring match
        score wins if higher than previous
```

Hyphens are normalised to underscores before matching.

### Tag source detection

`TAG_SOURCE_PATTERNS` (18 substrings): `username`, `user`, `email`, `org`, `organization`, `team`, `department`, `project`, `repository`, `repo`, `workflow`, `environment`, `env`, `cost_center`, `budget`, `label`, `tag`

Any source column whose name contains one of these patterns is included in `tag_sources`.

---

## 9. Date Parsing

**`_DATE_FORMATS`** (tried in order):

| Format | Example input |
|--------|--------------|
| `%Y-%m-%dT%H:%M:%SZ` | `2026-03-15T14:30:00Z` |
| `%Y-%m-%dT%H:%M:%S` | `2026-03-15T14:30:00` |
| `%Y-%m-%d` | `2026-03-15` |
| `%Y/%m/%d` | `2026/03/15` |
| `%m/%d/%Y` | `03/15/2026` |
| `%d-%m-%Y` | `15-03-2026` |
| `%Y-%m-%dT%H:%M:%S.%fZ` | `2026-03-15T14:30:00.000Z` |

**On parse failure:** logs a WARNING, returns `""` (empty string). Does not crash.

**`to_billing_period_end` edge case:** December → January of next year:
```python
if month == 12:
    year += 1
    month = 1
else:
    month += 1
return f"{year:04d}-{month:02d}-01T00:00:00Z"
```

---

## 10. Error Handling

| Error condition | Behaviour |
|-----------------|-----------|
| Mapper file not found | `FileNotFoundError` with remediation message |
| Required FOCUS column empty | `ValueError` listing all empty columns; printed to stderr; exits with code 1 |
| Unknown transform name | `ValueError` listing available transforms |
| Unparseable date | `WARNING` logged; empty string emitted; processing continues |
| Source column not found in row | Empty string returned; fallbacks tried next |
| Malformed Tags JSON (inject_extra_tag) | Treated as empty tags; new tag written |
| Empty usage report | Warning logged; returns 0 rows; no output file written |

---

## 11. CLI Reference

### `generate`

```
python3 main.py generate
  --usage_report   <path>     Input SaaS CSV                      [required]
  --output_mapper  <path>     Output mapper.json                  [default: mappers/<tool>_mapper.json]
  --provider_name  <str>      ProviderName in defaults            [optional]
  --tool_name      <str>      Override tool detection             [optional]
  --product_family <str>      Override ProductFamily inference    [optional]
  --billing_currency <str>    ISO 4217 code                       [default: USD]
  --schema         <path>     focus_schema.json                   [default: schemas/focus_schema.json]
```

### `transform`

```
python3 main.py transform
  --usage_report       <path>  Single input CSV                   [mutually exclusive with --usage_dir]
  --usage_dir          <dir>   Folder of CSVs (batch mode)       [mutually exclusive with --usage_report]
  --mapper             <path>  Mapper JSON                        [required]
  --cur_template       <path>  FOCUS schema template              [default: ../saas_template.csv]
  --output             <path>  Output CUR CSV (single-file mode)  [default: focus_cur_output.csv]
  --output_dir         <dir>   Output folder (batch mode)         [optional]
  --provider_name      <str>   Tier-1 ProviderName override       [optional]
  --billing_account_id <str>   Tier-1 BillingAccountId            [optional]
  --billing_account_name <str> Tier-1 BillingAccountName          [optional]
  --billing_currency   <str>   ISO 4217 code                      [default: USD]
  --region_name        <str>   Tier-1 RegionName                  [optional]
  --tag_key            <str>   Extra tag key for all rows         [optional]
  --tag_value          <str>   Extra tag value                    [optional]
  --skip_validation            Skip required-field check          [flag]
  --s3_bucket          <str>   S3 bucket name (enables S3 upload) [optional]
  --s3_prefix          <str>   S3 key prefix / folder path        [optional]
  --s3_region          <str>   AWS region for the bucket          [optional]
  --s3_profile         <str>   AWS named credentials profile      [optional]
```

### `run`

All flags from `generate` + `transform`. Additional:

```
  --usage_report / --usage_dir  (same input modes as transform)
  --output / --output_dir       (same output modes as transform)
  --mapper              <path>  Use existing mapper for all files (skip detection/generation) [optional]
  --regenerate_mapper           Force mapper re-generation for each file                      [flag]
```

---

## 12. Configuration — Default Paths

All paths resolved relative to `main.py`'s directory (`_ROOT`):

| Constant | Resolved path |
|----------|--------------|
| `DEFAULT_SCHEMA` | `<project_root>/schemas/focus_schema.json` |
| `DEFAULT_TEMPLATE` | `<project_root>/../saas_template.csv` |
| `DEFAULT_MAPPERS_DIR` | `<project_root>/mappers/` |

**S3 configuration** is stored in `config.ini [s3]`:

| INI key | CLI flag | Description |
|---------|----------|-------------|
| `bucket` | `--s3_bucket` | Bucket name; enables upload when set |
| `prefix` | `--s3_prefix` | Key prefix within the bucket |
| `region` | `--s3_region` | AWS region |
| `profile` | `--s3_profile` | AWS named credentials profile |

When running from `saas_to_focus_formatter/`, external files are accessed via `../`:

| File / Folder | Convention | Mode |
|------|-----------|------|
| `usage_report.csv` | `../usage_report.csv` | Single-file |
| `usage_reports/` | `../usage_reports/` | Batch |
| `saas_template.csv` | `../saas_template.csv` (DEFAULT_TEMPLATE) | Both |
| `focus_cur_output.csv` | `../focus_cur_output.csv` | Single-file |
| `focus_cur_outputs/` | `../focus_cur_outputs/` | Batch |

**Batch output naming:** for input `../usage_reports/copilot_march.csv`, output is `<output_dir>/copilot_march_focus_cur.csv`.

---

## 13. Testing Strategy

**Framework:** Python `unittest` (stdlib — no pytest required)

**Run all tests:**
```bash
cd saas_to_focus_formatter
python3 -m unittest discover -s tests -v
```

**Test coverage:**

| File | Tests | What is covered |
|------|-------|----------------|
| `tests/test_field_transformations.py` | 63 | All 13 transforms, all date formats, edge cases (empty, invalid, currency symbols), `_lookup_column` (exact, case-insensitive, substring), `apply_transform` (valid + unknown) |
| `tests/test_transformer.py` | 38 | Three-tier resolution priority, `transform_row` outputs, fallback chain, `validate_required_columns` (pass + fail), `inject_extra_tag` (empty, existing, malformed JSON), `first_non_empty` via mapper |
| `tests/test_generate_mapper.py` | 50 | `_score_column` (no match, exact, best wins, case-insensitive, hyphen normalisation), `_find_best_match` (date, cost, transform assignment), `_detect_tag_sources`, `_infer_product_family` (7 vendors), `_infer_tool_name` (from row, from filename), `_infer_default_unit`, full `generate_mapper` (structure, field content, CLI-only exclusions) |
| `tests/test_main.py` | 17 | `_get_input_files` (single file, sorted folder, empty folder, no csvs), `_resolve_output_path` (single-file with/without output_dir, batch path construction, directory auto-creation) |

**Total: 168 tests**

**Test design principles:**
- All transform functions are pure — no I/O, no mocking required
- `MapperDrivenTransformer` is constructed in-memory with fixture mappers
- No filesystem access in unit tests (mapper JSON and schema are inlined as dicts)
- `generate_mapper()` tests use an inline `_FOCUS_SCHEMA` dict

---

## 14. Extension Points

### Adding a new transform function

1. Define in `field_transformations.py`:
   ```python
   def my_transform(value: str, row=None, config=None) -> str:
       return ...
   ```
2. Register: `TRANSFORM_REGISTRY["my_transform"] = my_transform`
3. Reference in any mapper: `{ "transform": "my_transform" }`

### Adding a new SaaS vendor (no code changes)

1. Export the vendor's usage CSV
2. Run `python3 main.py generate --usage_report <csv> --output_mapper mappers/<vendor>_mapper.json`
3. Review and edit the generated mapper
4. Commit to repo

### Adding a new FOCUS column

1. Add to `schemas/focus_schema.json`
2. Add a column to `saas_template.csv`
3. Add semantic patterns to `COLUMN_PATTERNS` in `generate_mapper.py`
4. The engine includes the column automatically

### Claude Code integration

Custom slash command: `.claude/commands/generate-mapper.md`
- Type `/generate-mapper` to have Claude generate a mapper without running Python
- Claude reads `usage_report.csv`, applies the scoring rules, writes `mappers/<tool>_mapper.json`

---

## 15. Known Limitations

| Limitation | Severity | Notes |
|-----------|----------|-------|
| All rows loaded into memory at once | Medium | `rows = list(reader)` — fine for < 1M rows; large files may require chunked streaming |
| One output row per input row (no aggregation) | By design | FOCUS CUR is row-level; aggregation is a reporting concern |
| `_lookup_column` substring match may produce false positives | Low | `"date"` matches any column containing `"date"` (e.g. `"update_date"`) — exact match is tried first |
| Mapper generator uses substring scoring (not ML) | Low | New vendors with unusual column names may need manual mapper corrections |
| No support for multi-sheet Excel input | Low | CSV-only; Excel users must export to CSV first |
| `to_billing_period_end` uses calendar month rollover only | By design | Consistent with FOCUS 1.0 billing period semantics |
