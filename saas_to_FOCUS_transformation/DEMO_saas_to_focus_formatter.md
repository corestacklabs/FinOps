# SaaS → FOCUS/CUR Converter — Complete Demo Guide

A presenter-ready walkthrough of every feature in `saas_to_focus_formatter`.
Run each command block live in the terminal as you walk through the sections.

---

## Quick Reference Card

```
COMMANDS (run from inside saas_to_focus_formatter/)
─────────────────────────────────────────────────────────────────────────────
python3 main.py generate   --usage_report FILE              # CSV → mapper JSON
python3 main.py transform  --usage_report FILE --mapper JSON # CSV + mapper → FOCUS CSV
python3 main.py run                                         # full pipeline from config.ini
python3 main.py run --resume                                # skip already-done files
python3 main.py run --max_retries 3                         # retry failed files 3×
python3 main.py run --config /path/to/other.ini             # use a different config
python3 main.py run --provider_name "Acme" --billing_currency EUR  # override any value
python3 main.py run --s3_bucket my-bucket --s3_prefix focus/ # also upload to S3

PRIORITY ORDER (high → low)
─────────────────────────────────────────────────────────────────────────────
  CLI argument  >  config.ini  >  built-in default (USD / global / Usage / Monthly)

KEY FILES
─────────────────────────────────────────────────────────────────────────────
  saas_to_focus_formatter/
    main.py              CLI entry point
    config.ini           All your settings (paths, billing, mapper, logging, s3)
    mappers/*.json       One mapper per vendor
    logs/latest.log      Full log of the last run (overwritten each run)
    logs/run_state.json  Per-file checkpoint (used by --resume)

  One level above:
    usage_reports/*.csv          Your SaaS vendor exports (input)
    saas_template.csv            FOCUS/CUR column template
    focus_cur_outputs/*.csv      Generated outputs

EXIT CODES
─────────────────────────────────────────────────────────────────────────────
  0  all files succeeded
  2  partial failure — at least one file failed
  1  bad arguments
```

---

## 1. What Is This Project?

### The Problem

Every SaaS vendor exports billing data in their own CSV format:

| Vendor | Columns |
|--------|---------|
| GitHub Copilot | `date, product, sku, quantity, net_amount, username, organization, …` |
| Anthropic Claude | `date, model, input_tokens, output_tokens, cost_usd, team_name, …` |
| Datadog | `usage_date, product_type, billable_usage, price_per_unit, …` |
| Snowflake | `usage_date, service_type, credits_used, warehouse_name, …` |

FinOps platforms (AWS Cost Explorer, CloudZero, Apptio, etc.) expect data in the
**FOCUS 1.0 / CUR schema** — a standardized set of ~20 columns with specific names,
date formats, and value types.

### The Solution

A **mapper-driven transform engine**:

1. You write a `mapper.json` once per vendor — a JSON file that says "my `net_amount` column
   maps to FOCUS `BilledCost`, apply no transform; my `date` column maps to `BillingPeriodStart`,
   parse it to ISO 8601."
2. The transform engine reads the mapper and converts any CSV that matches the schema.
3. To add a new vendor, you never touch Python — just run `generate` on their CSV.

### Key Concepts

| Concept | What It Means |
|---------|--------------|
| **FOCUS schema** | ~20 standardized columns expected by FinOps tools |
| **Mapper JSON** | One file per vendor; defines how source columns → FOCUS columns |
| **Transform function** | Named function (e.g. `humanize`, `to_iso8601_start`) applied to a value |
| **Three-tier priority** | CLI arg wins over config.ini, which wins over built-in default |
| **Batch mode** | Process every `*.csv` in a folder in one command |
| **Resume** | Checkpoint-backed: skip files that already succeeded in a previous run |

---

## 2. Architecture Overview

