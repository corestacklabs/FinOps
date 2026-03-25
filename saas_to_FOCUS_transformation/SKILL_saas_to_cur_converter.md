---
name: saas-to-cur-converter
description: >
  Mapper-driven pipeline for converting SaaS vendor usage reports (e.g. GitHub Copilot, Anthropic Claude, Datadog) into AWS FOCUS / CUR-compliant cost and usage records. Covers the full pipeline: Mapper Generator → Transformation Engine → FOCUS-Compliant CUR Generator. All vendor logic lives in a declarative mapper.json — zero Python code changes needed to onboard a new SaaS vendor.
---
# Skill: SaaS Usage Report → AWS FOCUS / CUR Converter (v2 — Mapper-Driven)

> **Purpose:** A reusable developer playbook for the mapper-driven SaaS-to-FOCUS
> conversion framework.  This skill covers the full pipeline:
> Mapper Generator → Transformation Engine → FOCUS-Compliant CUR Generator.
>
> **Version 2 key change:** All vendor logic lives in a declarative `mapper.json` file.
> Zero Python code changes are needed to onboard a new SaaS vendor.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Project File Structure](#2-project-file-structure)
3. [FOCUS / CUR Column Reference](#3-focus--cur-column-reference)
4. [Four-Step Pipeline](#4-four-step-pipeline)
5. [Mapper JSON Format — Complete Reference](#5-mapper-json-format--complete-reference)
6. [Mapper Generator — How It Works](#6-mapper-generator--how-it-works)
7. [Transform Function Catalogue](#7-transform-function-catalogue)
8. [Three-Tier Value Resolution](#8-three-tier-value-resolution)
9. [Onboarding a New SaaS Vendor — Step-by-Step](#9-onboarding-a-new-saas-vendor--step-by-step)
10. [CLI Reference](#10-cli-reference)
10a. [AWS S3 Output Destination](#10a-aws-s3-output-destination)
10b. [Python Environment Setup](#10b-python-environment-setup)
11. [Mapper Defaults Section](#11-mapper-defaults-section)
12. [Tag Construction Pattern](#12-tag-construction-pattern)
13. [Cost Column Mapping Rules](#13-cost-column-mapping-rules)
14. [Date Handling Patterns](#14-date-handling-patterns)
15. [Reference Mapper — GitHub Copilot](#15-reference-mapper--github-copilot)
16. [Reference Mapper — Anthropic Claude](#16-reference-mapper--anthropic-claude)
17. [Reference Mapper — Datadog](#17-reference-mapper--datadog)
18. [Reference Mapper — Slack](#18-reference-mapper--slack)
19. [Reference Mapper — Snowflake](#19-reference-mapper--snowflake)
20. [Validation & Error Handling](#20-validation--error-handling)
21. [Testing Checklist](#21-testing-checklist)
22. [Extending the Framework](#22-extending-the-framework)
23. [Quick-Reference Card](#23-quick-reference-card)

---

## Claude Code Usage — Slash Command & Direct Generation

### Slash command (recommended)

A dedicated Claude Code slash command is available at `.claude/commands/generate-mapper.md`.

Type `/generate-mapper` in Claude Code to:
1. Auto-find `usage_report.csv` in the workspace root
2. Generate the mapper JSON and write it to `saas_to_focus_formatter/mappers/<tool_name>_mapper.json`
3. Optionally run the full transform → `focus_cur_output.csv`

You can also pass a specific CSV path: `/generate-mapper path/to/custom_report.csv`

### Default path map

| File / Folder | Resolved path (workspace root = `/Users/deepak/Documents/output/`) | Mode |
|------|---------------------------------------------------------------------|------|
| `usage_report.csv` | `usage_report.csv` | Single-file |
| `usage_reports/` | `usage_reports/` | Batch |
| `saas_template.csv` | `saas_template.csv` | Both |
| mapper output | `saas_to_focus_formatter/mappers/<tool_name>_mapper.json` | Both |
| `focus_cur_output.csv` | `focus_cur_output.csv` | Single-file |
| `focus_cur_outputs/` | `focus_cur_outputs/` | Batch |

### Direct generation (without the slash command)

If you are Claude Code and a user asks you to generate a mapper without using `/generate-mapper`, follow these steps directly — **no Python script required**:

1. **Read `usage_report.csv`** — extract column names and first 5 data rows
2. **Apply semantic scoring** (Section 6) — match source columns → FOCUS columns using `COLUMN_PATTERNS`
3. **Detect tag sources** — columns containing: `username, user, email, org, team, project, repo, workflow, env, cost_center, budget, label, tag`
4. **Infer tool name** — from `product`/`tool`/`service` column value in row 1, or filename stem
5. **Infer ProductFamily** — via `PRODUCT_FAMILY_KEYWORDS`: copilot/github → "Developer Tools", claude/anthropic → "AI / Machine Learning", datadog → "Observability", slack/zoom → "Collaboration", snowflake → "Data & Analytics"
6. **Write the mapper JSON** to `saas_to_focus_formatter/mappers/<tool_name>_mapper.json` (structure: Section 5)

### Reference mappers

| Vendor | Section | ProductFamily |
|--------|---------|---------------|
| GitHub Copilot | Section 15 | Developer Tools |
| Anthropic Claude | Section 16 | AI / Machine Learning |
| Datadog | Section 17 | Observability |
| Slack | Section 18 | Collaboration |
| Snowflake | Section 19 | Data & Analytics |

Use these as templates when `usage_report.csv` matches a known vendor.

---

## 1. Architecture Overview

```
┌─────────────────────────┐
│   SaaS Usage Export     │  (any CSV — Copilot, Claude, Datadog…)
│   usage_report.csv      │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP 1  Mapper Generator  (mapper_generator/generate_mapper.py)   │
│                                                             │
│  ├── Reads CSV headers + sample rows                        │
│  ├── Loads FOCUS schema  (schemas/focus_schema.json)        │
│  ├── Semantic scoring: source columns → FOCUS columns       │
│  ├── Detects tag sources, date columns, cost columns        │
│  └── Emits  mappers/<tool>_mapper.json                      │
└────────────┬────────────────────────────────────────────────┘
             │
             ▼
     mapper.json  ←── declarative: source, transform, fallbacks, statics
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP 2  Transformation Engine  (transform_engine/)         │
│                                                             │
│  transformer.py                                             │
│  ├── Loads mapper.json + FOCUS template schema              │
│  ├── Three-tier resolution per row per column:              │
│  │     Tier 1 — CLI params (always win)                     │
│  │     Tier 2 — Mapper config (source + transform)          │
│  │     Tier 3 — Mapper defaults (static fallbacks)          │
│  └── Calls field_transformations.py for each value          │
│                                                             │
│  field_transformations.py                                   │
│  └── Pure, pluggable transform functions (13 built-in)      │
└────────────┬────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│  STEP 3  FOCUS CUR Generator  (output)                      │
│                                                             │
│  ├── Column order driven by saas_template.csv row 0         │
│  ├── Required columns validated before writing              │
│  ├── Extra tag injection (--tag_key / --tag_value)          │
│  └── Emits  focus_cur_output.csv                            │
└─────────────────────────────────────────────────────────────┘
             │
             ▼
    focus_cur_output.csv  (FOCUS 1.0 compliant)
```

**Core engine files — never need to change:**
- `transform_engine/transformer.py` — three-tier resolver + streaming writer
- `transform_engine/field_transformations.py` — pure transform functions
- `schemas/focus_schema.json` — FOCUS column definitions
- `main.py` — CLI orchestrator

**Extension points — one per SaaS vendor:**
- `mappers/<vendor>_mapper.json` — generated by `generate_mapper.py`, editable

---

## 2. Project File Structure

```
saas_to_focus_formatter/
│
├── main.py                          # CLI: generate | transform | run
│
├── mapper_generator/
│   ├── __init__.py
│   └── generate_mapper.py           # Skill-based mapper generator
│
├── transform_engine/
│   ├── __init__.py
│   ├── transformer.py               # Mapper-driven conversion engine
│   └── field_transformations.py     # Pluggable transform functions
│
├── schemas/
│   └── focus_schema.json            # FOCUS 1.0 column reference
│
├── mappers/                         # Generated/edited mapper files
│   ├── copilot_mapper.json          # GitHub Copilot example
│   └── <vendor>_mapper.json         # Add one per SaaS vendor
│
└── SKILL_saas_to_cur_converter.md   # This file
```

**Shared inputs/outputs (outside the project):**
```
# Single-file mode
saas_template.csv       # FOCUS/CUR output schema template (shared)
usage_report.csv        # SaaS vendor usage export (single file)
focus_cur_output.csv    # Generated FOCUS-compliant output

# Batch mode
usage_reports/          # Folder of SaaS vendor exports
  ├── copilot_march.csv
  ├── copilot_april.csv
  └── claude_march.csv
focus_cur_outputs/      # Output folder (one file per input)
  ├── copilot_march_focus_cur.csv
  ├── copilot_april_focus_cur.csv
  └── claude_march_focus_cur.csv
```

---

## 3. FOCUS / CUR Column Reference

These are the 23 standard columns defined in `schemas/focus_schema.json` and `saas_template.csv`:

| Column | Required | Type | Description |
|--------|----------|------|-------------|
| `ProviderName` | required | string | SaaS provider (e.g. GitHub, Anthropic, Datadog) |
| `BillingAccountId` | required | string | Provider-assigned billing account ID |
| `BillingAccountName` | required | string | Provider-assigned billing account name |
| `BillingCurrency` | required | string | ISO 4217 currency code (e.g. USD) |
| `BillingPeriodEnd` | required | datetime | First instant of next month (`YYYY-MM-01T00:00:00Z`) |
| `BillingPeriodStart` | required | datetime | First instant of current month (`YYYY-MM-01T00:00:00Z`) |
| `BilledCost` | required | decimal | Invoiced cost after discounts |
| `EffectiveCost` | required | decimal | Amortized cost allocated over time |
| `ListCost` | required | decimal | Cost at list price before discounts |
| `ChargeCategory` | required | string | Typically `Usage` |
| `ChargeFrequency` | required | string | Typically `Monthly` |
| `ChargePeriodEnd` | required | datetime | Usage day end (`YYYY-MM-DDT23:59:59Z`) |
| `ChargePeriodStart` | required | datetime | Usage day start (`YYYY-MM-DDT00:00:00Z`) |
| `ServiceName` | required | string | Display name of consumed service |
| `ConsumedQuantity` | optional | decimal | Volume consumed |
| `ConsumedUnit` | optional | string | Unit of measure (Seats, Tokens, Hours…) |
| `RegionName` | optional | string | Geographic region |
| `ResourceId` | optional | string | Unique resource identifier |
| `ResourceName` | optional | string | Human-readable resource name |
| `SkuId` | optional | string | Provider SKU identifier |
| `Tags` | optional | map<string,string> | JSON key-value metadata |
| `UsageType` | optional | string | Category/type of usage |
| `ProductFamily` | optional | string | Product family grouping |

---

## 4. Four-Step Pipeline

### Single-file mode

```bash
# Enter the project folder first
cd saas_to_focus_formatter

Step 1 → Place SaaS usage export at ../usage_report.csv

Step 2 → Generate mapper
         python3 main.py generate \
             --usage_report  ../usage_report.csv \
             --output_mapper mappers/copilot_mapper.json \
             --provider_name "GitHub"

         Output: mappers/copilot_mapper.json
         (review and edit before Step 3 if needed)

Step 3 → Transform
         python3 main.py transform \
             --usage_report         ../usage_report.csv \
             --mapper               mappers/copilot_mapper.json \
             --cur_template         ../saas_template.csv \
             --output               ../focus_cur_output.csv \
             --provider_name        "GitHub" \
             --billing_account_id   "org-corestack" \
             --billing_account_name "CoreStack Engineering"

         Output: ../focus_cur_output.csv

OR use the single-command shortcut:

Step 1+2+3 → python3 main.py run \
             --usage_report         ../usage_report.csv \
             --cur_template         ../saas_template.csv \
             --output               ../focus_cur_output.csv \
             --provider_name        "GitHub" \
             --billing_account_id   "org-corestack" \
             --billing_account_name "CoreStack Engineering"
```

### Batch folder mode

```bash
cd saas_to_focus_formatter

# Place all CSVs in a folder
ls ../usage_reports/
# copilot_march.csv  copilot_april.csv  claude_march.csv

# Run the full pipeline — mapper auto-detected per file
python3 main.py run \
    --usage_dir            ../usage_reports/ \
    --output_dir           ../focus_cur_outputs/ \
    --cur_template         ../saas_template.csv \
    --billing_account_id   "org-corestack" \
    --billing_account_name "CoreStack Engineering"

# Outputs in ../focus_cur_outputs/:
#   copilot_march_focus_cur.csv
#   copilot_april_focus_cur.csv
#   claude_march_focus_cur.csv
```

**Batch mode behaviour:**
- `--usage_dir` and `--usage_report` are mutually exclusive
- Files are processed in alphabetical order
- Each input `<stem>.csv` → `<output_dir>/<stem>_focus_cur.csv`
- In `run` mode, mapper is auto-detected per file via tool name inference
- In `transform` mode, the same `--mapper` is applied to all files
- Progress is logged with `[N/M]` prefix; final line reports total files + rows

---

## 5. Mapper JSON Format — Complete Reference

A mapper.json file has three top-level sections:

```json
{
  "meta": {
    "tool_name":      "copilot",
    "generated_at":   "2026-03-03T10:43:47Z",
    "source_columns": ["date", "product", "sku", "quantity", "..."],
    "focus_version":  "1.0",
    "generator":      "saas_focus_converter/mapper_generator/generate_mapper.py"
  },

  "defaults": {
    "ChargeCategory":  "Usage",
    "ChargeFrequency": "Monthly",
    "BillingCurrency": "USD",
    "ProviderName":    "GitHub"
  },

  "mappings": {
    "BillingPeriodStart": {
      "source":    "date",
      "transform": "to_iso8601_start"
    },
    "BilledCost": {
      "source":           "net_amount",
      "transform":        "identity",
      "fallback_sources": ["gross_amount"],
      "default_value":    "0"
    },
    "Tags": {
      "transform":   "build_tags",
      "tag_sources": ["username", "organization", "repository"]
    },
    "ProductFamily": {
      "transform":    "static",
      "static_value": "Developer Tools"
    }
  }
}
```

### Mapping instruction fields

| Field | Required | Description |
|-------|----------|-------------|
| `source` | usually yes | Source column name from the input CSV (case-insensitive lookup) |
| `transform` | yes | Transform function name (see Section 7) |
| `fallback_sources` | no | List of source columns to try if `source` is empty |
| `default_value` | no | Value to emit if source and all fallbacks are empty |
| `static_value` | no | Emit this fixed string; `source` is ignored (use with `transform: "static"`) |
| `tag_sources` | yes (for `build_tags`) | List of source columns to aggregate into a JSON Tags map |
| `sources` | yes (for `first_non_empty`) | List of source columns; return first non-empty |

---

## 6. Mapper Generator — How It Works

`mapper_generator/generate_mapper.py` uses semantic pattern matching to
automatically map any SaaS CSV to the FOCUS schema:

### Scoring algorithm

For each FOCUS column, the generator scores every source column name using
a catalogue of `(pattern, score, transform)` tuples:

```
score ≥ 10 : high-confidence match  (e.g. "net_amount" → BilledCost)
score 5-9  : likely match           (e.g. "cost" → BilledCost)
score 1-4  : loose/fallback         (e.g. "amount" → BilledCost)
```

The highest-scoring source column wins and is written to `mappings`.

### Special detection logic

| Situation | Behaviour |
|-----------|-----------|
| Date columns | Detected by pattern ("date", "timestamp", "period_start"…) → assigned appropriate date transform |
| Cost columns | BilledCost ← "net_amount" > "billed_cost" > "total_cost" > "cost" |
| ListCost | ListCost ← "gross_amount" > "list_price" > "retail_cost" |
| Tag sources | All "contextual" columns (username, org, team, project, repo, env…) collected into `tag_sources` |
| ProductFamily | Inferred from tool name via `PRODUCT_FAMILY_KEYWORDS` dict |
| ProviderName | Written to `defaults` section (from `--provider_name` CLI arg) |

### Running the generator standalone

```bash
cd saas_to_focus_formatter
python3 mapper_generator/generate_mapper.py \
    --usage_report  ../usage_report.csv \
    --schema        schemas/focus_schema.json \
    --output        mappers/my_tool_mapper.json \
    --tool_name     my_tool \
    --provider_name "My Provider" \
    --product_family "Developer Tools"
```

---

## 7. Transform Function Catalogue

All transform functions live in `transform_engine/field_transformations.py`.
Reference them by name in mapper.json `"transform"` fields.

| Name | Input → Output | Example |
|------|---------------|---------|
| `identity` | value → value unchanged | `"0.612903"` → `"0.612903"` |
| `to_iso8601_start` | date string → `YYYY-MM-DDT00:00:00Z` | `"2026-03-01"` → `"2026-03-01T00:00:00Z"` |
| `to_iso8601_end` | date string → `YYYY-MM-DDT23:59:59Z` | `"2026-03-01"` → `"2026-03-01T23:59:59Z"` |
| `to_billing_period_end` | date string → first instant of next month | `"2026-03-01"` → `"2026-04-01T00:00:00Z"` |
| `humanize` | `snake_case` / `kebab-case` → Title Case | `"copilot_for_business"` → `"Copilot For Business"` |
| `title_case` | string → Title Case (no symbol replacement) | `"developer tools"` → `"Developer Tools"` |
| `to_uppercase` | string → UPPERCASE | `"usd"` → `"USD"` |
| `to_lowercase` | string → lowercase | `"USD"` → `"usd"` |
| `strip_whitespace` | string → trimmed | `"  foo  "` → `"foo"` |
| `to_decimal` | numeric string → decimal string (cleans commas/symbols) | `"$1,234.56"` → `"1234.56"` |
| `build_tags` | multiple source columns → compact JSON map | `{"username":"alice","org":"CoreStack"}` |
| `static` | ignored → `config["static_value"]` | `"Developer Tools"` |
| `first_non_empty` | multiple source columns → first non-empty value | tries `col_a`, `col_b`, `col_c` in order |

### Adding a new transform

1. Define the function in `field_transformations.py`:
   ```python
   def my_transform(value: str, row=None, config=None) -> str:
       return value.replace("old", "new")
   ```
2. Register it:
   ```python
   TRANSFORM_REGISTRY["my_transform"] = my_transform
   ```
3. Reference in any mapper.json:
   ```json
   { "source": "some_col", "transform": "my_transform" }
   ```
No other changes needed.

---

## 8. Three-Tier Value Resolution

For every FOCUS column in every output row, `transformer.py` resolves the
value in strict priority order:

```
Tier 1 — CLI Parameters (always win)
    Passed via --provider_name, --billing_account_id, etc.
    Map to: ProviderName, BillingAccountId, BillingAccountName,
            BillingCurrency, RegionName, ChargeCategory, ChargeFrequency

Tier 2 — Mapper "mappings" section
    Per-column instructions with source, transform, fallbacks.
    Covers all tool-specific field derivations.

Tier 3 — Mapper "defaults" section
    Static default values for columns not in "mappings".
    e.g. "ChargeCategory": "Usage", "BillingCurrency": "USD"

Fallback — Empty string (never None; no column is absent from output)
```

**Key insight:** CLI params override everything.  Mapper mappings handle
per-row derivations.  Defaults handle static/global values.

---

## 9. Onboarding a New SaaS Vendor — Step-by-Step

### Prerequisites
- The vendor's usage export CSV (any column names, any structure)
- `saas_template.csv` (FOCUS output schema — unchanged across all vendors)

### Step 1 — Inspect the export

Open the CSV and note:
- Date column(s)
- Cost column(s): net/billed, gross/list
- Quantity and unit columns
- Resource identifier columns (user, workspace, project…)
- Tag-worthy contextual columns

### Step 2 — Generate the mapper

```bash
cd saas_to_focus_formatter
python3 main.py generate \
    --usage_report  ../vendor_export.csv \
    --output_mapper mappers/vendor_mapper.json \
    --tool_name     "vendor" \
    --provider_name "Vendor Inc."
```

### Step 3 — Review and refine

Open `mappers/vendor_mapper.json` and verify:

| Check | What to look for |
|-------|-----------------|
| Date columns | `BillingPeriodStart/End`, `ChargePeriodStart/End` all mapped and using correct transforms |
| Cost columns | `BilledCost` ← net/billed, `ListCost` ← gross/list, `EffectiveCost` = BilledCost for most SaaS |
| Tags | `tag_sources` contains all contextual columns |
| Static values | `ProductFamily` and `defaults` look sensible |
| Missing columns | Any important FOCUS column not in `mappings`? Add it manually |

### Step 4 — Run the full pipeline

```bash
python3 main.py transform \
    --usage_report         ../vendor_export.csv \
    --mapper               mappers/vendor_mapper.json \
    --cur_template         ../saas_template.csv \
    --output               ../vendor_focus_cur.csv \
    --provider_name        "Vendor Inc." \
    --billing_account_id   "acct-12345" \
    --billing_account_name "My Org"
```

### Step 5 — Verify with the Testing Checklist (Section 21)

---

## 10. CLI Reference

### `main.py generate` — Mapper generation (single file only)

```
--usage_report   Path to SaaS usage export CSV           [required]
--schema         Path to focus_schema.json               [default: schemas/focus_schema.json]
--output_mapper  Output mapper.json path                 [default: mappers/<tool>_mapper.json]
--tool_name      Override tool name detection            [optional]
--provider_name  ProviderName written to defaults        [optional]
--product_family ProductFamily static value              [optional, auto-inferred]
--billing_currency  Currency code                        [default: USD]
```

### `main.py transform` — Conversion (single file or batch folder)

```
Input (mutually exclusive):
--usage_report   Single SaaS export CSV                  [one of these is required]
--usage_dir      Folder of CSVs (batch mode)             [one of these is required]

--mapper             Path to mapper.json                 [required]
--cur_template       Path to saas_template.csv           [default: ../saas_template.csv]

Output:
--output             Output CSV path (single-file mode)  [default: focus_cur_output.csv]
--output_dir         Output folder (batch mode)          [optional]

Overrides:
--provider_name      Tier-1 override for ProviderName    [optional]
--billing_account_id     Billing account ID              [optional]
--billing_account_name   Billing account name            [optional]
--billing_currency   Currency code                       [default: USD]
--region_name        Geographic region                   [optional]
--tag_key / --tag_value  Extra tag injected into all rows [optional]
--skip_validation    Skip required-field pre-check       [flag]

S3 output (optional — requires pip install boto3):
--s3_bucket          S3 bucket name; enables upload      [optional]
--s3_prefix          Key prefix / folder path in bucket  [optional]
--s3_region          AWS region for the bucket            [optional]
--s3_profile         AWS named credentials profile        [optional]
```

### `main.py run` — Full pipeline (single file or batch folder)

All flags from `generate` + `transform`.  Additional:
```
--mapper             Use existing mapper for all files (skips detection/generation) [optional]
--regenerate_mapper  Force re-generation even if mapper.json exists                 [flag]
```

**Batch mapper auto-detection (run mode, no --mapper specified):**
For each file, `_infer_tool_name()` derives the tool from the file's columns.
`mappers/<tool>_mapper.json` is then used (auto-generated if missing).

---

## 10a. AWS S3 Output Destination

The framework can upload each output CSV to an S3 bucket immediately after writing it locally.
Both destinations are active simultaneously — the local file is always kept.

### Activation

Set `bucket` in `config.ini [s3]` **or** pass `--s3_bucket` on the CLI.
Credentials are **never stored in config**; the standard boto3 chain is used.

### Configuration

```ini
[s3]
bucket  = my-finops-bucket        # required — enables S3 upload
prefix  = focus-cur-outputs/      # key prefix (folder path) within the bucket
region  = us-east-1               # optional; uses AWS SDK default if omitted
profile = default                 # optional; named profile from ~/.aws/credentials
```

### Credential resolution order (standard boto3 chain)

1. Environment variables: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`
2. `~/.aws/credentials` — named profile via `s3.profile` (defaults to `[default]`)
3. IAM instance role / ECS task role / AWS SSO

### S3 key naming

```
s3://<bucket>/<prefix>/<output_filename>

Example:
  prefix = focus-cur-outputs/
  file   = copilot_january_2026_focus_cur.csv
  key    = focus-cur-outputs/copilot_january_2026_focus_cur.csv
```

### Example invocations

```bash
# Via config.ini (set [s3] bucket + prefix)
python3 main.py run

# Via CLI flags
python3 main.py run \
    --s3_bucket  my-finops-bucket \
    --s3_prefix  focus-cur-outputs/ \
    --s3_region  us-east-1

# With a specific AWS credentials profile
python3 main.py run \
    --s3_bucket  my-finops-bucket \
    --s3_profile finops-prod
```

### Behaviour notes

| Behaviour | Detail |
|-----------|--------|
| Local file | Always written first; S3 upload is additive |
| S3 upload failure | Logged as WARNING; file not marked failed in `run_state.json` |
| boto3 missing | Raises `ImportError` with `pip install boto3` instruction |
| Credentials missing | `NoCredentialsError` from boto3; warning logged, run continues |

---

## 10b. Python Environment Setup

On macOS (Homebrew Python), running `pip install` system-wide is blocked by PEP 668.
Always use a virtual environment inside the project directory.

### First-time setup

```bash
cd saas_to_focus_formatter
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Every subsequent session

```bash
source .venv/bin/activate
```

### S3 / boto3 (optional dependency)

boto3 is not in `requirements.txt` by default. Install it inside the venv:

```bash
pip install boto3
```

Then configure credentials at `~/.aws/credentials`:

```ini
[default]
aws_access_key_id     = YOUR_ACCESS_KEY
aws_secret_access_key = YOUR_SECRET_KEY
```

Create the file if it doesn't exist:

```bash
mkdir -p ~/.aws
nano ~/.aws/credentials   # Ctrl+O → Enter to save, Ctrl+X to exit
```

---

## 11. Mapper Defaults Section

The `"defaults"` section provides Tier-3 static fallbacks for columns not
covered by `"mappings"`.  Common pattern:

```json
"defaults": {
  "ChargeCategory":  "Usage",
  "ChargeFrequency": "Monthly",
  "BillingCurrency": "USD",
  "ProviderName":    "GitHub",
  "RegionName":      "Global"
}
```

**Note:** Values in `"defaults"` are overridden by Tier-1 CLI params.
Use `"defaults"` for values that are always static for the vendor
(not row-specific).

---

## 12. Tag Construction Pattern

Tags must be a JSON string (`map<string,string>`).  Use the `build_tags` transform:

```json
"Tags": {
  "transform": "build_tags",
  "tag_sources": ["username", "organization", "repository", "workflow_path", "cost_center_name"]
}
```

The `build_tags` function:
- Looks up each column case-insensitively
- Excludes `null` / empty values automatically
- Outputs compact JSON: `{"username":"alice","organization":"CoreStack-Engg"}`

For explicit key renaming (tag key ≠ column name), use list-of-pairs format:

```json
"tag_sources": [
  ["user",  "username"],
  ["org",   "organization"],
  ["repo",  "repository"]
]
```

Output: `{"user":"alice","org":"CoreStack-Engg","repo":"api-gateway"}`

### Injecting an extra tag via CLI

```bash
python3 main.py transform ... --tag_key env --tag_value prod
```

Adds `"env":"prod"` to every row's Tags without modifying the mapper.

---

## 13. Cost Column Mapping Rules

| FOCUS Column | Source Column Priority | Notes |
|-------------|----------------------|-------|
| `BilledCost` | `net_amount` > `billed_cost` > `invoice_amount` > `total_cost` > `cost` | After discounts |
| `EffectiveCost` | Same as BilledCost | = BilledCost for most SaaS (no amortization) |
| `ListCost` | `gross_amount` > `list_cost` > `list_price` > `retail_cost` > `total_cost` | Before discounts |

**When there's only one cost column** (no discount breakdown):
```json
"BilledCost":    { "source": "cost",  "transform": "identity" },
"EffectiveCost": { "source": "cost",  "transform": "identity" },
"ListCost":      { "source": "cost",  "transform": "identity" }
```

**When rows are fully discounted** (e.g. Copilot premium requests with `net_amount=0`):
The mapper correctly emits `BilledCost=0` from `net_amount` — no special handling needed.

---

## 14. Date Handling Patterns

### For daily-granularity reports (most SaaS tools)

```json
"BillingPeriodStart": { "source": "date", "transform": "to_iso8601_start" },
"BillingPeriodEnd":   { "source": "date", "transform": "to_billing_period_end" },
"ChargePeriodStart":  { "source": "date", "transform": "to_iso8601_start" },
"ChargePeriodEnd":    { "source": "date", "transform": "to_iso8601_end" }
```

### For monthly-summary reports (one row per billing period)

```json
"BillingPeriodStart": { "source": "billing_start", "transform": "to_iso8601_start" },
"BillingPeriodEnd":   { "source": "billing_start",  "transform": "to_billing_period_end" },
"ChargePeriodStart":  { "source": "billing_start",  "transform": "to_iso8601_start" },
"ChargePeriodEnd":    { "source": "billing_end",    "transform": "to_iso8601_end" }
```

### Supported input date formats

The engine auto-detects these formats:
- `YYYY-MM-DD`
- `YYYY-MM-DDThh:mm:ssZ`
- `YYYY-MM-DDThh:mm:ss`
- `YYYY/MM/DD`
- `MM/DD/YYYY`
- `DD-MM-YYYY`
- `YYYY-MM-DDThh:mm:ss.fffZ`

---

## 15. Reference Mapper — GitHub Copilot

**Source columns:** `date, product, sku, quantity, unit_type, applied_cost_per_quantity, gross_amount, discount_amount, net_amount, username, organization, repository, workflow_path, cost_center_name`

**Key mappings:**

```json
{
  "meta": { "tool_name": "copilot" },
  "defaults": {
    "ChargeCategory": "Usage", "ChargeFrequency": "Monthly",
    "BillingCurrency": "USD", "ProviderName": "GitHub"
  },
  "mappings": {
    "BillingPeriodStart": { "source": "date", "transform": "to_iso8601_start" },
    "BillingPeriodEnd":   { "source": "date", "transform": "to_billing_period_end" },
    "ChargePeriodStart":  { "source": "date", "transform": "to_iso8601_start" },
    "ChargePeriodEnd":    { "source": "date", "transform": "to_iso8601_end" },
    "ServiceName":        { "source": "product", "transform": "humanize" },
    "SkuId":              { "source": "sku",     "transform": "identity" },
    "UsageType":          { "source": "sku",     "transform": "humanize",
                            "fallback_sources": ["unit_type"] },
    "ProductFamily":      { "transform": "static", "static_value": "Developer Tools" },
    "ConsumedQuantity":   { "source": "quantity",  "transform": "identity" },
    "ConsumedUnit":       { "source": "unit_type", "transform": "identity",
                            "default_value": "user-months" },
    "BilledCost":         { "source": "net_amount",   "transform": "identity",
                            "fallback_sources": ["gross_amount"], "default_value": "0" },
    "EffectiveCost":      { "source": "net_amount",   "transform": "identity",
                            "fallback_sources": ["gross_amount"], "default_value": "0" },
    "ListCost":           { "source": "gross_amount", "transform": "identity",
                            "fallback_sources": ["net_amount"], "default_value": "0" },
    "ResourceId":         { "source": "username",     "transform": "identity",
                            "fallback_sources": ["organization"] },
    "ResourceName":       { "source": "username",     "transform": "identity",
                            "fallback_sources": ["organization"] },
    "Tags": {
      "transform": "build_tags",
      "tag_sources": ["username", "organization", "repository", "workflow_path", "cost_center_name"]
    }
  }
}
```

---

## 16. Reference Mapper — Anthropic Claude

**Hypothetical source columns:** `usage_date, model, usage_type, input_tokens, output_tokens, total_tokens, total_cost, workspace_name, organization`

```json
{
  "meta": { "tool_name": "claude" },
  "defaults": {
    "ChargeCategory": "Usage", "ChargeFrequency": "Monthly",
    "BillingCurrency": "USD", "ProviderName": "Anthropic"
  },
  "mappings": {
    "BillingPeriodStart": { "source": "usage_date", "transform": "to_iso8601_start" },
    "BillingPeriodEnd":   { "source": "usage_date", "transform": "to_billing_period_end" },
    "ChargePeriodStart":  { "source": "usage_date", "transform": "to_iso8601_start" },
    "ChargePeriodEnd":    { "source": "usage_date", "transform": "to_iso8601_end" },
    "ServiceName":        { "transform": "static",  "static_value": "Claude" },
    "SkuId":              { "source": "model",       "transform": "identity" },
    "UsageType":          { "source": "usage_type",  "transform": "humanize",
                            "fallback_sources": ["model"] },
    "ProductFamily":      { "transform": "static",   "static_value": "AI / Machine Learning" },
    "ConsumedQuantity":   { "source": "total_tokens", "transform": "identity",
                            "fallback_sources": ["input_tokens"] },
    "ConsumedUnit":       { "transform": "static",   "static_value": "Tokens" },
    "BilledCost":         { "source": "total_cost",  "transform": "identity", "default_value": "0" },
    "EffectiveCost":      { "source": "total_cost",  "transform": "identity", "default_value": "0" },
    "ListCost":           { "source": "total_cost",  "transform": "identity", "default_value": "0" },
    "ResourceId":         { "source": "workspace_name", "transform": "identity" },
    "ResourceName":       { "source": "workspace_name", "transform": "identity" },
    "Tags": {
      "transform": "build_tags",
      "tag_sources": [["workspace", "workspace_name"], ["model", "model"], ["org", "organization"]]
    }
  }
}
```

---

## 17. Reference Mapper — Datadog

**Hypothetical source columns:** `period_start, product_name, sku_name, usage_qty, unit, cost_usd, list_price, host_name, org_name`

```json
{
  "meta": { "tool_name": "datadog" },
  "defaults": {
    "ChargeCategory": "Usage", "ChargeFrequency": "Monthly",
    "BillingCurrency": "USD", "ProviderName": "Datadog"
  },
  "mappings": {
    "BillingPeriodStart": { "source": "period_start", "transform": "to_iso8601_start" },
    "BillingPeriodEnd":   { "source": "period_start", "transform": "to_billing_period_end" },
    "ChargePeriodStart":  { "source": "period_start", "transform": "to_iso8601_start" },
    "ChargePeriodEnd":    { "source": "period_start", "transform": "to_iso8601_end" },
    "ServiceName":        { "source": "product_name", "transform": "humanize" },
    "SkuId":              { "source": "sku_name",     "transform": "identity" },
    "UsageType":          { "source": "sku_name",     "transform": "humanize" },
    "ProductFamily":      { "transform": "static",    "static_value": "Observability" },
    "ConsumedQuantity":   { "source": "usage_qty",    "transform": "identity" },
    "ConsumedUnit":       { "source": "unit",         "transform": "identity",
                            "default_value": "Events" },
    "BilledCost":         { "source": "cost_usd",     "transform": "identity", "default_value": "0" },
    "EffectiveCost":      { "source": "cost_usd",     "transform": "identity", "default_value": "0" },
    "ListCost":           { "source": "list_price",   "transform": "identity",
                            "fallback_sources": ["cost_usd"], "default_value": "0" },
    "ResourceId":         { "source": "host_name",    "transform": "identity" },
    "ResourceName":       { "source": "host_name",    "transform": "identity" },
    "Tags": {
      "transform": "build_tags",
      "tag_sources": [["host", "host_name"], ["org", "org_name"]]
    }
  }
}
```

---

## 18. Reference Mapper — Slack

**Typical source columns:** `date, product, quantity, unit, total_cost, workspace_name, team_name, channel_name`

```json
{
  "meta": { "tool_name": "slack" },
  "defaults": {
    "ChargeCategory": "Usage", "ChargeFrequency": "Monthly",
    "BillingCurrency": "USD", "ProviderName": "Slack"
  },
  "mappings": {
    "BillingPeriodStart": { "source": "date",       "transform": "to_iso8601_start" },
    "BillingPeriodEnd":   { "source": "date",       "transform": "to_billing_period_end" },
    "ChargePeriodStart":  { "source": "date",       "transform": "to_iso8601_start" },
    "ChargePeriodEnd":    { "source": "date",       "transform": "to_iso8601_end" },
    "ServiceName":        { "source": "product",    "transform": "humanize",
                            "default_value": "Slack" },
    "SkuId":              { "source": "product",    "transform": "identity" },
    "UsageType":          { "source": "product",    "transform": "humanize" },
    "ProductFamily":      { "transform": "static",  "static_value": "Collaboration" },
    "ConsumedQuantity":   { "source": "quantity",   "transform": "identity" },
    "ConsumedUnit":       { "source": "unit",       "transform": "identity",
                            "default_value": "Seats" },
    "BilledCost":         { "source": "total_cost", "transform": "identity", "default_value": "0" },
    "EffectiveCost":      { "source": "total_cost", "transform": "identity", "default_value": "0" },
    "ListCost":           { "source": "total_cost", "transform": "identity", "default_value": "0" },
    "ResourceId":         { "source": "workspace_name", "transform": "identity" },
    "ResourceName":       { "source": "workspace_name", "transform": "identity" },
    "Tags": {
      "transform": "build_tags",
      "tag_sources": [["workspace", "workspace_name"], ["team", "team_name"], ["channel", "channel_name"]]
    }
  }
}
```

---

## 19. Reference Mapper — Snowflake

**Typical source columns:** `usage_date, service_type, credits_used, credits_billed, credits_attributed_compute, storage_bytes, warehouse_name, account_name, region`

```json
{
  "meta": { "tool_name": "snowflake" },
  "defaults": {
    "ChargeCategory": "Usage", "ChargeFrequency": "Monthly",
    "BillingCurrency": "USD", "ProviderName": "Snowflake"
  },
  "mappings": {
    "BillingPeriodStart": { "source": "usage_date",     "transform": "to_iso8601_start" },
    "BillingPeriodEnd":   { "source": "usage_date",     "transform": "to_billing_period_end" },
    "ChargePeriodStart":  { "source": "usage_date",     "transform": "to_iso8601_start" },
    "ChargePeriodEnd":    { "source": "usage_date",     "transform": "to_iso8601_end" },
    "ServiceName":        { "source": "service_type",   "transform": "humanize",
                            "default_value": "Snowflake" },
    "SkuId":              { "source": "service_type",   "transform": "identity" },
    "UsageType":          { "source": "service_type",   "transform": "humanize" },
    "ProductFamily":      { "transform": "static",      "static_value": "Data & Analytics" },
    "ConsumedQuantity":   { "source": "credits_used",   "transform": "identity",
                            "fallback_sources": ["credits_billed"] },
    "ConsumedUnit":       { "transform": "static",      "static_value": "Credits" },
    "BilledCost":         { "source": "credits_billed", "transform": "identity",
                            "fallback_sources": ["credits_used"], "default_value": "0" },
    "EffectiveCost":      { "source": "credits_billed", "transform": "identity",
                            "fallback_sources": ["credits_used"], "default_value": "0" },
    "ListCost":           { "source": "credits_billed", "transform": "identity",
                            "fallback_sources": ["credits_used"], "default_value": "0" },
    "RegionName":         { "source": "region",         "transform": "identity" },
    "ResourceId":         { "source": "warehouse_name", "transform": "identity" },
    "ResourceName":       { "source": "warehouse_name", "transform": "identity" },
    "Tags": {
      "transform": "build_tags",
      "tag_sources": [["warehouse", "warehouse_name"], ["account", "account_name"]]
    }
  }
}
```

---

## 20. Validation & Error Handling

### Required-column validation

Before writing any rows, the engine runs `validate_required_columns()` against
the first data row.  If any of the 14 required FOCUS columns would be empty,
it raises a descriptive `ValueError`:

```
ValueError: The following required FOCUS columns are empty for at least one row
  (check mapper, CLI params, and input CSV):
  BillingAccountId, BillingAccountName
```

**Fix:** Pass `--billing_account_id` and `--billing_account_name` via CLI, or
add them to the mapper's `"defaults"` section.

Skip validation (for debugging): `--skip_validation`

### Unknown transform

```
ValueError: Unknown transform: 'my_typo'. Available: [build_tags, humanize, ...]
```

**Fix:** Correct the transform name in mapper.json, or add the function to
`TRANSFORM_REGISTRY` in `field_transformations.py`.

### Missing mapper file

```
FileNotFoundError: Mapper file not found: mappers/vendor_mapper.json
Run mapper_generator/generate_mapper.py first to auto-generate it.
```

### Invalid date string

```
WARNING  Could not parse date string: '2026-31-03'
```

The engine emits an empty string for that field and continues.  Investigate
the source data format and confirm it matches a supported format (Section 14).

### Schema mismatch

If the mapper references a source column that doesn't exist in the input CSV,
`_lookup_column()` returns an empty string.  For required columns this triggers
the validation error above.

### Inline comments in config.ini polluting CSV output

**Symptom:** Output CSV contains values like `USD      # ISO 4217 code  (built-in default: USD)`
or `global   # geographic region (built-in default: global)` instead of just `USD` / `global`.

**Cause:** Python's `configparser` does not strip inline `#` comments by default.
Any `# ...` text after a value in `config.ini` is included in the value.

**Fix (code):** Pass `inline_comment_prefixes=('#',)` when constructing the parser in `main.py`:

```python
cfg = configparser.ConfigParser(inline_comment_prefixes=('#',))
```

**Fix (config):** Remove inline comments from `config.ini` values entirely:

```ini
# Before (broken)
billing_currency = USD      # ISO 4217 code  (built-in default: USD)
region_name      = global   # geographic region (built-in default: global)

# After (correct)
billing_currency = USD
region_name      = global
```

**Fix (mapper):** If a mapper JSON was already generated with the polluted values,
manually correct the `"defaults"` section:

```json
"BillingCurrency": "USD"
```

---

## 21. Testing Checklist

Run after every new mapper or after modifying an existing one:

### Schema
- [ ] Output CSV has exactly the same columns as `saas_template.csv` row 0
- [ ] Column order matches the template

### Required columns (never empty)
- [ ] `ProviderName` — from `--provider_name` or mapper defaults
- [ ] `BillingAccountId` — from `--billing_account_id`
- [ ] `BillingAccountName` — from `--billing_account_name`
- [ ] `BillingCurrency` — filled (default: `USD`)
- [ ] `BillingPeriodStart` — valid ISO-8601 `T00:00:00Z`
- [ ] `BillingPeriodEnd` — first instant of NEXT month
- [ ] `BilledCost` — numeric string
- [ ] `EffectiveCost` — numeric string
- [ ] `ListCost` — numeric string
- [ ] `ChargeCategory` — typically `Usage`
- [ ] `ChargeFrequency` — typically `Monthly`
- [ ] `ChargePeriodStart` — valid ISO-8601 `T00:00:00Z`
- [ ] `ChargePeriodEnd` — valid ISO-8601 `T23:59:59Z`
- [ ] `ServiceName` — non-empty, human-readable

### Dates
- [ ] `BillingPeriodEnd` is `YYYY-04-01T00:00:00Z` for March data (next month)
- [ ] `ChargePeriodStart` and `ChargePeriodEnd` are on the same calendar day
- [ ] No raw date strings without a time suffix in output

### Tags
- [ ] `Tags` column is valid, compact JSON (no trailing commas, all keys quoted)
- [ ] No `null` or `None` values in Tags JSON
- [ ] If `--tag_key` / `--tag_value` were used, the tag appears in every row

### Costs
- [ ] `BilledCost` ≤ `ListCost` (after discounts)
- [ ] `EffectiveCost` = `BilledCost` (for standard SaaS tools)
- [ ] Fully-discounted rows show `BilledCost=0` with `ListCost > 0`

### Row count
- [ ] Output row count = input row count (1-to-1)
- [ ] No duplicate rows

### Console output
- [ ] `INFO  Mapper loaded: tool='...'`
- [ ] `INFO  Validation passed — all required columns are populated.`
- [ ] `INFO  Conversion complete: N rows → <output path>`

---

## 22. Extending the Framework

### Adding a new transform function

```python
# field_transformations.py

def to_kilobytes(value: str, row=None, config=None) -> str:
    """Convert bytes to kilobytes."""
    try:
        return str(round(float(value) / 1024, 4))
    except ValueError:
        return value

TRANSFORM_REGISTRY["to_kilobytes"] = to_kilobytes
```

Reference in mapper.json:
```json
{ "source": "bytes_used", "transform": "to_kilobytes" }
```

### Adding a new SaaS vendor

1. Export the vendor's usage CSV
2. `cd saas_to_focus_formatter` then run `python3 main.py generate --usage_report ../vendor.csv --output_mapper mappers/vendor_mapper.json`
3. Review and edit the mapper if needed
4. Run `python3 main.py transform ...`
5. No engine code changes required

### Supporting a new FOCUS column

1. Add the column to `schemas/focus_schema.json`
2. Add a corresponding row to `saas_template.csv`
3. Add semantic patterns to `COLUMN_PATTERNS` in `generate_mapper.py`
4. The engine automatically includes the new column in all output rows

### Batch processing multiple vendors

```bash
cd saas_to_focus_formatter
for vendor in copilot claude datadog; do
    python3 main.py run \
        --usage_report         "../${vendor}_usage.csv" \
        --cur_template         ../saas_template.csv \
        --output               "../${vendor}_focus_cur.csv" \
        --provider_name        "$(echo $vendor | sed 's/./\u&/')" \
        --billing_account_id   "acct-${vendor}" \
        --billing_account_name "CoreStack Engineering"
done
```

---

## 23. Quick-Reference Card

```
New SaaS Vendor in 3 Commands
──────────────────────────────────────────────────────────────────
cd saas_to_focus_formatter

1. Generate mapper:
   python3 main.py generate \
       --usage_report  ../vendor.csv \
       --output_mapper mappers/vendor_mapper.json \
       --provider_name "Vendor Inc."

2. Review mappers/vendor_mapper.json
   (Edit source columns / transforms / tag_sources if needed)

3. Convert:
   python3 main.py transform \
       --usage_report         ../vendor.csv \
       --mapper               mappers/vendor_mapper.json \
       --cur_template         ../saas_template.csv \
       --output               ../vendor_focus_cur.csv \
       --billing_account_id   "acct-123" \
       --billing_account_name "My Org"
──────────────────────────────────────────────────────────────────
OR one-command pipeline:
   python3 main.py run \
       --usage_report         ../vendor.csv \
       --cur_template         ../saas_template.csv \
       --output               ../vendor_focus_cur.csv \
       --provider_name        "Vendor Inc." \
       --billing_account_id   "acct-123" \
       --billing_account_name "My Org"
──────────────────────────────────────────────────────────────────
S3 upload (add to any run/transform command, or set in config.ini [s3]):
   python3 main.py run \
       --s3_bucket  my-finops-bucket \
       --s3_prefix  focus-cur-outputs/ \
       --s3_region  us-east-1
   (requires: pip install boto3 + AWS credentials configured)
──────────────────────────────────────────────────────────────────

Transform functions available in mapper.json "transform" field:
  identity              to_iso8601_start      to_iso8601_end
  to_billing_period_end humanize              title_case
  to_uppercase          to_lowercase          strip_whitespace
  to_decimal            build_tags            static
  first_non_empty

Mapper.json structure at a glance:
  {
    "meta":     { "tool_name": "...", "source_columns": [...] },
    "defaults": { "ChargeCategory": "Usage", "BillingCurrency": "USD" },
    "mappings": {
      "BillingPeriodStart": { "source": "date",       "transform": "to_iso8601_start" },
      "BilledCost":         { "source": "net_amount", "transform": "identity",
                              "fallback_sources": ["cost"], "default_value": "0" },
      "Tags":               { "transform": "build_tags",
                              "tag_sources": ["username", "org", "project"] },
      "ProductFamily":      { "transform": "static", "static_value": "My Category" }
    }
  }
──────────────────────────────────────────────────────────────────
```
