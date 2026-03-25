# SaaS Usage → FOCUS / CUR Converter

A mapper-driven Python framework that converts any SaaS usage export (GitHub Copilot, Anthropic Claude, Datadog, and more) into an AWS **FOCUS / CUR-compliant CSV** — ready for FinOps tools and cost analytics pipelines.

Supports both **single-file** and **batch folder** input modes.

---

## Project Structure

```
saas_to_focus_formatter/
│
├── main.py                              # CLI entry point
├── config.ini                           # Project config: paths, billing, mapper, logging
├── README.md                            # This file
├── requirements.txt                     # Dependencies (stdlib only — nothing to install)
├── Makefile                             # Setup / test / run shortcuts
├── .gitignore
│
├── audit/
│   └── run_logger.py                    # Structured log file + JSON checkpoint (resume)
│
├── mapper_generator/
│   └── generate_mapper.py               # Auto-generates mapper.json from any CSV
│
├── transform_engine/
│   ├── transformer.py                   # Mapper-driven conversion engine
│   └── field_transformations.py         # 13 pluggable transform functions
│
├── schemas/
│   └── focus_schema.json                # FOCUS 1.0 column reference
│
├── mappers/
│   └── copilot_mapper.json              # Example mapper — GitHub Copilot
│
├── logs/                                # Created on first run
│   ├── latest.log                       # Full structured log (overwritten each run)
│   └── run_state.json                   # JSON checkpoint for --resume
│
└── tests/
    ├── test_field_transformations.py    # 63 tests
    ├── test_transformer.py              # 38 tests
    ├── test_generate_mapper.py          # 50 tests
    └── test_main.py                     # 17 tests (batch helpers)
```

**External files (place in the parent folder, one level above `saas_to_focus_formatter/`):**

```
usage_reports/          ← Folder of SaaS vendor exports (batch input)
  ├── copilot_march.csv
  ├── copilot_april.csv
  └── claude_march.csv

saas_template.csv       ← FOCUS/CUR schema template (shared)

focus_cur_outputs/      ← Generated output folder (created after run)
  ├── copilot_march_focus_cur.csv
  ├── copilot_april_focus_cur.csv
  └── claude_march_focus_cur.csv
```

Single-file usage (legacy-compatible):

```
usage_report.csv        ← Your SaaS vendor export (input)
saas_template.csv       ← FOCUS/CUR schema template (shared)
focus_cur_output.csv    ← Generated output (created after run)
```

---

## Prerequisites

- **Python 3.10 or higher** — no third-party packages required (stdlib only)
- **git** — to clone the repository

```bash
python3 --version   # must be 3.10 or higher
```

---

## Setup

### Option A — Virtual environment (recommended)

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd saas_to_focus_formatter

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate          # Mac / Linux
# venv\Scripts\activate           # Windows

# 3. Install dependencies  (nothing is downloaded — project uses stdlib only)
pip install -r requirements.txt

# 4. Verify
python3 main.py --help
```

### Option B — Make (Mac/Linux shortcut)

```bash
git clone <repo-url>
cd saas_to_focus_formatter
make setup            # creates venv and installs dependencies
source venv/bin/activate
python3 main.py --help
```

### Option C — System Python (no venv)

```bash
git clone <repo-url>
cd saas_to_focus_formatter
python3 main.py --help   # works directly — no pip install needed
```

> This project has **zero third-party dependencies**, so Option C is safe and will
> never conflict with your system Python environment.

---

## Running the Tests

```bash
# From inside saas_to_focus_formatter/

# Run all tests
python3 -m unittest discover -s tests -v

# Run a single test file
python3 -m unittest tests.test_field_transformations -v
python3 -m unittest tests.test_transformer -v
python3 -m unittest tests.test_generate_mapper -v
python3 -m unittest tests.test_main -v

# Run a single test class
python3 -m unittest tests.test_transformer.TestThreeTierResolution -v

# Run a single test method
python3 -m unittest tests.test_transformer.TestThreeTierResolution.test_tier1_cli_wins_over_defaults -v