```
  INPUT
  ─────
  usage_reports/
    copilot_january_2026.csv   ─┐
    copilot_february_2026.csv  ─┤
    copilot_march_2026.csv     ─┤──► mapper_generator/
    copilot_april_2026.csv     ─┤      generate_mapper.py
    copilot_may_2026.csv       ─┤       (auto-scores columns,
    copilot_june_2026.csv      ─┘        writes mapper JSON)
                                              │
                                             ▼
                                    mappers/
                                      copilot_mapper.json
                                      claude_mapper.json   ◄── one per vendor
                                              │
                              ┌───────────────┘
                              │
  saas_template.csv  ─────────┼──► transform_engine/
  (column order)              │      transformer.py
                              │       (reads mapper + CSV,
                              │        applies transforms,
                              │        writes FOCUS output)
                              │              │
                              │    field_transformations.py
                              │    (13 pluggable functions)
                              │              │
                             ▼             ▼
                     focus_cur_outputs/
                       copilot_january_2026_focus_cur.csv
                       copilot_february_2026_focus_cur.csv
                       …

  CONTROL
  ───────
  config.ini  ──────────────► main.py  ──────────► audit/run_logger.py
  (paths, billing,              (CLI,                 logs/latest.log
   mapper, logging)              orchestration)        logs/run_state.json
```

**Data flow summary:**
1. `generate` reads CSV headers and sample rows → scores each source column against FOCUS
   column patterns → writes a `mapper.json` with the best mapping for each FOCUS column.
2. `transform` reads the mapper + CSV row by row → applies the named transform function to
   each source value → writes a FOCUS-compliant output CSV.
3. `run` does both automatically, detecting the vendor per file.

---

## 3. File-by-File Reference

### Inside `saas_to_focus_formatter/`

| File | Role | You touch it when… |
|------|------|-------------------|
| `main.py` | CLI entry point; three sub-commands; config loading; retry/resume logic | Adding a new sub-command |
| `config.ini` | All project settings — paths, billing metadata, mapper paths, log config | Once at setup; whenever paths change |
| `mapper_generator/generate_mapper.py` | Reads CSV headers, scores columns semantically, produces `mapper.json` | Never — invoked via `generate` |
| `transform_engine/transformer.py` | Mapper-driven row transform; three-tier value resolution | Never |
| `transform_engine/field_transformations.py` | 13 named transform functions used in mapper JSON | Only to add a custom transform |
| `audit/run_logger.py` | Writes structured log + atomic JSON checkpoint per file | Never |
| `mappers/copilot_mapper.json` | Ready-to-use mapper for GitHub Copilot | Copy as a starting point for new vendors |
| `schemas/focus_schema.json` | FOCUS 1.0 column reference (read by `generate`) | Never — reference only |
| `tests/` | 168 unit tests across 4 files | When adding features or transforms |

### Outside `saas_to_focus_formatter/` (one level up)

| File / Folder | Role |
|---------------|------|
| `usage_reports/*.csv` | Your SaaS vendor exports — drop files here each billing cycle |
| `saas_template.csv` | Defines output column order; shared across all vendors |
| `focus_cur_outputs/` | Generated FOCUS CSV files land here (created automatically) |

---

## 4. `config.ini` — Section by Section

`config.ini` lives inside `saas_to_focus_formatter/` and is auto-loaded on every run.
**CLI arguments always override it.**

```ini
# =============================================================================
# [paths] — Where to find inputs and write outputs
# =============================================================================
[paths]

# Batch mode: process all *.csv files in this folder (alphabetical order).
# Used by: run, transform
usage_dir    = ../usage_reports/

# Single-file mode: one specific CSV.
# Used by: generate (required), run/transform (fallback if usage_dir not set)
; usage_report  = ../usage_reports/copilot_january_2026.csv

# Output folder for batch mode — each input produces <stem>_focus_cur.csv here.
output_dir   = ../focus_cur_outputs/

# Output file for single-file mode.
; output        = ../focus_cur_output.csv

# FOCUS/CUR template: defines column order of output CSVs.
cur_template  = ../saas_template.csv


# =============================================================================
# [billing] — Metadata written into every FOCUS output row
# =============================================================================
[billing]
provider_name        = GitHub
billing_account_id   = org-CoreStack-Engg
billing_account_name = CoreStack Engineering
billing_currency     = USD      # built-in default: USD
region_name          = global   # built-in default: global


# =============================================================================
# [mapper] — Mapper file paths and generation hints
# =============================================================================
[mapper]
# Mapper used by `transform`. Required for standalone transform runs.
mapper = mappers/copilot_mapper.json

# Hints passed to `generate` (auto-inferred from CSV if omitted).
tool_name      = copilot
product_family = Developer Tools


# =============================================================================
# [logging] — Log directory and retry behaviour
# =============================================================================
[logging]
log_dir     = logs   # relative to saas_to_focus_formatter/
max_retries = 1      # 1 = no retry; 3 = try up to 3 times before marking failed
```

