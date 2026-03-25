# Knowledge Transfer Document
## SaaS Usage → FOCUS/CUR Converter (`saas_to_focus_formatter`)

**Version:** 1.0
**Date:** 2026-03-05
**Audience:** New team members, engineers onboarding to the FinOps platform

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [How the Solution Works — Big Picture](#2-how-the-solution-works--big-picture)
3. [Architecture Flow Diagram](#3-architecture-flow-diagram)
4. [Folder Structure — Every Folder and File Explained](#4-folder-structure--every-folder-and-file-explained)
5. [The Three Key Files You Work With](#5-the-three-key-files-you-work-with)
6. [config.ini — The Control Panel](#6-configini--the-control-panel)
7. [The Three CLI Commands — Deep Explanation](#7-the-three-cli-commands--deep-explanation)
8. [Important Flags — Resume, Retries, Log Dir](#8-important-flags--resume-retries-log-dir)
9. [The Mapper JSON — Anatomy and Deep Dive](#9-the-mapper-json--anatomy-and-deep-dive)
10. [The SKILL File — `/generate-mapper`](#10-the-skill-file--generate-mapper)
11. [The Makefile](#11-the-makefile)
12. [The README](#12-the-readme)
13. [All Test Files — One by One](#13-all-test-files--one-by-one)
14. [How to Run Tests — Every Command](#14-how-to-run-tests--every-command)
15. [Understanding the Input, Template, and Output Files](#15-understanding-the-input-template-and-output-files)
16. [Priority Order — Who Wins When Values Conflict](#16-priority-order--who-wins-when-values-conflict)
17. [Logs and Audit Trail](#17-logs-and-audit-trail)
18. [Adding a New SaaS Vendor — Zero Code Required](#18-adding-a-new-saas-vendor--zero-code-required)
19. [Common Errors and What They Mean](#19-common-errors-and-what-they-mean)
20. [Development Prompts — How This Project Was Built](#20-development-prompts--how-this-project-was-built)

---

## 1. Problem Statement

### The Gap We Are Solving

Modern organisations use many SaaS tools — GitHub Copilot, Anthropic Claude, Datadog, Snowflake, Slack, and more. Each of these tools exports billing/usage data in its own custom CSV format. No two vendors use the same column names.

FinOps platforms (like CoreStack) need cost data in a **standard format** called **FOCUS 1.0** (also called CUR — Cloud Usage and Resource). This is the same format AWS uses for billing exports.

**The problem:**

| What FinOps tools speak | What SaaS vendors export |
|------------------------|--------------------------|
| FOCUS / CUR format | Their own custom CSV schema |
| Standard column names (`BilledCost`, `ServiceName`, etc.) | Random column names (`net_amount`, `product`, `sku`) |
| One unified dashboard | Invisible — not in any dashboard |

Before this tool existed, engineers manually reformatted SaaS CSVs using Excel or one-off Python scripts. This was:
- Time-consuming (1–2 hours per vendor per month)
- Error-prone (manual mapping decisions, no validation)
- Not reusable (each vendor needed its own ad-hoc script)
- Undocumented (no audit trail)

### What This Utility Does

`saas_to_focus_formatter` is a **standalone Python utility** that:

1. **Takes any SaaS vendor usage export CSV** as input
2. **Generates a mapper JSON file** that describes how to convert it (one time per vendor)
3. **Transforms the CSV** into a FOCUS 1.0-compliant CUR CSV
4. **Validates** that all 14 required FOCUS columns are populated before writing output
5. **Supports batch processing** — process an entire folder of CSVs in one command
6. **Optionally uploads** the output to AWS S3

**Key design principle:** All vendor-specific knowledge lives in a `mapper.json` file. The Python engine itself has zero vendor-specific code. Adding a new vendor = adding one JSON file.

---

## 2. How the Solution Works — Big Picture

Think of the system in three layers:

```
Layer 1 — INPUT
  Your SaaS vendor exports billing as a CSV file.
  Example: GitHub Copilot exports copilot_january_2026.csv
  It has columns: date, product, sku, quantity, net_amount, username, organization, ...

Layer 2 — MAPPER (the brain)
  A mapper.json file tells the engine:
  "To fill FOCUS column BilledCost, read the net_amount column from the input CSV."
  "To fill FOCUS column BillingPeriodStart, read the date column and format it as ISO-8601."
  One mapper.json per vendor. Write it once. Reuse every month.

Layer 3 — OUTPUT
  The engine reads the input CSV row by row, applies the mapper, and writes
  a FOCUS-compliant CUR CSV with standard column names that your FinOps
  platform understands.
```

The tool does the mapping **automatically** for the first run using a "generate" step.
After that, it reuses the same mapper file every month.

---

## 3. Architecture Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        INPUT LAYER                                  │
│                                                                     │
│   usage_reports/                                                    │
│   ├── copilot_january_2026.csv    ← Copilot billing export          │
│   ├── copilot_february_2026.csv                                     │
│   └── copilot_march_2026.csv      ← Any SaaS vendor CSV             │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  (Step 1) Read columns + sample rows
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     MAPPER GENERATOR                                │
│   mapper_generator/generate_mapper.py                               │
│                                                                     │
│   • Reads the CSV headers                                           │
│   • Scores each source column against known FOCUS column patterns   │
│   • Auto-detects date columns, cost columns, tag columns            │
│   • Infers vendor name and product family                           │
│   • Writes a structured mappers/<tool>_mapper.json                  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  (Step 2) mapper.json written
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       MAPPER FILE                                   │
│   mappers/copilot_mapper.json                                       │
│                                                                     │
│   { "meta": { "tool_name": "copilot" },                             │
│     "defaults": { "ChargeCategory": "Usage", "BillingCurrency": "USD" },│
│     "mappings": {                                                   │
│       "BilledCost": { "source": "net_amount", "transform": "identity" },│
│       "BillingPeriodStart": { "source": "date", "transform": "to_iso8601_start" },│
│       "Tags": { "transform": "build_tags", "tag_sources": ["username", "organization"] }│
│     }                                                               │
│   }                                                                 │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  (Step 3) Mapper + CSV fed to engine
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   TRANSFORMATION ENGINE                             │
│   transform_engine/transformer.py                                   │
│                                                                     │
│   For each row in the input CSV:                                    │
│     1. Read all source values from the input row                    │
│     2. For each FOCUS output column:                                │
│        a. Check CLI params (Tier 1) — highest priority              │
│        b. Check mapper mappings (Tier 2) — apply transform function │
│        c. Check mapper defaults (Tier 3) — static fallback          │
│     3. Validate all 14 required columns are populated               │
│     4. Write the output row                                         │
│                                                                     │
│   Transform functions used:  identity, to_iso8601_start,            │
│   to_billing_period_end, humanize, build_tags, static, ...          │
│   (13 functions total, all in field_transformations.py)             │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  (Step 4) FOCUS-compliant CSV written
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        OUTPUT LAYER                                 │
│                                                                     │
│   focus_cur_outputs/                                                │
│   ├── copilot_january_2026_focus_cur.csv   ← Ready for FinOps       │
│   ├── copilot_february_2026_focus_cur.csv                           │
│   └── copilot_march_2026_focus_cur.csv                              │
│                                                                     │
│   (Optional) Also uploaded to:                                      │
│   s3://my-finops-bucket/focus-cur-outputs/                          │
└─────────────────────────────────────────────────────────────────────┘
                               │  (Step 5) Logged + checkpointed
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      AUDIT & LOGGING                                │
│   audit/run_logger.py                                               │
│                                                                     │
│   logs/latest.log         ← Full timestamped log of the current run │
│   logs/run_state.json     ← JSON checkpoint: which files succeeded, │
│                              which failed, how many rows written    │
└─────────────────────────────────────────────────────────────────────┘
```

### Point-by-Point Explanation of the Flow

**Step 1 — Read Input CSV**
The tool reads your SaaS vendor's usage export. It reads only the column headers and a few sample rows — it does not load the entire file into memory during generation.

**Step 2 — Generate Mapper (first time only)**
The `generate` command inspects the column names. It uses semantic scoring — for example, if a column is named `net_amount`, it gets a high score for the FOCUS `BilledCost` column because "amount" and "cost" are semantically related. The best-matching source column wins for each FOCUS target column.

**Step 3 — Read Mapper + Apply Three-Tier Resolution**
The transformation engine reads the mapper JSON. For every row, and every output column, it follows this priority:
- Tier 1: Did the user pass this value on the CLI? (e.g. `--billing_account_id "my-org"`) → Use that.
- Tier 2: Does the mapper have a mapping for this column? → Read the source column, apply the transform function.
- Tier 3: Does the mapper have a default for this column? → Use the static default value.
If none of the three tiers has a value, the output column is left empty.

**Step 4 — Validate and Write**
Before writing any rows, the engine checks that all 14 required FOCUS columns are populated in the first row. If any are empty, the run stops with a clear error message listing which columns are missing. This catches misconfigured mappers before producing a broken output file.

**Step 5 — Log and Checkpoint**
After every file is processed, the audit logger writes the result to `run_state.json`. This checkpoint is used by the `--resume` flag to skip already-completed files in case a run is interrupted.

---

## 4. Folder Structure — Every Folder and File Explained

```
output/                              ← Parent directory (project root)
│
├── saas_to_focus_formatter/         ← The Python project (you always run from here)
│   │
│   ├── main.py                      ← THE CLI. All commands start here.
│   │                                   Three sub-commands: generate, transform, run
│   │
│   ├── config.ini                   ← The settings file. Edit this once at setup.
│   │                                   Controls all paths, billing info, S3 settings.
│   │
│   ├── requirements.txt             ← Lists all Python libraries used.
│   │                                   Core needs nothing (stdlib only).
│   │                                   boto3 optional for S3.
│   │
│   ├── Makefile                     ← Shortcuts. 'make test', 'make run-config', etc.
│   │
│   ├── README.md                    ← Full user guide for the project.
│   │
│   ├── mapper_generator/
│   │   └── generate_mapper.py       ← Auto-generates mapper.json from any CSV.
│   │                                   Uses semantic scoring to match columns.
│   │                                   Called by: main.py generate
│   │
│   ├── transform_engine/
│   │   ├── transformer.py           ← The conversion engine. Reads mapper + CSV,
│   │   │                               applies three-tier resolution, writes output.
│   │   │                               Called by: main.py transform / run
│   │   │
│   │   └── field_transformations.py ← 13 transform functions.
│   │                                   identity, humanize, to_iso8601_start, etc.
│   │                                   Called by: transformer.py per cell
│   │
│   ├── audit/
│   │   └── run_logger.py            ← Writes structured logs and JSON checkpoint.
│   │                                   Creates: logs/latest.log, logs/run_state.json
│   │
│   ├── schemas/
│   │   └── focus_schema.json        ← The FOCUS 1.0 column reference.
│   │                                   Defines what columns exist and which are required.
│   │                                   Read by: generate_mapper.py, transformer.py
│   │
│   ├── mappers/
│   │   └── copilot_mapper.json      ← The mapper for GitHub Copilot.
│   │                                   One file per SaaS vendor.
│   │                                   Generated by: main.py generate
│   │                                   Used by: main.py transform / run
│   │
│   ├── logs/                        ← Created automatically on first run.
│   │   ├── latest.log               ← Full log of the most recent run.
│   │   └── run_state.json           ← JSON checkpoint for --resume.
│   │
│   └── tests/
│       ├── test_field_transformations.py   ← 63 tests for all 13 transform functions
│       ├── test_transformer.py             ← 38 tests for the conversion engine
│       ├── test_generate_mapper.py         ← 50 tests for the mapper generator
│       └── test_main.py                    ← 17 tests for batch path helpers
│
├── usage_reports/                   ← YOUR INPUT FILES (outside the project folder)
│   ├── copilot_january_2026.csv     ← Download these from each SaaS vendor portal
│   ├── copilot_february_2026.csv
│   └── ...
│
├── saas_template.csv                ← THE FOCUS TEMPLATE (outside the project folder)
│                                       Defines the 23 output column names and order.
│                                       Never modify this file.
│
└── focus_cur_outputs/               ← YOUR OUTPUT FILES (outside the project folder)
    ├── copilot_january_2026_focus_cur.csv
    └── ...
```

### Why are `usage_reports/`, `saas_template.csv`, and `focus_cur_outputs/` outside the project folder?

They are data files, not code. Keeping them outside the Python project folder means:
- They are not accidentally committed to git
- The same template can be shared across multiple projects
- The output folder stays clean and separate from code

All paths are configured in `config.ini` using relative paths from the `saas_to_focus_formatter/` directory, so `../` points to the parent folder.

---

## 5. The Three Key Files You Work With

As a user or operator, you only need to interact with three files:

| File | When you touch it | What you do |
|------|------------------|-------------|
| `config.ini` | Once at setup | Set your paths, billing account details, S3 settings |
| `mappers/<vendor>_mapper.json` | Once per new vendor | Review and optionally edit the auto-generated mapper |
| `usage_reports/*.csv` | Monthly | Drop the new billing export from the SaaS vendor portal |

Everything else (Python files, schema, template) is infrastructure — you do not need to edit it.

---

## 6. config.ini — The Control Panel

`config.ini` is the single place where you configure the project. Once set up correctly, you can run everything with just `python3 main.py run`.

### The Four Sections

**`[paths]` — File locations**

```ini
[paths]
usage_dir    = ../usage_reports/      ← Batch mode: folder of input CSVs
; usage_report  = ../usage_report.csv ← Single file mode (commented out)
output_dir   = ../focus_cur_outputs/  ← Where output CSVs are written
cur_template = ../saas_template.csv   ← The FOCUS column template
```

- `usage_dir` tells the tool "process all CSVs in this folder" — used by `run` and `transform`
- `usage_report` tells the tool "process this single file" — used by `generate` (and as fallback)
- If only `usage_dir` is set, `generate` automatically picks the first CSV from that folder

**`[billing]` — Your organisation's billing identity**

```ini
[billing]
provider_name        = GitHub              ← The SaaS vendor name
billing_account_id   = org-CoreStack-Engg  ← Your account ID at that vendor
billing_account_name = CoreStack Engineering
billing_currency     = USD
region_name          = global
```

These values appear in every row of every output CSV. They identify who the bill belongs to.

**`[mapper]` — Mapper file settings**

```ini
[mapper]
mapper         = mappers/copilot_mapper.json  ← Used by 'transform' command
tool_name      = copilot                      ← Hint for 'generate' command
product_family = Developer Tools              ← Hint for 'generate' command
```

**`[logging]` — Log and retry settings**

```ini
[logging]
log_dir     = logs    ← Where to write latest.log and run_state.json
max_retries = 1       ← How many times to retry a failing file (1 = no retry)
```

**`[s3]` — Optional AWS S3 upload (all commented out by default)**

```ini
[s3]
; bucket  = my-finops-bucket
; prefix  = focus-cur-outputs/
; region  = us-east-1
; profile = default
```

Uncomment `bucket` to enable S3 upload. The other three are optional.

### Priority Rule

When the same setting is available in multiple places, this is who wins:

```
CLI argument  >  config.ini  >  built-in code default
  (highest)                        (lowest)
```

Example: if `config.ini` says `provider_name = GitHub` but you run:
```bash
python3 main.py run --provider_name "GitHub Enterprise"
```
Then `GitHub Enterprise` wins because CLI arguments always override the config file.

---

## 7. The Three CLI Commands — Deep Explanation

All commands must be run from inside the `saas_to_focus_formatter/` directory:

```bash
cd /path/to/saas_to_focus_formatter
python3 main.py <command> [flags]
```

---

### Command 1: `generate`

**What it does in plain English:**
"Look at my SaaS CSV, figure out which columns map to which FOCUS columns, and write me a mapper JSON file I can use for future conversions."

**When to use it:**
- The very first time you process a new SaaS vendor
- When a vendor changes their CSV column names

**What it needs:**
- A SaaS usage export CSV (single file only — not a folder)
- The FOCUS schema file (`schemas/focus_schema.json` — already in the project)

**How it auto-detects column mappings:**
The generator uses a scoring system. For example, it knows:
- Any column containing "amount" or "cost" or "price" is probably a cost column
- Any column containing "date" or "period" is probably a date column
- Any column containing "user" or "username" or "org" is a good candidate for Tags

It scores every source column against every FOCUS target column and picks the best match.

**Command (using config.ini):**
```bash
python3 main.py generate
# Uses usage_dir first file OR usage_report from config.ini
```

**Command (with all flags explicit):**
```bash
python3 main.py generate \
    --usage_report  ../usage_reports/copilot_january_2026.csv \
    --tool_name     copilot \
    --provider_name "GitHub" \
    --product_family "Developer Tools" \
    --billing_currency USD \
    --output_mapper mappers/copilot_mapper.json
```

**What each flag does:**

| Flag | What it does |
|------|-------------|
| `--usage_report FILE` | Path to the SaaS CSV to inspect |
| `--tool_name NAME` | The vendor keyword (e.g. `copilot`, `datadog`, `claude`). Auto-detected from filename if omitted. |
| `--provider_name NAME` | Written into `defaults.ProviderName` in the mapper. Example: `GitHub`. |
| `--product_family NAME` | Written as a static value. Auto-inferred from tool_name if omitted. |
| `--billing_currency CODE` | ISO currency code. Default: `USD`. |
| `--output_mapper PATH` | Where to save the mapper JSON. Default: `mappers/<tool>_mapper.json`. |

**What it produces:**
```
mappers/copilot_mapper.json
```
Open and review this file before running the transform step.

**Important:** You should review the generated mapper. The generator is smart but not perfect. Check that cost columns map correctly, and that date columns got the right transform.

---

### Command 2: `transform`

**What it does in plain English:**
"Using the mapper JSON I already have, convert my SaaS CSV into a FOCUS-compliant CUR CSV. Validate that all required columns are populated before writing."

**When to use it:**
- Every month when you have new billing CSVs to convert
- When you already have a mapper and just want to convert

**What it needs:**
- The SaaS usage CSV (single file or a folder of files)
- An existing `mapper.json` for that vendor
- The `saas_template.csv` (column order template)

**Command (using config.ini — the simplest way):**
```bash
python3 main.py transform
# All paths and billing info come from config.ini
```

**Command — single file with all flags:**
```bash
python3 main.py transform \
    --usage_report         ../usage_reports/copilot_january_2026.csv \
    --mapper               mappers/copilot_mapper.json \
    --cur_template         ../saas_template.csv \
    --output               ../focus_cur_outputs/copilot_jan_focus_cur.csv \
    --provider_name        "GitHub" \
    --billing_account_id   "org-CoreStack-Engg" \
    --billing_account_name "CoreStack Engineering" \
    --billing_currency     USD
```

**Command — batch folder:**
```bash
python3 main.py transform \
    --usage_dir  ../usage_reports/ \
    --output_dir ../focus_cur_outputs/ \
    --mapper     mappers/copilot_mapper.json
```

**What each flag does:**

| Flag | What it does |
|------|-------------|
| `--usage_report FILE` | Single CSV to convert |
| `--usage_dir DIR` | Folder of CSVs — all `*.csv` processed alphabetically |
| `--mapper PATH` | The mapper JSON to use |
| `--cur_template PATH` | The FOCUS column order template |
| `--output PATH` | Output path for single-file mode |
| `--output_dir DIR` | Output folder for batch mode |
| `--provider_name NAME` | Overrides mapper defaults (Tier 1) |
| `--billing_account_id ID` | Overrides mapper defaults (Tier 1) |
| `--billing_account_name NAME` | Overrides mapper defaults (Tier 1) |
| `--billing_currency CODE` | Overrides mapper defaults (Tier 1) |
| `--region_name NAME` | Geographic region (default: global) |
| `--tag_key KEY` + `--tag_value VAL` | Injects an extra tag into every row |
| `--skip_validation` | Skips required-field check (for debugging) |
| `--s3_bucket BUCKET` | Upload output to S3 after local write |
| `--s3_prefix PREFIX` | Folder path inside the S3 bucket |
| `--s3_region REGION` | AWS region (e.g. `us-east-1`) |
| `--s3_profile PROFILE` | Named AWS credentials profile |

**What it produces:**
- Single-file mode: one output CSV at `--output` path
- Batch mode: one `<stem>_focus_cur.csv` per input file in `--output_dir`

---

### Command 3: `run`

**What it does in plain English:**
"Do everything in one shot — if I don't have a mapper yet, generate it; then transform all my CSVs. I don't want to run two separate commands."

**When to use it:**
- The most common way to run — just `python3 main.py run`
- Both first-time use and monthly re-runs
- In automated pipelines and cron jobs

**How it differs from calling `generate` then `transform` separately:**
- If a mapper already exists → it reuses it (skips generation)
- If no mapper exists → it generates one first, then immediately transforms
- `--regenerate_mapper` flag forces re-generation even if the mapper exists
- In batch mode, the correct mapper is auto-detected per file based on the column names

**Command (the simplest — everything from config.ini):**
```bash
python3 main.py run
```

**Command with common overrides:**
```bash
python3 main.py run \
    --provider_name "GitHub" \
    --billing_account_id "org-CoreStack-Engg" \
    --billing_account_name "CoreStack Engineering"
```

**Additional flags specific to `run`:**

| Flag | What it does |
|------|-------------|
| `--regenerate_mapper` | Force regeneration of mapper.json even if it already exists |
| `--mapper PATH` | Use a specific mapper for all files (skips auto-detection) |
| `--resume` | Skip files already marked `done` in `logs/run_state.json` |
| `--max_retries N` | Retry each failing file up to N times. Default: 1 (no retry). |

**Exit codes:**
- `0` = all files succeeded
- `2` = partial failure (some files failed, some succeeded)
- `1` = fatal error (bad arguments, missing config)

---

## 8. Important Flags — Resume, Retries, Log Dir

### `--resume` — Continue Where You Left Off

**What it does:**
Reads `logs/run_state.json` from the previous run. Skips any file that already has `status: done`. Only processes files that are still `pending` or `failed`.

**When to use it:**
- A run was interrupted partway through (power cut, Ctrl+C, network error)
- Some files failed and you fixed the problem and want to re-run only those files

```bash
# First run — 5/6 files succeed, june fails
python3 main.py run
# Fix the issue with june's CSV
# Re-run — only june is processed, the other 5 are skipped
python3 main.py run --resume
```

**How it knows what to skip:**
It reads the `status` field in `run_state.json`. Files with `status: done` are skipped. Files with `status: failed` or `status: pending` are included.

---

### `--max_retries N` — Retry Failed Files

**What it does:**
If a file fails during processing, retry it up to N times within the same run before giving up and marking it as failed.

```bash
python3 main.py run --max_retries 3
# Each file is tried up to 3 times if it keeps failing
```

**Default:** 1 (try once, move on if it fails — no retry).

**When to use it:**
- Transient failures (network blip, locked file, temporary I/O error)
- As extra safety in cron/pipeline runs

**In config.ini:**
```ini
[logging]
max_retries = 3
```

---

### `--log_dir DIR` — Custom Log Directory

**What it does:**
Changes where `latest.log` and `run_state.json` are written. Default: `logs/`.

```bash
python3 main.py run --log_dir /var/log/focus_converter/
```

**When to use it:**
- When running as a cron job — use `logs/cron/` to keep automated and manual logs separate
- When running multiple concurrent projects with different configs

---

### `--skip_validation` — Bypass Required-Field Check

**What it does:**
Normally, before writing any output, the engine checks that all 14 required FOCUS columns have values. If any are empty, it stops. This flag bypasses that check.

```bash
python3 main.py transform --skip_validation
```

**When to use it:**
- Debugging a new mapper that isn't fully populated yet
- You know some required columns will be empty and want to inspect the output anyway

**Warning:** Never use this for production outputs. Empty required columns will cause FinOps platform ingestion to fail.

---

## 9. The Mapper JSON — Anatomy and Deep Dive

The mapper JSON is the heart of the system. Each SaaS vendor gets exactly one mapper file.

### Full Structure

```json
{
  "meta": {                          ← Section 1: Information about this mapper
    "tool_name": "copilot",
    "generated_at": "2026-03-05T09:33:13Z",
    "source_columns": [              ← List of columns from the vendor's CSV
      "date", "product", "sku", "quantity", "unit_type",
      "applied_cost_per_quantity", "gross_amount", "discount_amount",
      "net_amount", "username", "organization", "repository",
      "workflow_path", "cost_center_name"
    ],
    "focus_version": "1.0",
    "generator": "saas_focus_converter/mapper_generator/generate_mapper.py"
  },

  "defaults": {                      ← Section 2: Static values injected into every row
    "ChargeCategory": "Usage",
    "ChargeFrequency": "Monthly",
    "BillingCurrency": "USD",
    "ProviderName": "GitHub"
  },

  "mappings": {                      ← Section 3: Per-column conversion rules
    "BillingPeriodStart": {
      "source": "date",              ← Read from this column in the input CSV
      "transform": "to_iso8601_start"← Apply this transform function
    },
    "BilledCost": {
      "source": "net_amount",
      "transform": "identity",
      "fallback_sources": ["applied_cost_per_quantity", "gross_amount"],
      "default_value": "0"           ← Use "0" if all sources are empty
    },
    "Tags": {
      "transform": "build_tags",     ← Special: aggregates multiple columns into JSON
      "tag_sources": [
        "username", "organization", "repository", "workflow_path", "cost_center_name"
      ]
    },
    "ProductFamily": {
      "transform": "static",         ← Special: always returns this fixed value
      "static_value": "Developer Tools"
    }
  }
}
```

### The Three Sections Explained

**`meta`** — Documentation only. Tells you which tool this mapper is for, when it was generated, and what the vendor CSV's columns were. The engine doesn't use this section for conversion — it's for human reference.

**`defaults`** — Static values applied to every row. These are things that don't change row-by-row — the billing currency, charge category, provider name. These are Tier 3 in the priority order.

**`mappings`** — The actual conversion rules. Each key is a FOCUS output column name. The value describes how to populate it:

| Mapping key | What it does |
|------------|-------------|
| `"source": "col_name"` | Read this column from the input CSV |
| `"transform": "identity"` | Copy the value unchanged |
| `"transform": "to_iso8601_start"` | Convert date to `YYYY-MM-DDT00:00:00Z` |
| `"transform": "humanize"` | Convert `copilot_for_business` → `Copilot For Business` |
| `"transform": "build_tags"` | Build a JSON object from multiple columns |
| `"transform": "static"` + `"static_value": "X"` | Always output the value `X` |
| `"fallback_sources": [...]` | If primary source is empty, try these columns in order |
| `"default_value": "0"` | If all sources are empty, use this value |

### All 13 Transform Functions

| Transform Name | Input → Output | Example |
|---------------|---------------|---------|
| `identity` | Pass through unchanged | `"19.99"` → `"19.99"` |
| `to_iso8601_start` | Any date → `YYYY-MM-DDT00:00:00Z` | `"2026-03-01"` → `"2026-03-01T00:00:00Z"` |
| `to_iso8601_end` | Any date → `YYYY-MM-DDT23:59:59Z` | `"2026-03-01"` → `"2026-03-01T23:59:59Z"` |
| `to_billing_period_end` | Any date → first instant of next month | `"2026-03-01"` → `"2026-04-01T00:00:00Z"` |
| `humanize` | snake_case/kebab → Title Case | `"copilot_for_business"` → `"Copilot For Business"` |
| `title_case` | Any string → Title Case | `"developer tools"` → `"Developer Tools"` |
| `to_uppercase` | Any string → UPPERCASE | `"usd"` → `"USD"` |
| `to_lowercase` | Any string → lowercase | `"GitHub"` → `"github"` |
| `strip_whitespace` | Trim leading/trailing spaces | `"  foo  "` → `"foo"` |
| `to_decimal` | Normalize cost string | `"$1,234.56"` → `"1234.56"` |
| `build_tags` | Multiple columns → compact JSON | `{"username":"alice","org":"CoreStack"}` |
| `static` | Always return a fixed value | always `"Developer Tools"` |
| `first_non_empty` | Try multiple columns in order | tries `col_a`, then `col_b`, returns first non-empty |

### How Date Parsing Works

The date transforms support **7 input formats**. You do not need to know the format in advance — the engine tries them all:

| Input format | Example input | Transforms to |
|-------------|--------------|--------------|
| `YYYY-MM-DDThh:mm:ssZ` | `2026-03-01T00:00:00Z` | strips time |
| `YYYY-MM-DDThh:mm:ss` | `2026-03-01T14:30:00` | strips time |
| `YYYY-MM-DD` | `2026-03-01` | standard |
| `YYYY/MM/DD` | `2026/03/01` | converts slashes |
| `MM/DD/YYYY` | `03/01/2026` | US format |
| `DD-MM-YYYY` | `01-03-2026` | European format |
| `YYYY-MM-DD hh:mm:ss` | `2026-03-01 14:30:00` | strips time |

---

## 10. The SKILL File — `/generate-mapper`

**File:** `SKILL_saas_to_cur_converter.md` (in the parent `output/` folder)

This file defines a **Claude Code skill** (slash command). It is not Python code — it is a markdown playbook that Claude Code reads when you type `/generate-mapper` in the Claude Code CLI.

### What the skill does

When you type `/generate-mapper` in Claude Code:
1. Claude reads `usage_report.csv` from the workspace
2. Claude applies the same semantic scoring logic as `generate_mapper.py`
3. Claude writes `mappers/<tool_name>_mapper.json`
4. Claude asks: "Run the transform now?"
5. If you say yes, Claude executes `python3 main.py transform`

### When to use the skill vs. the CLI command

| Use | When |
|----|------|
| `/generate-mapper` (Claude Code skill) | Interactive use — you want Claude to generate the mapper and explain it step by step |
| `python3 main.py generate` (CLI) | Automated use — pipeline, cron job, scripted workflow |

### What is in the SKILL file

The SKILL file is structured documentation that tells Claude Code:
- The exact steps to follow when the skill is triggered
- How to interpret CSV column names
- What scoring rules to apply
- What mapper JSON structure to produce
- How to ask follow-up questions and offer to run the transform

You should never need to edit this file unless you want to change the behavior of the Claude Code `/generate-mapper` command.

---

## 11. The Makefile

**File:** `saas_to_focus_formatter/Makefile`

The Makefile provides convenient shortcuts so you don't have to remember long commands.

| Target | Command | What it does |
|--------|---------|-------------|
| `make help` | `make` | Shows all available targets |
| `make setup` | `make setup` | Creates a Python virtual environment and installs dependencies |
| `make test` | `make test` | Runs all 168 unit tests |
| `make run-config` | `make run-config` | Runs the full pipeline using settings from `config.ini` |
| `make run-example` | `make run-example` | Example single-file run (hardcoded paths for demo) |
| `make run-batch-example` | `make run-batch-example` | Example batch run (hardcoded paths for demo) |
| `make clean` | `make clean` | Deletes the virtual environment and `__pycache__` directories |

**When is it useful?**
- `make test` is the fastest way to run all tests
- `make run-config` is the fastest way to run the pipeline if `config.ini` is set up
- `make setup` is for first-time environment setup

---

## 12. The README

**File:** `saas_to_focus_formatter/README.md`

The README is the complete user guide for the project. It covers:

1. **Project structure** — visual directory tree
2. **Prerequisites** — Python 3.10+, no third-party packages
3. **Setup** — three methods: venv, Make, system Python
4. **Running tests** — all test commands
5. **Config file** — every key in `config.ini` explained
6. **Logging and auditing** — log file format, `run_state.json` structure
7. **AWS S3 upload** — 4-step setup guide, credential methods
8. **Input modes** — single file vs. batch folder
9. **All three commands** — with all flags documented
10. **Full workflows** — step-by-step for new vendor and monthly batch
11. **FOCUS output columns** — all 23 columns with required/optional labels
12. **Troubleshooting** — common errors and their fixes
13. **Transform functions** — all 13 with examples
14. **Adding a new vendor** — zero-code process

**When to read it:**
- When you first join the project
- When you encounter an error and need the troubleshooting table
- When you want to add a new SaaS vendor

---

## 13. All Test Files — One by One

The project has **168 unit tests** across 4 test files. All tests are pure (no I/O, no network, no file writes) and run in under 1 second.

---

### `tests/test_field_transformations.py` — 63 tests

**What it tests:** Every one of the 13 transform functions in `field_transformations.py`

**Test classes and what they verify (in plain English):**

**`TestIdentity` (3 tests)**
- Passing `"hello"` through identity gives back `"hello"` — no change
- An empty string stays empty
- A number string `"3.14"` comes through unchanged

**`TestToIso8601Start` (8 tests)**
- Standard date `"2026-03-15"` → `"2026-03-15T00:00:00Z"` (start of day)
- Date+time input → only the date part is kept, time becomes 00:00:00
- Slash format `"2026/03/15"` → standard format
- US format `"03/15/2026"` → standard format
- European format `"15-03-2026"` → standard format
- Empty input → empty output (does not crash)
- Unparseable input → empty output (does not crash)

**`TestToIso8601End` (5 tests)**
- Standard date → `"2026-03-15T23:59:59Z"` (end of day)
- Date+time → strips time, gives 23:59:59
- Empty → empty; invalid → empty; December 31 works correctly

**`TestToBillingPeriodEnd` (6 tests)**
- Mid-month date (March 15) → first of April (`"2026-04-01T00:00:00Z"`)
- First of month (March 1) → still gives April 1
- December → January of next year (year rolls over correctly)
- Empty → empty; invalid → empty

**`TestHumanize` (6 tests)**
- Underscores removed: `"copilot_for_business"` → `"Copilot For Business"`
- Hyphens removed: `"datadog-apm-metrics"` → `"Datadog Apm Metrics"`
- Mixed separators work
- Already clean text is just title-cased
- Empty stays empty
- Consecutive underscores `"a__b"` → `"A B"` (collapsed to one space)

**`TestTitleCase` (3 tests)**
- Lowercase → Title Case
- Already Title Case stays the same
- Note: unlike `humanize`, `title_case` does NOT replace underscores/hyphens

**`TestToUppercase` / `TestToLowercase` (5 tests)**
- Case conversion works in both directions

**`TestStripWhitespace` (3 tests)**
- Leading/trailing spaces removed
- Internal spaces preserved: `"  foo bar  "` → `"foo bar"`
- No spaces → unchanged

**`TestToDecimal` (9 tests)**
- Integer string `"100"` → `"100"`
- Float `"3.14"` → `"3.14"`
- Currency symbol stripped: `"$1234.56"` → `"1234.56"`
- Comma separator removed: `"$1,234.56"` → `"1234.56"`
- Empty → `"0"` (not empty — defaults to zero)
- Whitespace only → `"0"`
- Invalid string → `"0"` (does not crash)
- Negative numbers work: `"-5.00"` → `"-5.00"`
- Zero stays zero

**`TestBuildTags` (8 tests)**
- List of column names → JSON object: `{"username":"alice","organization":"CoreStack-Engg"}`
- Column name aliases: rename `"username"` → `"user"` in output tags
- Empty column values are excluded from the JSON (no null/empty keys)
- No row provided → empty JSON `{}`
- No config provided → empty JSON `{}`
- Column not found → excluded from output
- Case-insensitive: `"USERNAME"` in the row matches `"username"` in tag_sources
- Output is compact JSON (no spaces): `{"k":"v"}` not `{"k": "v"}`

**`TestStaticValue` (4 tests)**
- Returns the configured static value regardless of input
- Ignores the source value entirely
- No config → empty string
- Config without the key → empty string

**`TestFirstNonEmpty` (4 tests)**
- Returns the first non-empty column from a list
- Falls back to the original source value if all listed columns are empty
- No row → returns original value unchanged
- No config → returns original value unchanged

**`TestLookupColumn` (6 tests)**
- Exact column name match
- Case-insensitive match: `"NET_AMOUNT"` finds `"net_amount"` in the row
- Substring match: `"amount"` finds `"net_amount"`
- Missing column → empty string (does not crash)
- Empty row → empty string
- Strips whitespace from the value

**`TestApplyTransform` (4 tests)**
- Calling a valid transform by name works
- Date transform works by name
- Unknown transform name raises `ValueError` with the transform name and list of available names in the error message
- Output is always a string type

---

### `tests/test_transformer.py` — 38 tests

**What it tests:** The `MapperDrivenTransformer` class in `transformer.py` — the conversion engine

**Test classes:**

**`TestThreeTierResolution` (5 tests)**
These verify the priority order: CLI > mappings > defaults.

- CLI param wins over mapper defaults: passing `ProviderName=Override` in CLI params gives `Override` in output, not the mapper default
- Mapper defaults are used when no mapping exists: `ChargeCategory` from defaults → `"Usage"`
- Mapper mappings produce transformed values: `date` column → `"2026-03-15T00:00:00Z"`
- Missing column with no default → empty string (does not crash, just gives `""`)
- Output always contains all schema columns, even if empty

**`TestTransformRowBehaviours` (5 tests)**
These verify individual transform behaviors end-to-end through the full engine:

- `humanize` transform: `"copilot_for_business"` → `"Copilot For Business"` in `ServiceName`
- `static` transform: `ProductFamily` always shows `"Developer Tools"` regardless of input
- `build_tags`: output is a JSON object with `username` and `organization` keys
- `to_billing_period_end`: date in March gives April 1 as `BillingPeriodEnd`
- Cost passthrough: `"19.99"` in `cost` column appears unchanged in `BilledCost`

**`TestFallbackSources` (3 tests)**
These verify the fallback mechanism when the primary source column is empty:

- If `net_amount` is empty, falls back to `gross_amount`
- If both `net_amount` and `gross_amount` are empty, uses `default_value: "0"`
- If `net_amount` has a value, uses it (does not fall through to fallback)

**`TestValidateRequiredColumns` (3 tests)**
These verify that validation correctly catches missing required columns:

- All 14 required columns filled → validation passes, returns empty list
- Missing billing columns → raises `ValueError` listing the missing column names
- Completely empty mapper → lists ALL required columns in the error message

**`TestInjectExtraTag` (7 tests)**
These verify the `--tag_key / --tag_value` injection feature:

- Injecting into empty tags `{}` → tag appears in JSON
- Injecting into existing tags → new tag added, existing tags preserved
- Empty tag key → nothing happens, original tags unchanged
- Overwriting an existing key → new value wins
- Row with no `Tags` column at all → `Tags` column is created
- Malformed JSON in `Tags` → gracefully recovered, injection still works
- Output is always compact JSON (no spaces)

**`TestFirstNonEmptyMapping` (2 tests)**
- `first_non_empty` transform via mapper: tries `empty_col` (empty), finds `username` (has value)
- Falls back to `default_value` when all listed columns are empty

---

### `tests/test_generate_mapper.py` — 50 tests

**What it tests:** The mapper generator's scoring, matching, and inference functions

**Test classes:**

**`TestScoreColumn` (6 tests)**
Tests the scoring function that decides how well a source column name matches a FOCUS column:

- Column with no pattern match → score 0
- Exact pattern match → returns the configured score (10)
- Substring match: `"net_amount"` contains `"amount"` → gets that score (3)
- Best score wins when multiple patterns match
- Matching is case-insensitive
- Hyphens treated as underscores: `"net-amount"` matches `"net_amount"`

**`TestFindBestMatch` (6 tests)**
Tests the function that picks the best source column for each FOCUS column:

- `"BillingPeriodStart"` + columns `["date", "product", "cost"]` → picks `"date"` with `to_iso8601_start` transform
- `"BilledCost"` + columns `["product", "net_amount", "quantity"]` → picks `"net_amount"`
- When two columns score differently, the higher score wins (`"net_amount"` beats `"cost"`)
- No match found → returns `None` (mapper will have no entry for that column)
- Unknown FOCUS column → returns `None`
- `"ServiceName"` prefers `humanize` transform over `identity`

**`TestDetectTagSources` (8 tests)**
Tests which columns get identified as tag candidates:

- `"username"` detected as a tag source
- `"organization"` detected
- `"repository"` detected
- `"cost_center_name"` detected
- Pure data columns (`date`, `product`, `cost`, `quantity`) → never become tags
- Empty result when no tag columns present
- Mixed columns: tag columns included, non-tag excluded
- Case-insensitive: `"Username"` and `"ORGANIZATION"` still detected

**`TestInferProductFamily` (9 tests)**
Tests the vendor→category lookup table:

- `"copilot"` → `"Developer Tools"`
- `"github"` → `"Developer Tools"`
- `"claude"` → `"AI / Machine Learning"`
- `"anthropic"` → `"AI / Machine Learning"`
- `"datadog"` → `"Observability"`
- `"snowflake"` → `"Data & Analytics"`
- `"salesforce"` → `"CRM"`
- Unknown vendor → `"SaaS"` (safe fallback)
- Case-insensitive: `"Copilot"` → `"Developer Tools"`

**`TestInferToolName` (4 tests)**
Tests how the tool detects the vendor name:

- From the `product` column value: row with `product=copilot_for_business` → detects `"copilot"`
- From the filename: `"slack_report.csv"` → detects `"slack"` (strips `_report`)
- Strips year from filename: `"copilot_usage_2026.csv"` → `"copilot"`
- Falls back to filename when no rows available

**`TestInferDefaultUnit` (6 tests)**
Tests how the default unit of measure is inferred:

- If sample data has the value → uses that: `"user-months"` from data → `"user-months"`
- AI tool with no data → `"Tokens"`
- Copilot with no data → `"Seats"`
- Datadog → `"Events"`
- Snowflake → `"Credits"`
- Unknown vendor → `"Units"`

**`TestGenerateMapper` (11 tests)**
Integration tests — generate a full mapper for Copilot and verify the output structure:

- Mapper has all three top-level keys: `meta`, `defaults`, `mappings`
- `meta.tool_name` is correct
- `meta.source_columns` lists all 14 input columns
- `defaults` includes `ChargeCategory: Usage`, `ChargeFrequency: Monthly`, `BillingCurrency: USD`
- `BillingPeriodStart` is mapped to `"date"` with `to_iso8601_start`
- `BilledCost` is mapped to `"net_amount"` with `default_value: "0"`
- `Tags` mapping uses `build_tags` with all contextual columns
- `ProductFamily` uses `static` transform
- CLI-only columns (`ProviderName`, `BillingAccountId`, `BillingAccountName`) are NOT in mappings (they come from CLI Tier 1)
- Static columns (`ChargeCategory`, `ChargeFrequency`, `BillingCurrency`) are NOT in mappings (they come from defaults Tier 3)
- Custom `product_family` override works
- Custom currency override works
- Empty `provider_name` is not written to defaults

---

### `tests/test_main.py` — 17 tests

**What it tests:** The path-resolution helper functions in `main.py` — not the transform logic

**Test classes:**

**`TestGetInputFiles` (8 tests)**
Tests the function that decides which CSV files to process:

- Single file (`--usage_report`) → returns list with that one file
- `--usage_dir` + 3 CSV files → returns them in alphabetical order (alpha → bravo → charlie)
- Non-CSV files (`.txt`, `.json`) in the folder → excluded from results
- Folder with only one CSV → returns that one file
- Empty folder → raises `ValueError` with the folder path in the message
- Folder with no CSV files (only `.txt`) → raises `ValueError`
- When both `--usage_dir` and `--usage_report` are set → `usage_dir` wins
- Folder with 5 CSV files → all 5 returned

**`TestResolveOutputPath` (9 tests)**
Tests the function that decides where the output file is written:

- Single-file mode → output goes to `args.output` path
- Custom `--output` path is respected
- Batch mode → output filename is `<input_stem>_focus_cur.csv`
- Batch mode → output is placed inside `--output_dir`
- Batch mode with non-existent `output_dir` → directory is created automatically
- Stem extraction: `"data.csv"` → `"data_focus_cur.csv"`, `"vendor_export.csv"` → `"vendor_export_focus_cur.csv"`
- Deep input path `/some/deep/path/slack_march.csv` → output is just `slack_march_focus_cur.csv` in `output_dir`
- Single-file mode with `output_dir=None` → same output for any input path

---

## 14. How to Run Tests — Every Command

All test commands are run from inside `saas_to_focus_formatter/`:

```bash
cd saas_to_focus_formatter
```

### Run all 168 tests at once

```bash
# Standard — shows test names
python3 -m unittest discover -s tests -v

# Using Make (shortest)
make test
```

Expected output: `Ran 168 tests in 0.016s — OK`

### Run a specific test file

```bash
# Only field transformation tests (63 tests)
python3 -m unittest tests.test_field_transformations -v

# Only transformer engine tests (38 tests)
python3 -m unittest tests.test_transformer -v

# Only mapper generator tests (50 tests)
python3 -m unittest tests.test_generate_mapper -v

# Only batch helper tests (17 tests)
python3 -m unittest tests.test_main -v
```

### Run a specific test class

```bash
# Only the three-tier priority tests
python3 -m unittest tests.test_transformer.TestThreeTierResolution -v

# Only the date transform tests
python3 -m unittest tests.test_field_transformations.TestToIso8601Start -v

# Only the mapper generation integration tests
python3 -m unittest tests.test_generate_mapper.TestGenerateMapper -v

# Only the batch folder tests
python3 -m unittest tests.test_main.TestGetInputFiles -v
```

### Run a single test method

```bash
# A specific test by full path
python3 -m unittest tests.test_transformer.TestThreeTierResolution.test_tier1_cli_wins_over_defaults -v

# Test that CLI overrides work
python3 -m unittest tests.test_transformer.TestThreeTierResolution.test_tier1_cli_wins_over_defaults -v

# Test that December rolls over to January in billing period
python3 -m unittest tests.test_field_transformations.TestToBillingPeriodEnd.test_december_rolls_over -v

# Test that empty folder raises an error
python3 -m unittest tests.test_main.TestGetInputFiles.test_empty_folder_raises_value_error -v
```

### Run tests without verbose output

```bash
# Just the summary line
python3 -m unittest discover -s tests
```

### Check test count per file

```bash
# Run each file and check the count at the bottom
python3 -m unittest tests.test_field_transformations 2>&1 | tail -3
python3 -m unittest tests.test_transformer 2>&1 | tail -3
python3 -m unittest tests.test_generate_mapper 2>&1 | tail -3
python3 -m unittest tests.test_main 2>&1 | tail -3
```

---

## 15. Understanding the Input, Template, and Output Files

### The Input File — `usage_reports/*.csv`

**What it is:**
The billing or usage export you download from a SaaS vendor's portal. Every vendor exports differently.

**Example — GitHub Copilot export:**

| date | product | sku | quantity | unit_type | applied_cost_per_quantity | gross_amount | discount_amount | net_amount | username | organization | repository | workflow_path | cost_center_name |
|------|---------|-----|----------|-----------|--------------------------|--------------|-----------------|------------|----------|-------------|------------|--------------|-----------------|
| 2026-01-01 | copilot_for_business | copilot_for_business_seat | 1 | user-months | 0 | 19.00 | 0 | 19.00 | alice | CoreStack-Engg | api-gateway | | eng |
| 2026-01-01 | copilot_for_business | copilot_for_business_seat | 1 | user-months | 0 | 19.00 | 0 | 19.00 | bob | CoreStack-Engg | frontend | | eng |

Key characteristics:
- One row per user per billing period
- Column names are vendor-specific (not FOCUS standard)
- Date might be in any format (`YYYY-MM-DD`, `MM/DD/YYYY`, etc.)
- Costs might have currency symbols (`$19.00`) or commas (`$1,234.56`)
- The file may have a BOM (byte-order mark) — the engine handles this transparently

**Where to get it:**
Each SaaS vendor has a billing portal. Download the CSV export for the billing period you want to process.

**Naming convention:**
We use `<vendor>_<month>_<year>.csv` (e.g. `copilot_january_2026.csv`). This is just a convention — any filename works.

---

### The Template File — `saas_template.csv`

**What it is:**
A CSV file where row 0 (the header row) contains all 23 FOCUS output column names in the correct order.

**Why it exists:**
FOCUS 1.0 requires a specific set of column names. The template is the authoritative source for what those columns are and what order they appear in. The transformation engine reads this file to know what columns to write in the output.

**Content:**
```
ProviderName,BillingAccountId,BillingAccountName,BillingCurrency,BillingPeriodEnd,
BillingPeriodStart,BilledCost,EffectiveCost,ListCost,ChargeCategory,ChargeFrequency,
ChargePeriodEnd,ChargePeriodStart,ServiceName,ConsumedQuantity,ConsumedUnit,
RegionName,ResourceId,ResourceName,SkuId,Tags,UsageType,ProductFamily
```

**Important:** Never modify this file. It is the shared contract between the conversion tool and the FinOps platform. If it changes, the FinOps platform ingestion will break.

**The 14 required FOCUS columns** (must always be populated):
- `ProviderName`, `BillingAccountId`, `BillingAccountName`, `BillingCurrency`
- `BillingPeriodEnd`, `BillingPeriodStart`
- `BilledCost`, `EffectiveCost`, `ListCost`
- `ChargeCategory`, `ChargeFrequency`
- `ChargePeriodEnd`, `ChargePeriodStart`
- `ServiceName`

The other 9 columns (`ConsumedQuantity`, `ConsumedUnit`, `RegionName`, `ResourceId`, `ResourceName`, `SkuId`, `Tags`, `UsageType`, `ProductFamily`) are optional — they can be empty without failing validation.

---

### The Output File — `focus_cur_outputs/*_focus_cur.csv`

**What it is:**
A FOCUS 1.0-compliant CUR CSV with the 23 standard columns, one row per row in the input CSV.

**Example output row:**

| ProviderName | BillingAccountId | BillingAccountName | BillingCurrency | BillingPeriodEnd | BillingPeriodStart | BilledCost | EffectiveCost | ListCost | ChargeCategory | ChargeFrequency | ChargePeriodEnd | ChargePeriodStart | ServiceName | ... | Tags |
|-------------|-----------------|-------------------|-----------------|-----------------|-------------------|------------|---------------|----------|----------------|-----------------|-----------------|------------------|-------------|-----|------|
| GitHub | org-CoreStack-Engg | CoreStack Engineering | USD | 2026-02-01T00:00:00Z | 2026-01-01T00:00:00Z | 19.00 | 19.00 | 19.00 | Usage | Monthly | 2026-01-01T23:59:59Z | 2026-01-01T00:00:00Z | Copilot For Business | ... | `{"username":"alice","organization":"CoreStack-Engg","repository":"api-gateway"}` |

Key characteristics:
- **Same row count as input** — one row per input row, no merging, no splitting
- **Standard column names** — the FinOps platform understands these immediately
- **ISO-8601 dates** — `2026-01-01T00:00:00Z` format, always UTC
- **Tags as JSON** — a compact JSON string in the `Tags` column
- **Named `<input_stem>_focus_cur.csv`** in batch mode

**Naming:**
- Batch mode: `copilot_january_2026.csv` → `copilot_january_2026_focus_cur.csv`
- Single file mode: name specified by `--output` or `config.ini`

---

## 16. Priority Order — Who Wins When Values Conflict

When the same FOCUS column could get its value from multiple places, this is the strict priority:

```
Tier 1 — CLI argument        (ALWAYS WINS)
  python3 main.py run --provider_name "Override"
  This beats everything.

Tier 2 — Mapper mappings    (wins if no CLI override)
  "mappings": { "BilledCost": { "source": "net_amount" } }
  Reads the source column, applies the transform function.

Tier 3 — Mapper defaults    (lowest priority)
  "defaults": { "ChargeCategory": "Usage" }
  Static values that never change per row.
```

**Practical example:**

`config.ini` says `billing_currency = USD`. Your mapper says `"BillingCurrency": "USD"` in defaults. But you run:
```bash
python3 main.py run --billing_currency EUR
```
Result: `EUR` in every output row, because CLI wins.

---

## 17. Logs and Audit Trail

Every run writes two files to `logs/` (created automatically):

### `logs/latest.log`

A human-readable structured log. Overwritten every run (always shows the current run).

**Format:**
```
2026-03-05 11:56:22  INFO   ========================================================================
2026-03-05 11:56:22  INFO   RUN START   run_id=20260305_115622    command=run
2026-03-05 11:56:22  INFO   Config      : /path/to/config.ini
2026-03-05 11:56:22  INFO   Input files : 6
2026-03-05 11:56:22  INFO     [1/6] ../usage_reports/copilot_april_2026.csv
...
2026-03-05 11:56:22  INFO   [1/6] START   ../usage_reports/copilot_april_2026.csv
2026-03-05 11:56:22  INFO   [1/6]   output : ../focus_cur_outputs/copilot_april_2026_focus_cur.csv
2026-03-05 11:56:22  INFO   [1/6]   mapper : mappers/copilot_mapper.json
2026-03-05 11:56:22  INFO   [1/6] DONE    rows=21      elapsed=0.01s
...
2026-03-05 11:56:22  INFO   RUN COMPLETE   done=6  failed=0  skipped=0  rows=122  elapsed=0.02s
```

### `logs/run_state.json`

A JSON checkpoint updated after every file. Used by `--resume`.

**Structure:**
```json
{
  "run_id": "20260305_115622",
  "command": "run",
  "files": {
    "../usage_reports/copilot_january_2026.csv": {
      "status": "done",
      "started_at": "2026-03-05T11:56:22Z",
      "output": "../focus_cur_outputs/copilot_january_2026_focus_cur.csv",
      "mapper": "mappers/copilot_mapper.json",
      "attempts": 1,
      "rows": 19,
      "elapsed_s": 0.003
    },
    "../usage_reports/copilot_bad.csv": {
      "status": "failed",
      "error": "Mapper file not found: mappers/bad_mapper.json",
      "attempts": 1
    }
  },
  "summary": { "done": 5, "failed": 1, "total_rows": 101 }
}
```

**Status values:**

| Status | Meaning |
|--------|---------|
| `pending` | Not yet processed in this run |
| `in_progress` | Currently being processed |
| `done` | Completed successfully |
| `failed` | Failed after all retries |
| `retrying` | Failed once, will be retried |

---

## 18. Adding a New SaaS Vendor — Zero Code Required

This is the key feature. Adding any new vendor takes under 15 minutes:

```bash
# Step 1 — Get the vendor's billing export CSV
# Download it from the vendor portal. Save it in usage_reports/.

# Step 2 — Generate the mapper
cd saas_to_focus_formatter
python3 main.py generate \
    --usage_report ../usage_reports/datadog_march_2026.csv \
    --tool_name    datadog \
    --provider_name "Datadog"
# Output: mappers/datadog_mapper.json

# Step 3 — Review the mapper
# Open mappers/datadog_mapper.json
# Check that cost columns are mapped correctly
# Check that date columns got the right transform
# Edit if needed

# Step 4 — Test the conversion
python3 main.py transform \
    --usage_report ../usage_reports/datadog_march_2026.csv \
    --mapper       mappers/datadog_mapper.json \
    --billing_account_id "acct-123" \
    --billing_account_name "CoreStack"
# Check the output CSV

# Step 5 — For next month, just run:
python3 main.py run
# The engine auto-detects datadog's mapper from the CSV column names
```

No Python code written. The mapper JSON is the only artifact.

---

## 19. Common Errors and What They Mean

| Error message | What went wrong | How to fix it |
|--------------|----------------|---------------|
| `No input CSV specified` | No CSV path given and none in config.ini | Add `usage_dir` or `usage_report` to `config.ini` |
| `No mapper specified` | Running `transform` without pointing to a mapper | Add `--mapper PATH` or `mapper.mapper` in `config.ini` |
| `Mapper file not found: mappers/X_mapper.json` | The mapper JSON doesn't exist | Run `generate` first to create it |
| `Required FOCUS columns are empty: BillingAccountId` | Missing billing metadata | Add `--billing_account_id "your-id"` or set in `[billing]` section |
| `No .csv files found in directory: ../usage_reports/` | The input folder is empty | Add CSV files to the folder |
| `Unknown transform: 'my_typo'` | Typo in mapper.json transform name | Check spelling against the 13 transform names |
| `Could not parse date string: '...'` | Date format not recognised | Add the format to `_DATE_FORMATS` in `field_transformations.py` |
| `ModuleNotFoundError` | Running from wrong directory | `cd saas_to_focus_formatter` first |
| Exit code `2` | Some files failed, some succeeded | Check `logs/latest.log`; fix issues; run with `--resume` |
| `ImportError: boto3 is required` | S3 enabled but boto3 not installed | `pip install boto3` |
| `NoCredentialsError` | S3 enabled but no AWS credentials | Set `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` or run `aws configure` |

---

*This KT document covers the complete system. For the authoritative command reference, see `README.md`. For the product requirements, see `PRD_saas_to_focus_formatter.md`. For the technical specification, see `TECH_SPEC_saas_to_focus_formatter.md`.*

---

## 20. Development Prompts — How This Project Was Built

This section documents the prompts used to develop this project via AI-assisted development. They are preserved here as a historical record so team members can understand the intent behind each evolution of the codebase.

---

### Prompt 1 — Main Prompt (Initial Requirements)

> I have two different input files:
>
> **Usage Report File**
> - This is a tool-specific usage report (for example: Copilot, Claude, or any other SaaS/monitoring tool).
> - The schema can vary depending on the tool.
> - Some billing-related fields (e.g., `billing_account_id`, `billing_account_name`) are not present in this file.
> - Product-related attributes such as product family, service name, SKU, usage quantity, usage date, etc., may be present and need to be mapped.
>
> **SaaS CUR Template File**
> - This represents the target AWS Cost and Usage Report (CUR)–like SaaS template.
> - The output must strictly follow this template's schema and formatting.
>
> **Objective**
>
> Generate a standalone script that:
> - Accepts a usage report file and a CUR SaaS template file as inputs.
> - Converts the usage report into the CUR-compliant SaaS format.
> - Automatically maps fields from the usage report to the appropriate CUR fields wherever possible.
> - Handles missing fields gracefully.
>
> **Functional Requirements**
>
> *Automatic Field Mapping*
> - Detect and map common fields automatically (e.g., usage date, service name, product family, usage quantity, unit, cost).
> - Map product-related attributes (product family, service, SKU, usage type, etc.) from the usage report to the CUR schema.
>
> *Parameter-Driven Missing Fields*
> - Fields that are not present in the usage report (e.g., `billing_account_id`, `billing_account_name`, payer account details) must be:
>   - Accepted as runtime parameters when executing the script.
>   - Injected into the output CUR file for all relevant records.
> - Example runtime parameters:
>   - `--billing_account_id`
>   - `--billing_account_name`
>   - `--payer_account_id`
>   - Any other mandatory CUR fields not derivable from the usage report.
>
> *Extensibility*
> - The script should support any similar usage report, not just Copilot or Claude.
> - Mapping logic should be configurable or easily extendable for new tools and schemas.
>
> **Output**
> - Generate a CUR-formatted output file that strictly follows the SaaS CUR template.
> - Ensure data consistency and prevent cost or usage mismatches.
> - The output should be ready to upload to an AWS S3 bucket.
>
> **Operational Constraints**
> - The script should be efficient and avoid memory or CPU spikes (suitable for large files).
> - Maintain clean, production-quality code with clear structure and logging.
> - Do not change the template structure — only populate and map fields.
>
> **Deliverable**
> - A single, runnable script (with clear CLI arguments).
> - Brief inline documentation or comments explaining:
>   - Mapping logic
>   - Required parameters
>   - How to extend mappings for new tools

---

### Prompt 2 — Region Name Parameter

> In the current code changes, can we also have a param for region name. If it is provided as a param, use that region name. If it is available in the CSV, take that as the region. If it is not available in the CSV and not given as the param, leave empty like now.

*This added the `--region` CLI flag with the following priority order: CLI param → CSV column → empty string.*

---

### Prompt 3 — Code Cleanup

> Code clean up prompt.

*A general refactoring and cleanup pass was performed to improve code readability, remove duplication, and ensure production-quality structure.*

---

### Prompt 4 — README Generation

> Create the README file for this code execution, with the sample command and its execution.

*This produced the initial `README.md` with usage instructions, CLI argument descriptions, and worked examples.*

---

### Prompt 5 — Open Source Preparation

> You are working on a Python utility project that converts SaaS usage exports into AWS FOCUS / CUR format.
>
> This project will be open sourced and must be fully standalone and portable, so anyone can clone the repository and run it easily from any machine.
>
> Update the project with the following requirements:
>
> **1. Dependency Management**
> - Generate a `requirements.txt` file that contains all external Python dependencies used in the project.
> - Ensure the file only contains required libraries with compatible versions.
> - Remove any unused imports.
>
> **2. Virtual Environment Support**
>
> Add instructions and optional helper scripts so that the project can run inside a Python virtual environment (`venv`). The setup process should support the following workflow:
>
> ```bash
> git clone <repo>
> cd <repo>
>
> python -m venv venv
> source venv/bin/activate   # Mac/Linux
> venv\Scripts\activate      # Windows
>
> pip install -r requirements.txt
> ```
>
> **3. Project Setup Documentation**
>
> Update or create a `README.md` with a clear Setup and Run section that includes:
> - Python version requirement
> - Steps to create and activate venv
> - Installing dependencies from `requirements.txt`
> - Running the utility
>
> **4. Optional Improvements**
>
> If useful, also include:
> - `.gitignore` entry for: `venv/`, `__pycache__/`, `*.pyc`
> - A Makefile or setup script (optional) to simplify setup:
>   ```
>   make setup
>   make run
>   ```
>
> **5. Goal**
>
> Ensure that any developer can clone the repository and run the tool with minimal setup, without modifying system Python or installing global dependencies.
>
> Provide:
> - `requirements.txt`
> - Updated `README.md`
> - Any required setup scripts or project structure improvements

---