# Or run all with Make
make test
```

Expected output: **168 tests, OK**.

| Test file | Tests | What it covers |
|-----------|------:|----------------|
| `tests/test_field_transformations.py` | 63 | All 13 transform functions, date parsing, edge cases |
| `tests/test_transformer.py` | 38 | Three-tier resolution, row transformation, validation, tag injection |
| `tests/test_generate_mapper.py` | 50 | Semantic scoring, tool detection, mapper structure |
| `tests/test_main.py` | 17 | Batch helper functions (`_get_input_files`, `_resolve_output_path`) |

---

## Config File

All paths, billing values, and logging settings can be stored in **`config.ini`** so you only need to type the sub-command — no flags required:

```bash
# After editing config.ini, just run:
python3 main.py run
python3 main.py generate
python3 main.py transform
make run-config
```

Edit `config.ini` (inside `saas_to_focus_formatter/`) to set your project's defaults:

```ini
[paths]
# Batch mode: set both to run all sub-commands without flags
usage_dir     = ../usage_reports/       # input folder  (run / transform)
usage_report  = ../usage_report.csv     # single file   (generate / run / transform)
output_dir    = ../focus_cur_outputs/   # output folder (batch mode)
# output      = ../focus_cur_output.csv # output file   (single-file mode)
cur_template  = ../saas_template.csv

[billing]
provider_name        = GitHub
billing_account_id   = org-CoreStack-Engg
billing_account_name = CoreStack Engineering
billing_currency     = USD              # default: USD
region_name          = global           # default: global

[mapper]
tool_name      = copilot                # optional hint for `generate`
product_family = Developer Tools        # optional hint for `generate`
# mapper       = mappers/copilot_mapper.json  # required for `transform`

[logging]
log_dir     = logs                      # where latest.log and run_state.json are written
max_retries = 1                         # retry each failed file N times (1 = no retry)
```

**Priority order (high → low):**  `CLI argument` > `config.ini` > built-in default

> Use `--config /path/to/other.ini` to point at a different config file for the current run.

---

## Logging & Auditing

Every `run` and `transform` execution writes two files to `logs/` (created automatically):

| File | Behaviour | Purpose |
|------|-----------|---------|
| `logs/latest.log` | Overwritten each run | Full structured log — always shows the current run |
| `logs/run_state.json` | Updated after every file (atomic write) | Checkpoint for `--resume` |

**Sample log output:**
```
2026-03-05 14:30:22  INFO   ========================================================================
2026-03-05 14:30:22  INFO   RUN START   run_id=20260305_143022    command=run
2026-03-05 14:30:22  INFO   Config      : /path/to/config.ini
2026-03-05 14:30:22  INFO   Input files : 3
2026-03-05 14:30:22  INFO     [1/3] ../usage_reports/claude_march.csv
2026-03-05 14:30:22  INFO     [2/3] ../usage_reports/copilot_april.csv
2026-03-05 14:30:22  INFO     [3/3] ../usage_reports/copilot_march.csv
2026-03-05 14:30:22  INFO   ------------------------------------------------------------------------
2026-03-05 14:30:22  INFO   [1/3] START   ../usage_reports/claude_march.csv
2026-03-05 14:30:22  INFO   [1/3]   output : ../focus_cur_outputs/claude_march_focus_cur.csv
2026-03-05 14:30:22  INFO   [1/3]   mapper : mappers/claude_mapper.json
2026-03-05 14:30:22  INFO   [1/3] DONE    rows=45      elapsed=0.12s
...
2026-03-05 14:30:23  ERROR  [3/3] FAIL    elapsed=0.08s  error=KeyError: 'net_amount'
2026-03-05 14:30:23  INFO   ------------------------------------------------------------------------
2026-03-05 14:30:23  INFO   RUN COMPLETE WITH ERRORS  done=2  failed=1  skipped=0  rows=255  elapsed=1.03s
```

**Run state JSON** (`logs/run_state.json`) tracks each file's outcome:
```json
{
  "run_id": "20260305_143022",
  "command": "run",
  "files": {
    "../usage_reports/claude_march.csv":   { "status": "done",   "rows": 45  },
    "../usage_reports/copilot_april.csv":  { "status": "done",   "rows": 210 },
    "../usage_reports/copilot_march.csv":  { "status": "failed", "error": "KeyError: 'net_amount'" }
  }
}
```

### Failure handling flags

| Flag | Config key | Default | Description |
|------|-----------|---------|-------------|
| `--max_retries N` | `logging.max_retries` | `1` | Retry each failed file up to N times within the same run |
| `--resume` | — | off | Re-run only files not yet `done` in `logs/run_state.json`; skip already-successful files |
| `--log_dir DIR` | `logging.log_dir` | `logs/` | Override the directory for `latest.log` and `run_state.json` |

```bash
# Retry each failed file up to 3 times
python3 main.py run --max_retries 3