**Three-tier priority in action:**

```
You set in config.ini:   billing_currency = USD
You run:                 python3 main.py run --billing_currency EUR
Result:                  EUR  (CLI wins)

You set in config.ini:   billing_currency = USD
You run:                 python3 main.py run
Result:                  USD  (config wins over built-in default)

Neither CLI nor config:  billing_currency is blank in config.ini, no CLI flag
Result:                  USD  (built-in default)
```

---

## 5. The Three Sub-Commands

### 5.1 `generate` — CSV → Mapper JSON

**What it does:** Reads column headers and up to 5 sample rows from a single CSV.
Scores each source column against 17 FOCUS columns using keyword patterns.
Writes a `mapper.json` to `mappers/`.

**Requires:** A single `--usage_report` CSV file.

```
python3 main.py generate [OPTIONS]

Options:
  --usage_report FILE     Input CSV (required; or set paths.usage_report in config.ini)
  --output_mapper FILE    Where to write the mapper (default: mappers/<tool_name>_mapper.json)
  --tool_name NAME        Vendor name hint (auto-inferred from CSV data if omitted)
  --product_family NAME   ProductFamily value (e.g. "Developer Tools")
  --provider_name NAME    ProviderName value (e.g. "GitHub")
  --billing_currency CODE ISO 4217 currency code (default: USD)
  --schema FILE           FOCUS schema JSON (default: schemas/focus_schema.json)
  --config FILE           INI config file (default: config.ini)
```

**Example:**
```bash
cd saas_to_focus_formatter

python3 main.py generate \
  --usage_report ../usage_reports/copilot_january_2026.csv \
  --tool_name    copilot \
  --provider_name GitHub

# → writes mappers/copilot_mapper.json
```

**Expected output:**
```
INFO  Mapper written → mappers/copilot_mapper.json  (15 FOCUS columns mapped)
```

---

### 5.2 `transform` — CSV + Mapper → FOCUS CSV

**What it does:** Reads a mapper JSON, then converts each row of the input CSV(s) to the
FOCUS schema. Supports both single-file and batch-folder input modes.

```
python3 main.py transform [OPTIONS]

Input (choose one):
  --usage_report FILE     Single CSV file
  --usage_dir    DIR      Batch folder — all *.csv processed alphabetically

Output (matches input mode):
  --output FILE           Single output file (single-file mode)
  --output_dir DIR        Output folder (batch mode)

Mapper + template:
  --mapper FILE           Mapper JSON (required; or set mapper.mapper in config.ini)
  --cur_template FILE     FOCUS template CSV (default: ../saas_template.csv)

Billing metadata:
  --provider_name NAME
  --billing_account_id ID
  --billing_account_name NAME
  --billing_currency CODE (default: USD)
  --region_name NAME      (default: global)
  --charge_category CAT   (default: Usage)
  --charge_frequency FREQ (default: Monthly)

Logging:
  --max_retries N         Retry each failed file N times (default: 1)
  --resume                Skip files already marked done in run_state.json
  --log_dir DIR           Override log directory (default: logs/)
  --config FILE           INI config file (default: config.ini)
```

**Single-file example:**
```bash
python3 main.py transform \
  --usage_report  ../usage_reports/copilot_january_2026.csv \
  --mapper        mappers/copilot_mapper.json \
  --cur_template  ../saas_template.csv \
  --output        ../focus_cur_outputs/copilot_january_focus_cur.csv \
  --provider_name GitHub \
  --billing_account_id   org-CoreStack-Engg \
  --billing_account_name "CoreStack Engineering"
```