# Fix the broken CSV, then resume — skips already-done files
python3 main.py run --resume

# Write logs to a custom directory
python3 main.py run --log_dir /var/log/focus_converter/
```

**Exit codes:** `0` = all files succeeded · `2` = partial failure (some files failed) · `1` = bad arguments

---

## AWS S3 Upload (Optional)

In addition to writing output locally, the framework can upload each output CSV to an S3 bucket immediately after writing it. Both destinations are active simultaneously — the local file is always kept.

---

### Step 1 — Install boto3

```bash
pip install boto3
```

The core pipeline has zero third-party dependencies. boto3 is only needed when `s3.bucket` is configured.

---

### Step 2 — Configure AWS credentials

Credentials are **never stored in `config.ini`**. Choose one method:

#### Method A — Environment variables (CI/CD, Docker, cron jobs)

```bash
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=abc123...
export AWS_DEFAULT_REGION=us-east-1   # optional if region is set in config.ini
```

#### Method B — AWS CLI / shared credentials file (local dev)

```bash
# Run once — interactive setup, writes to ~/.aws/credentials
aws configure
```

Or edit `~/.aws/credentials` directly:

```ini
[default]
aws_access_key_id     = AKIA...
aws_secret_access_key = abc123...

[finops-prod]
aws_access_key_id     = AKIA...
aws_secret_access_key = xyz789...
```

To use a named profile, set `profile` in `config.ini [s3]` (see Step 3).

#### Method C — IAM Instance Role / ECS Task Role / AWS SSO

No credentials needed. If running on EC2, ECS, or Lambda, boto3 automatically picks up the attached IAM role. Just configure the bucket settings in Step 3.

---

### Step 3 — Set S3 connection details in `config.ini`

Edit the `[s3]` section (all values commented out by default):

```ini
[s3]
bucket  = my-finops-bucket        # your S3 bucket name  ← required to enable S3
prefix  = focus-cur-outputs/      # folder path within the bucket  (optional)
region  = us-east-1               # AWS region where the bucket lives  (optional)
profile = default                 # named profile from ~/.aws/credentials  (optional)
```

| Key | Required? | What to put here |
|-----|-----------|-----------------|
| `bucket` | **Yes** — enables S3 | The S3 bucket name (e.g. `my-finops-bucket`) |
| `prefix` | No | Folder path inside the bucket. Leave blank for bucket root. |
| `region` | No | AWS region. If blank, uses `AWS_DEFAULT_REGION` env var or profile default. |
| `profile` | No | Named profile from `~/.aws/credentials`. If blank, uses `[default]`. |

---

### Step 4 — Run (S3 upload is automatic)

```bash
cd saas_to_focus_formatter
python3 main.py run
```

Or pass S3 settings directly as CLI flags (overrides config.ini):

```bash
python3 main.py run \
    --s3_bucket  my-finops-bucket \
    --s3_prefix  focus-cur-outputs/ \
    --s3_region  us-east-1

# Use a specific credentials profile
python3 main.py run \
    --s3_bucket  my-finops-bucket \
    --s3_profile finops-prod
```

---

### S3 flags reference (available on `transform` and `run`)

| Flag | Config key | Description |
|------|-----------|-------------|
| `--s3_bucket BUCKET` | `s3.bucket` | S3 bucket name. Setting this enables S3 upload. |
| `--s3_prefix PREFIX` | `s3.prefix` | Key prefix (folder path) within the bucket, e.g. `focus-cur-outputs/` |
| `--s3_region REGION` | `s3.region` | AWS region of the bucket. Uses the SDK default if omitted. |
| `--s3_profile PROFILE` | `s3.profile` | AWS named profile from `~/.aws/credentials`. Uses the default credential chain if omitted. |

### S3 key naming

Uploaded key = `<prefix>/<output_filename>`

| Local output | S3 key (with `prefix = focus-cur-outputs/`) |
|---|---|
| `focus_cur_outputs/copilot_january_2026_focus_cur.csv` | `focus-cur-outputs/copilot_january_2026_focus_cur.csv` |
| `focus_cur_output.csv` | `focus-cur-outputs/focus_cur_output.csv` |

### Expected console output

```
✓ Pipeline complete.
  Output : ../focus_cur_outputs/copilot_january_2026_focus_cur.csv  (31 rows)
  S3     : s3://my-finops-bucket/focus-cur-outputs/
  Log    : logs/latest.log
  State  : logs/run_state.json