**Batch-folder example (via config.ini):**
```bash
# All settings already in config.ini:
python3 main.py transform
```

---

### 5.3 `run` — Full Pipeline (generate + transform)

**What it does:** For each input CSV, `run` automatically detects the vendor from the
column names (or filename), generates/reuses a mapper, and transforms the file.
This is the main production command.

```
python3 main.py run [OPTIONS]
  (same options as transform — see above)
  Plus: --config FILE
```

**From config.ini (simplest):**
```bash
python3 main.py run
```

**With overrides:**
```bash
python3 main.py run --provider_name "GitHub Enterprise" --max_retries 3
```

**Vendor auto-detection logic (inside `run`):**
1. Reads column names from the CSV
2. Scores against known vendor patterns (copilot columns → copilot, claude model names → claude, etc.)
3. Looks for `mappers/<tool_name>_mapper.json`; if missing, generates it first
4. Runs transform

---

## 6. Input Modes: Single File vs Batch Folder

| | Single File | Batch Folder |
|---|---|---|
| **Config key** | `paths.usage_report` | `paths.usage_dir` |
| **CLI flag** | `--usage_report FILE` | `--usage_dir DIR` |
| **Output key** | `paths.output` | `paths.output_dir` |
| **Output naming** | Explicit path | `<stem>_focus_cur.csv` auto-named |
| **Works with** | `generate`, `transform`, `run` | `transform`, `run` |
| **File ordering** | Single file | Alphabetical by filename |

**Tip:** Set both `usage_dir` and `usage_report` in `config.ini` — `run`/`transform` use
the folder, `generate` falls back to the single file. All three commands work without any flags.

```ini
[paths]
usage_dir    = ../usage_reports/        # for run / transform
usage_report = ../usage_report.csv      # for generate
output_dir   = ../focus_cur_outputs/
cur_template = ../saas_template.csv
```

---

## 7. Mapper JSON Deep Dive

Open `mappers/copilot_mapper.json` to follow along.

### Structure

```json
{
  "meta": {
    "tool_name": "copilot",
    "generated_at": "2026-03-05T09:33:13Z",
    "source_columns": ["date","product","sku","quantity","unit_type",
                       "applied_cost_per_quantity","gross_amount",
                       "discount_amount","net_amount","username",
                       "organization","repository","workflow_path",
                       "cost_center_name"],
    "focus_version": "1.0",
    "generator": "saas_focus_converter/mapper_generator/generate_mapper.py"
  },
  "defaults": {
    "ChargeCategory": "Usage",
    "ChargeFrequency": "Monthly",
    "BillingCurrency": "USD",
    "ProviderName": "GitHub"
  },
  "mappings": {
    "BilledCost": {
      "source": "net_amount",
      "transform": "identity",
      "fallback_sources": ["applied_cost_per_quantity", "gross_amount"],
      "default_value": "0"
    },
    "BillingPeriodStart": {
      "source": "date",
      "transform": "to_iso8601_start"
    },
    "BillingPeriodEnd": {
      "source": "date",
      "transform": "to_billing_period_end"
    },
    "ServiceName": {
      "source": "product",
      "transform": "humanize"
    },
    "Tags": {
      "transform": "build_tags",
      "tag_sources": ["username","organization","repository",
                      "workflow_path","cost_center_name"]
    },
    "ProductFamily": {
      "transform": "static",
      "static_value": "Developer Tools"
    }
  }
}
```

### Sections Explained

**`meta`** — Informational. Records what columns the CSV had and when the mapper was generated.
The transformer uses `source_columns` for validation.

**`defaults`** — Static values injected into every output row for columns not in `mappings`.
These are overridden by CLI billing flags (three-tier priority applies here too).

**`mappings`** — One entry per FOCUS column. Each entry has:

| Key | Required? | Meaning |
|-----|-----------|---------|
| `source` | Usually yes | Source CSV column to read |
| `transform` | Yes | Named transform function to apply |
| `fallback_sources` | No | Try these columns if `source` is empty |
| `default_value` | No | Use this if source and all fallbacks are empty |
| `static_value` | For `static` only | Literal value to output |
| `tag_sources` | For `build_tags` only | List of columns to pack into a JSON tag map |

### All 13 Transform Functions

| Name | What It Does | Example Input → Output |
|------|-------------|----------------------|
| `identity` | Return value unchanged | `"19.50"` → `"19.50"` |
| `humanize` | Replace `_`/`-` with spaces, title-case | `"copilot_for_business"` → `"Copilot For Business"` |
| `title_case` | Title-case only | `"copilot"` → `"Copilot"` |
| `to_uppercase` | Full uppercase | `"usd"` → `"USD"` |
| `to_lowercase` | Full lowercase | `"GitHub"` → `"github"` |
| `strip_whitespace` | Strip leading/trailing spaces | `"  hello  "` → `"hello"` |
| `to_decimal` | Coerce to decimal string; empty → `"0"` | `"19"` → `"19"` |
| `to_iso8601_start` | Any date → `YYYY-MM-DDT00:00:00Z` | `"2026-01-01"` → `"2026-01-01T00:00:00Z"` |
| `to_iso8601_end` | Any date → `YYYY-MM-DDT23:59:59Z` | `"2026-01-01"` → `"2026-01-01T23:59:59Z"` |
| `to_billing_period_end` | First instant of **next** month | `"2026-01-15"` → `"2026-02-01T00:00:00Z"` |
| `static` | Return `static_value` (ignores input) | any → `"Developer Tools"` |
| `build_tags` | Build compact JSON map from `tag_sources` | columns → `{"username":"alice","org":"Acme"}` |
| `first_non_empty` | First non-empty value from `sources` list | tries each in order |

### Three-Tier Value Resolution Per Cell

For each output cell, the transformer resolves the value in this order:

```
1. CLI billing flag (e.g. --provider_name)
2. mapper.json defaults block
3. mapper.json mappings entry → source column + transform
   3a. If source is empty → try fallback_sources in order
   3b. If all sources empty → use default_value
4. Empty string
```

---

## 8. End-to-End Demo Script

All commands run from inside `saas_to_focus_formatter/`.

```bash
cd /Users/deepak/Documents/output/saas_to_focus_formatter
```

---

### Step 1 — Verify the Environment

```bash
python3 --version
# Python 3.x.x  (must be 3.10+)

python3 main.py --help
# Shows: usage: main.py [-h] {generate,transform,run} ...

python3 main.py run --help
# Shows all flags for run
```

---

### Step 2 — Run the Test Suite

```bash
python3 -m unittest discover -s tests -v
```

Expected: **168 tests, OK** across 4 test files.

| Test File | Tests | Covers |
|-----------|------:|--------|
| `test_field_transformations.py` | 63 | All 13 transforms, date parsing, edge cases |
| `test_transformer.py` | 38 | Three-tier resolution, row transform, validation |
| `test_generate_mapper.py` | 50 | Semantic scoring, tool detection, mapper structure |
| `test_main.py` | 17 | Batch helpers (`_get_input_files`, `_resolve_output_path`) |

---

### Step 3 — Inspect the Input Data

```bash
# Look at the first 3 rows of a Copilot CSV
head -4 ../usage_reports/copilot_january_2026.csv
```

You'll see columns: `date, product, sku, quantity, unit_type, applied_cost_per_quantity,
gross_amount, discount_amount, net_amount, username, organization, repository, workflow_path, cost_center_name`

---

### Step 4 — Generate a Mapper from a Single CSV

```bash
python3 main.py generate \
  --usage_report ../usage_reports/copilot_january_2026.csv \
  --tool_name    copilot \
  --provider_name GitHub
```

Expected output:
```
INFO  Mapper written → mappers/copilot_mapper.json  (15 FOCUS columns mapped)
```

Now open `mappers/copilot_mapper.json` and walk through the structure.
Point out:
- `meta.source_columns` — what columns were found in the CSV
- `defaults` — billing metadata injected into every row
- `mappings.BilledCost` — `net_amount` → identity (number as-is)
- `mappings.BillingPeriodStart` — `date` → `to_iso8601_start` (date normalization)
- `mappings.Tags` — `build_tags` packing 5 columns into a JSON tag object
- `mappings.ProductFamily` — `static` with `static_value` (no source column needed)

---

### Step 5 — Transform a Single File

```bash
python3 main.py transform \
  --usage_report  ../usage_reports/copilot_january_2026.csv \
  --mapper        mappers/copilot_mapper.json \
  --cur_template  ../saas_template.csv \
  --output        ../focus_cur_outputs/copilot_january_focus_cur.csv \
  --provider_name GitHub \
  --billing_account_id   org-CoreStack-Engg \
  --billing_account_name "CoreStack Engineering"