```

> **S3 upload failures are non-fatal.** If an upload fails the local file is kept and a warning is logged. The file is not marked as failed in `run_state.json`.

---

## Input Modes

The framework supports two input modes for `transform` and `run`:

| Mode | Flag / config key | Description |
|------|-------------------|-------------|
| Single file | `--usage_report FILE` / `paths.usage_report` | Process one CSV, write one output file |
| Batch folder | `--usage_dir DIR` / `paths.usage_dir` | Process all `*.csv` files in a folder, write one output per file |

In batch mode each output file is named `<input_stem>_focus_cur.csv` inside `--output_dir`.

---

## How to Run

The framework has **three sub-commands**. Use them individually or together.

---

### Command 1 — `generate` (Create mapper from CSV)

Inspects your SaaS CSV and auto-generates a `mapper.json` that describes how to convert it. Run this first for any new vendor. Always operates on a single file.

```bash
python3 main.py generate \
    --usage_report  ../usage_report.csv \
    --output_mapper mappers/copilot_mapper.json \
    --tool_name     copilot \
    --provider_name "GitHub" \
    --product_family "Developer Tools" \
    --billing_currency USD
```

| Flag | Required | Example | Description |
|------|:--------:|---------|-------------|
| `--usage_report` | ✅† | `../usage_report.csv` | Path to your SaaS export CSV |
| `--output_mapper` | optional | `mappers/copilot_mapper.json` | Where to save the generated mapper (default: `mappers/<tool>_mapper.json`) |
| `--tool_name` | optional | `copilot` | Vendor keyword (auto-detected if omitted) |
| `--provider_name` | optional | `"GitHub"` | Written into mapper defaults |
| `--product_family` | optional | `"Developer Tools"` | Auto-inferred if omitted |
| `--billing_currency` | optional | `USD` | Defaults to `USD` |

† Can be supplied via `paths.usage_report` in `config.ini` instead.

**Output:** `mappers/copilot_mapper.json`
Open and review this file before running the next step.

---

### Command 2 — `transform` (Convert CSV using mapper)

Uses an existing `mapper.json` to convert one or more usage CSVs into FOCUS-compliant CUR files.

#### Single file

```bash
python3 main.py transform \
    --usage_report         ../usage_report.csv \
    --mapper               mappers/copilot_mapper.json \
    --cur_template         ../saas_template.csv \
    --output               ../focus_cur_output.csv \
    --provider_name        "GitHub" \
    --billing_account_id   "org-CoreStack-Engg" \
    --billing_account_name "CoreStack Engineering" \
    --billing_currency     USD \
    --region_name          "east-us"
```

#### Batch folder

```bash
python3 main.py transform \
    --usage_dir            ../usage_reports/ \
    --output_dir           ../focus_cur_outputs/ \
    --mapper               mappers/copilot_mapper.json \
    --cur_template         ../saas_template.csv \
    --provider_name        "GitHub" \
    --billing_account_id   "org-CoreStack-Engg" \
    --billing_account_name "CoreStack Engineering" \
    --billing_currency     USD
```

| Flag | Required | Example | Description |
|------|:--------:|---------|-------------|
| `--usage_report` | ✅†* | `../usage_report.csv` | Single SaaS export CSV (*mutually exclusive with `--usage_dir`) |
| `--usage_dir` | ✅†* | `../usage_reports/` | Folder of CSVs for batch mode (*mutually exclusive with `--usage_report`) |
| `--mapper` | ✅† | `mappers/copilot_mapper.json` | Mapper file to use |
| `--cur_template` | optional | `../saas_template.csv` | FOCUS schema template (default from `config.ini` or built-in) |
| `--output` | optional | `../focus_cur_output.csv` | Output path (single-file mode) |
| `--output_dir` | optional | `../focus_cur_outputs/` | Output folder (batch mode) |
| `--provider_name` | optional | `"GitHub"` | Overrides mapper defaults |
| `--billing_account_id` | optional | `"org-CoreStack-Engg"` | Billing account ID |
| `--billing_account_name` | optional | `"CoreStack Engineering"` | Billing account name |
| `--billing_currency` | optional | `USD` | ISO 4217 currency code |
| `--region_name` | optional | `"Global"` | Geographic region |
| `--tag_key` / `--tag_value` | optional | `env` / `prod` | Injects an extra tag on every row |
| `--skip_validation` | optional flag | *(no value)* | Skips required-field pre-check |
| `--max_retries N` | optional | `3` | Retry each failed file up to N times |
| `--resume` | optional flag | *(no value)* | Skip files already done in last run |
| `--log_dir DIR` | optional | `logs/` | Directory for `latest.log` + `run_state.json` |
| `--s3_bucket BUCKET` | optional | `my-finops-bucket` | Upload each output to this S3 bucket (requires `pip install boto3`) |
| `--s3_prefix PREFIX` | optional | `focus-cur-outputs/` | S3 key prefix (folder path) |
| `--s3_region REGION` | optional | `us-east-1` | AWS region for the bucket |
| `--s3_profile PROFILE` | optional | `default` | AWS named profile |

† Can be supplied via `config.ini` (`paths.*` / `mapper.mapper`) instead of the CLI.

**Output:** One FOCUS-compliant CUR file per input CSV.

---

### Command 3 — `run` (Full pipeline in one command)

Runs **generate + transform** in a single command. If a mapper already exists it reuses it; otherwise auto-generates one first.

In batch mode, the correct mapper is **auto-detected per file** from the file's column names, so mixed-vendor folders work automatically.

#### Single file

```bash
python3 main.py run \
    --usage_report         ../usage_report.csv \
    --cur_template         ../saas_template.csv \
    --output               ../focus_cur_output.csv \
    --provider_name        "GitHub" \
    --billing_account_id   "org-CoreStack-Engg" \
    --billing_account_name "CoreStack Engineering" \
    --billing_currency     USD \
    --region_name          "east-us"
```

#### Batch folder (mixed vendors supported)

```bash
python3 main.py run \
    --usage_dir            ../usage_reports/ \
    --output_dir           ../focus_cur_outputs/ \
    --cur_template         ../saas_template.csv \
    --provider_name        "GitHub" \
    --billing_account_id   "org-CoreStack-Engg" \
    --billing_account_name "CoreStack Engineering" \
    --billing_currency     USD
```

**Additional flags for `run`:**

| Flag | Description |
|------|-------------|
| `--mapper mappers/copilot_mapper.json` | Use a specific existing mapper (skips detection/generation) |
| `--regenerate_mapper` | Force re-generation even if mapper.json already exists |
| `--tool_name copilot` | Override tool detection during generation |
| `--max_retries N` | Retry each failed file up to N times |
| `--resume` | Skip files already completed in the last run |
| `--log_dir DIR` | Directory for `latest.log` + `run_state.json` (default: `logs/`) |

---

## Full Step-by-Step Workflow (New Vendor)

```bash
# Step 0 — Enter the project folder
cd saas_to_focus_formatter

# Step 1 — Generate mapper (inspect CSV → mapper.json)
python3 main.py generate \
    --usage_report  ../usage_report.csv \
    --output_mapper mappers/copilot_mapper.json \
    --provider_name "GitHub"

# Step 2 — (Optional) Review the generated mapper
cat mappers/copilot_mapper.json

# Step 3 — Convert to FOCUS CUR
python3 main.py transform \
    --usage_report         ../usage_report.csv \
    --mapper               mappers/copilot_mapper.json \
    --cur_template         ../saas_template.csv \
    --output               ../focus_cur_output.csv \
    --provider_name        "GitHub" \
    --billing_account_id   "org-CoreStack-Engg" \
    --billing_account_name "CoreStack Engineering"
```

---

## Batch Workflow (Multiple Files / Mixed Vendors)

```bash
# Step 0 — Enter the project folder
cd saas_to_focus_formatter