```

Expected output:
```
INFO  [1/1] START   ../usage_reports/copilot_january_2026.csv
INFO  [1/1]   output : ../focus_cur_outputs/copilot_january_focus_cur.csv
INFO  [1/1]   mapper : mappers/copilot_mapper.json
INFO  [1/1] DONE    rows=31      elapsed=0.04s
```

Open `../focus_cur_outputs/copilot_january_focus_cur.csv`.
Point out FOCUS columns: `BillingPeriodStart`, `BilledCost`, `EffectiveCost`, `ServiceName`,
`ProviderName`, `BillingAccountId`, `Tags` (JSON map with username/org/repo).

---

### Step 6 — Batch Run Everything from `config.ini`

```bash
# No flags needed — config.ini has all paths and billing values
python3 main.py run
```

Expected output:
```
INFO  ========================================================================
INFO  RUN START   run_id=20260305_HHMMSS    command=run
INFO  Config      : /path/to/saas_to_focus_formatter/config.ini
INFO  Input files : 6
INFO    [1/6] ../usage_reports/copilot_april_2026.csv
INFO    [2/6] ../usage_reports/copilot_february_2026.csv
...
INFO  ------------------------------------------------------------------------
INFO  [1/6] START   ../usage_reports/copilot_april_2026.csv
INFO  [1/6]   output : ../focus_cur_outputs/copilot_april_2026_focus_cur.csv
INFO  [1/6]   mapper : mappers/copilot_mapper.json
INFO  [1/6] DONE    rows=30      elapsed=0.04s
...
INFO  RUN COMPLETE   done=6  failed=0  skipped=0  rows=186  elapsed=0.22s
```

Six output files created in `../focus_cur_outputs/`.

Show the log file:
```bash
cat logs/latest.log
```

Show the checkpoint:
```bash
cat logs/run_state.json
```

---

### Step 7 — Simulate a Failure + Resume

**7a. Break one file:**
```bash
mv ../usage_reports/copilot_june_2026.csv ../usage_reports/copilot_june_2026.csv.bak
```

**7b. Run with retries:**
```bash
python3 main.py run --max_retries 2
echo "Exit code: $?"
```

Expected: 5 succeed, 1 fails → `run_state.json` shows `"status": "failed"` for june.
Exit code is `2` (partial failure).

**7c. Inspect the checkpoint:**
```bash
cat logs/run_state.json
# june_2026 shows: "status": "failed", "attempts": 2, "error": "..."
# all others show: "status": "done"
```

**7d. Restore the file and resume:**
```bash
mv ../usage_reports/copilot_june_2026.csv.bak ../usage_reports/copilot_june_2026.csv

python3 main.py run --resume
echo "Exit code: $?"
```

Expected: Only `copilot_june_2026.csv` re-runs (5 files skipped).
Log shows `skipped=5  done=1`. Exit code is `0`.

---

### Step 8 — Override Values via CLI

The three-tier priority means any config value can be overridden without editing the file:

```bash
# Override provider name and currency for this run only
python3 main.py run \
  --provider_name "GitHub Enterprise" \
  --billing_currency EUR

# Override billing account for a specific customer
python3 main.py run \
  --billing_account_id   org-customer-xyz \
  --billing_account_name "Customer XYZ"

# Use a completely different config file
python3 main.py run --config /path/to/staging.ini

# Override a single file instead of the whole folder
python3 main.py transform \
  --usage_report ../usage_reports/copilot_june_2026.csv \
  --mapper mappers/copilot_mapper.json \
  --output ../focus_cur_outputs/copilot_june_focus_cur.csv