# Step 1 — Place all CSVs in one folder
ls ../usage_reports/
# copilot_march.csv  copilot_april.csv  claude_march.csv

# Step 2 — Run full pipeline (mappers auto-detected and generated as needed)
python3 main.py run \
    --usage_dir            ../usage_reports/ \
    --output_dir           ../focus_cur_outputs/ \
    --cur_template         ../saas_template.csv \
    --billing_account_id   "org-CoreStack-Engg" \
    --billing_account_name "CoreStack Engineering"

# Output:
# focus_cur_outputs/copilot_march_focus_cur.csv
# focus_cur_outputs/copilot_april_focus_cur.csv
# focus_cur_outputs/claude_march_focus_cur.csv
```

---

## Expected Console Output

```
# After generate
INFO  Config loaded: config.ini
INFO  Inspecting usage report: ../usage_report.csv
INFO  Found 14 columns: ['date', 'product', 'sku', ...]
INFO  BillingPeriodStart  ← date          (transform=to_iso8601_start)
INFO  BilledCost          ← net_amount    (transform=identity)
...
✓ Mapper generated: mappers/copilot_mapper.json
  Log: logs/latest.log

# After run (single file) — success
INFO  Config loaded: config.ini
INFO  [1/1] START   ../usage_report.csv
INFO  [1/1]   output : ../focus_cur_output.csv
INFO  [1/1]   mapper : mappers/copilot_mapper.json
INFO  [1/1] DONE    rows=169    elapsed=0.21s

✓ Pipeline complete.
  Output : ../focus_cur_output.csv  (169 rows)
  Log    : logs/latest.log
  State  : logs/run_state.json

# After run (batch folder, 1 failure)
INFO  Config loaded: config.ini
INFO  [1/3] START   ../usage_reports/claude_march.csv
INFO  [1/3] DONE    rows=45     elapsed=0.12s
INFO  [2/3] START   ../usage_reports/copilot_april.csv
INFO  [2/3] DONE    rows=210    elapsed=0.18s
INFO  [3/3] START   ../usage_reports/copilot_march.csv
ERROR [3/3] FAIL    elapsed=0.05s  error=KeyError: 'net_amount'

⚠ Batch complete: 2 done, 1 failed, 0 skipped — 255 total rows
  Output dir  : ../focus_cur_outputs/
  Failed files:
    - ../usage_reports/copilot_march.csv
  Log   : logs/latest.log
  State : logs/run_state.json

# Resume after fixing the failed file
$ python3 main.py run --resume
INFO  Resume: skipping 2 already-done file(s); 1 remaining.
INFO  [1/1] START   ../usage_reports/copilot_march.csv
INFO  [1/1] DONE    rows=169    elapsed=0.20s

✓ Batch complete: 1 done, 0 failed, 2 skipped — 169 total rows
```

---

## FOCUS Output Columns

The output CSV contains **23 FOCUS 1.0 columns** in the order defined by `saas_template.csv`:

| # | Column | Required | Type |
|---|--------|:--------:|------|
| 1 | `ProviderName` | ✅ | string |
| 2 | `BillingAccountId` | ✅ | string |
| 3 | `BillingAccountName` | ✅ | string |
| 4 | `BillingCurrency` | ✅ | string |
| 5 | `BillingPeriodEnd` | ✅ | datetime |
| 6 | `BillingPeriodStart` | ✅ | datetime |
| 7 | `BilledCost` | ✅ | decimal |
| 8 | `EffectiveCost` | ✅ | decimal |
| 9 | `ListCost` | ✅ | decimal |
| 10 | `ChargeCategory` | ✅ | string |
| 11 | `ChargeFrequency` | ✅ | string |
| 12 | `ChargePeriodEnd` | ✅ | datetime |
| 13 | `ChargePeriodStart` | ✅ | datetime |
| 14 | `ServiceName` | ✅ | string |
| 15 | `ConsumedQuantity` | optional | decimal |
| 16 | `ConsumedUnit` | optional | string |
| 17 | `RegionName` | optional | string |
| 18 | `ResourceId` | optional | string |
| 19 | `ResourceName` | optional | string |
| 20 | `SkuId` | optional | string |
| 21 | `Tags` | optional | JSON map |
| 22 | `UsageType` | optional | string |
| 23 | `ProductFamily` | optional | string |

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `FileNotFoundError: Mapper file not found` | Running `transform` before `generate` | Run `generate` first, or use `run` |
| `No .csv files found in directory` | `--usage_dir` points to empty or wrong folder | Check the folder path and contents |
| `Required FOCUS columns are empty: BillingAccountId` | Missing billing flag | Add `--billing_account_id "your-id"` or set in `config.ini` |
| `No mapper specified` | Running `transform` without a mapper | Add `--mapper mappers/<tool>_mapper.json` or set `mapper.mapper` in `config.ini` |
| `Unknown transform: 'my_typo'` | Typo in `mapper.json` | Check spelling against the transform catalogue below |
| `Could not parse date string: '...'` | Unrecognised date format in source CSV | Add the format to `_DATE_FORMATS` in `field_transformations.py` |
| `ModuleNotFoundError` | Running from wrong directory | `cd saas_to_focus_formatter` first |
| Exit code `2` | One or more files failed | Check `logs/latest.log` for errors; fix then re-run with `--resume` |
| `ImportError: boto3 is required for S3 upload` | `pip install boto3` not done | Run `pip install boto3` then retry |
| `NoCredentialsError` or `ClientError` on S3 upload | AWS credentials not configured | Set `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` env vars, or run `aws configure` |

---

## Available Transform Functions

Reference these names in the `"transform"` field of any `mapper.json`:

| Name | What it does | Example |
|------|-------------|---------|
| `identity` | Pass value through unchanged | `"0.612"` → `"0.612"` |
| `to_iso8601_start` | Date → `YYYY-MM-DDT00:00:00Z` | `"2026-03-01"` → `"2026-03-01T00:00:00Z"` |
| `to_iso8601_end` | Date → `YYYY-MM-DDT23:59:59Z` | `"2026-03-01"` → `"2026-03-01T23:59:59Z"` |
| `to_billing_period_end` | Date → first instant of next month | `"2026-03-01"` → `"2026-04-01T00:00:00Z"` |
| `humanize` | snake_case / kebab-case → Title Case | `"copilot_for_business"` → `"Copilot For Business"` |
| `title_case` | Title-case only | `"developer tools"` → `"Developer Tools"` |
| `to_uppercase` | Full uppercase | `"usd"` → `"USD"` |
| `to_lowercase` | Full lowercase | `"USD"` → `"usd"` |
| `strip_whitespace` | Trim leading/trailing spaces | `"  foo  "` → `"foo"` |
| `to_decimal` | Normalise numeric string | `"$1,234.56"` → `"1234.56"` |
| `build_tags` | Multiple columns → compact JSON map | `{"username":"alice","org":"CoreStack"}` |
| `static` | Emit a fixed string | `"Developer Tools"` |
| `first_non_empty` | Try multiple columns, return first hit | tries `col_a`, `col_b`, `col_c` in order |

---

## Adding a New SaaS Vendor

No code changes required — only a new mapper file:

```bash
# 1. Generate mapper for the new vendor
python3 main.py generate \
    --usage_report  ../new_vendor_export.csv \
    --output_mapper mappers/new_vendor_mapper.json \
    --provider_name "New Vendor Inc."

# 2. Review and edit mappers/new_vendor_mapper.json if needed

# 3. Convert
python3 main.py transform \
    --usage_report         ../new_vendor_export.csv \
    --mapper               mappers/new_vendor_mapper.json \
    --cur_template         ../saas_template.csv \
    --output               ../new_vendor_focus_cur.csv \
    --provider_name        "New Vendor Inc." \
    --billing_account_id   "acct-12345" \
    --billing_account_name "My Organisation"
```

---

## Reference

- [SKILL_saas_to_cur_converter.md](../SKILL_saas_to_cur_converter.md) — Full developer playbook (23 sections)
- [PRD_saas_to_focus_formatter.md](../PRD_saas_to_focus_formatter.md) — Product Requirements Document
- [TECH_SPEC_saas_to_focus_formatter.md](../TECH_SPEC_saas_to_focus_formatter.md) — Technical Specification
- [FinOps Foundation FOCUS Specification](https://focus.finops.org)