```

---

### Step 9 — Upload Outputs to AWS S3

**Prerequisites:** `pip install boto3` and AWS credentials configured.

**9a. Enable S3 in config.ini** (uncomment and fill in):
```ini
[s3]
bucket  = my-finops-bucket
prefix  = focus-cur-outputs/
region  = us-east-1
```

**9b. Run normally — S3 upload happens automatically:**
```bash
python3 main.py run
```

Expected output now shows:
```
✓ Batch complete: 6 done, 0 failed, 0 skipped — 186 total rows
  Output dir : ../focus_cur_outputs/
  S3 dest    : s3://my-finops-bucket/focus-cur-outputs/
  Log   : logs/latest.log
  State : logs/run_state.json
```

And in `logs/latest.log`:
```
INFO   [1/6] DONE    rows=31      elapsed=0.04s
INFO   [1/6]   s3     : s3://my-finops-bucket/focus-cur-outputs/copilot_january_2026_focus_cur.csv
```

**9c. Or override via CLI for a one-off upload:**
```bash
python3 main.py run \
    --s3_bucket  my-finops-bucket \
    --s3_prefix  focus-cur-outputs/ \
    --s3_region  us-east-1

# Use a specific AWS credentials profile
python3 main.py run \
    --s3_bucket  my-finops-bucket \
    --s3_profile finops-prod
```

**Key behaviours to demonstrate:**
- Local files are always written — S3 is additive, not a replacement
- S3 upload failure logs a warning but does not fail the file or change exit code
- Both `output_dir` (local) and `s3_bucket` can be set simultaneously

---

### Step 10 — Add a New Vendor (No Code Required)

To add support for Anthropic Claude billing exports:

```bash
# 1. Drop the vendor CSV in usage_reports/
#    (Claude CSV has columns: date, model, sku, input_tokens, output_tokens,
#     total_tokens, cost_usd, username, organization, team_name)

# 2. Generate the mapper
python3 main.py generate \
  --usage_report ../usage_reports/claude_january_2026.csv \
  --tool_name    claude \
  --provider_name Anthropic \
  --product_family "AI / Machine Learning"

# → mappers/claude_mapper.json  (auto-maps cost_usd → BilledCost,
#                                 total_tokens → ConsumedQuantity, etc.)

# 3. Inspect and optionally hand-edit the mapper
# open mappers/claude_mapper.json

# 4. Transform
python3 main.py transform \
  --usage_report  ../usage_reports/claude_january_2026.csv \
  --mapper        mappers/claude_mapper.json \
  --cur_template  ../saas_template.csv \
  --output        ../focus_cur_outputs/claude_january_focus_cur.csv \
  --provider_name Anthropic \
  --billing_account_id   org-CoreStack-Engg \
  --billing_account_name "CoreStack Engineering"

# Or for batch with mixed vendors, just:
python3 main.py run
# run auto-detects the vendor per file and uses the right mapper
```

**No Python code written. No engine changes. Just a JSON mapper.**

---

## 9. Logging & Auditing Reference

### `logs/latest.log`

Overwritten on every run. Contains the full structured log of what happened.

```
2026-03-05 14:30:22  INFO   ========================================================================
2026-03-05 14:30:22  INFO   RUN START   run_id=20260305_143022    command=run
2026-03-05 14:30:22  INFO   Config      : /path/to/config.ini
2026-03-05 14:30:22  INFO   Input files : 6
2026-03-05 14:30:22  INFO     [1/6] ../usage_reports/copilot_april_2026.csv
2026-03-05 14:30:22  INFO     [2/6] ../usage_reports/copilot_february_2026.csv
...
2026-03-05 14:30:22  INFO   ------------------------------------------------------------------------
2026-03-05 14:30:22  INFO   [1/6] START   ../usage_reports/copilot_april_2026.csv
2026-03-05 14:30:22  INFO   [1/6]   output : ../focus_cur_outputs/copilot_april_2026_focus_cur.csv
2026-03-05 14:30:22  INFO   [1/6]   mapper : mappers/copilot_mapper.json
2026-03-05 14:30:22  INFO   [1/6] DONE    rows=30      elapsed=0.04s
...
2026-03-05 14:30:23  ERROR  [6/6] FAIL    elapsed=0.08s  error=FileNotFoundError: ...
2026-03-05 14:30:23  INFO   ------------------------------------------------------------------------
2026-03-05 14:30:23  INFO   RUN COMPLETE WITH ERRORS  done=5  failed=1  skipped=0  rows=155  elapsed=0.22s
```

### `logs/run_state.json`

Updated atomically after every file. Used by `--resume` to skip already-done files.

```json
{
  "run_id": "20260305_143022",
  "command": "run",
  "started_at": "2026-03-05T14:30:22Z",
  "files": {
    "../usage_reports/copilot_april_2026.csv": {
      "status": "done",
      "rows": 30,
      "started_at": "2026-03-05T14:30:22Z",
      "finished_at": "2026-03-05T14:30:22Z",
      "elapsed_s": 0.04,
      "attempts": 1
    },
    "../usage_reports/copilot_june_2026.csv": {
      "status": "failed",
      "error": "FileNotFoundError: No such file or directory",
      "attempts": 2,
      "elapsed_s": 0.08
    }
  }
}
```

### Flags Summary

| Flag | Config Key | Default | What It Does |
|------|-----------|---------|-------------|
| `--max_retries N` | `logging.max_retries` | `1` | Retry each failed file up to N times in the same run |
| `--resume` | — | off | Skip files with `status=done` in the last `run_state.json` |
| `--log_dir DIR` | `logging.log_dir` | `logs/` | Write `latest.log` and `run_state.json` to a different directory |

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All files succeeded |
| `2` | Partial failure — at least one file failed after all retries |
| `1` | Bad arguments — fix the command and retry |

---

## 10. Troubleshooting Quick Reference

| Error | Root Cause | Fix |
|-------|-----------|-----|
| `No input source specified` | Neither `--usage_report` nor `--usage_dir` set | Add the flag or set `paths.usage_report`/`paths.usage_dir` in config.ini |
| `No .csv files found in directory` | `usage_dir` points to an empty or non-existent folder | Check that `usage_reports/` exists and has `.csv` files |
| `paths.usage_dir is set but generate requires a single file` | Running `generate` with only `usage_dir` set in config | Set `paths.usage_report` in config.ini or pass `--usage_report` |
| `Mapper not found` | `mapper.mapper` in config or `--mapper` path does not exist | Run `generate` first, or correct the path |
| `KeyError: 'net_amount'` | Source column in mapper doesn't exist in CSV | Edit the mapper's `source`/`fallback_sources` to match actual column names |
| `cur_template not found` | `saas_template.csv` missing from parent directory | Copy/create `saas_template.csv` one level above `saas_to_focus_formatter/` |
| `Exit code 2` | One or more files failed during batch run | Check `logs/latest.log` for the specific error; fix, then `--resume` |
| `168 tests, FAIL` | A transform or mapper function is broken | Run `python3 -m unittest tests.<file> -v` to isolate the failure |

---

## 11. Extending the Project

### Add a Custom Transform Function

1. Open `transform_engine/field_transformations.py`
2. Define a function with signature: `fn(value: str, row: dict = None, config: dict = None) -> str`
3. Register it in `TRANSFORM_REGISTRY` at the bottom of the file with a unique key
4. Reference the key in any mapper's `"transform"` field

Example:
```python
def to_month_year(value, row=None, config=None):
    """Convert any date to 'January 2026' format."""
    from datetime import datetime
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(value.strip(), fmt)
            return dt.strftime("%B %Y")
        except ValueError:
            continue
    return value

TRANSFORM_REGISTRY["to_month_year"] = to_month_year
```

Then in your mapper:
```json
"ServicePeriod": { "source": "date", "transform": "to_month_year" }
```

### Add a New Vendor Mapper

1. Export the vendor's CSV (any format)
2. Run `python3 main.py generate --usage_report vendor.csv --tool_name vendor`
3. Open `mappers/vendor_mapper.json` and verify the auto-detected mappings
4. Hand-edit any columns the auto-detection got wrong
5. Run `python3 main.py transform` — done

The engine code never changes.
