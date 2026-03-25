# Product Requirements Document
## SaaS Usage → FOCUS/CUR Converter (`saas_to_focus_formatter`)

**Version:** 1.2
**Date:** 2026-03-05
**Status:** Approved
**Owner:** CoreStack Engineering — FinOps Platform Team

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Goals & Success Metrics](#3-goals--success-metrics)
4. [Target Users](#4-target-users)
5. [Use Cases](#5-use-cases)
6. [Functional Requirements](#6-functional-requirements)
7. [Non-Functional Requirements](#7-non-functional-requirements)
8. [Out of Scope](#8-out-of-scope)
9. [Assumptions & Constraints](#9-assumptions--constraints)
10. [Risks](#10-risks)

---

## 1. Executive Summary

CoreStack's FinOps platform ingests cloud cost data in the AWS **FOCUS / CUR (Cloud Usage and Resource)** format. SaaS vendors — GitHub, Anthropic, Datadog, Slack, Snowflake, and others — export usage billing in their own proprietary CSV schemas. This creates a gap: SaaS spend is invisible to FinOps dashboards that speak only FOCUS.

`saas_to_focus_formatter` closes this gap. It is a lightweight, zero-dependency Python framework that converts **any SaaS vendor's usage export** into a FOCUS 1.0-compliant CUR CSV, without requiring code changes for each new vendor. All vendor-specific logic lives in a declarative `mapper.json` file that can be auto-generated and then tuned.

---

## 2. Problem Statement

### The gap

| Dimension | Cloud providers (AWS, Azure, GCP) | SaaS vendors (GitHub, Datadog, etc.) |
|-----------|-----------------------------------|--------------------------------------|
| Billing format | FOCUS / CUR standard | Proprietary CSV per vendor |
| FinOps tool compatibility | ✅ Native | ❌ Not supported |
| Cost visibility in CoreStack | ✅ Full | ❌ None or manual |

### Pain points

1. **Manual effort** — Engineers manually reformat SaaS CSVs using Excel or one-off scripts. This is error-prone and does not scale.
2. **Vendor proliferation** — Each new SaaS tool requires a new ad-hoc converter; there is no shared framework.
3. **No audit trail** — Manual transformations are undocumented; field mapping decisions are implicit.
4. **Broken FinOps visibility** — SaaS spend (often 20–40% of total tech spend) is absent from cost dashboards, budgets, and allocation reports.

---

## 3. Goals & Success Metrics

### Goals

| # | Goal |
|---|------|
| G1 | Produce FOCUS 1.0-compliant CUR CSV from any SaaS vendor usage export |
| G2 | Onboard a new SaaS vendor with zero Python code changes |
| G3 | Auto-generate a vendor mapper from just the usage CSV |
| G4 | All 14 required FOCUS columns are validated before output is written |
| G5 | Framework is usable standalone (CLI) and via Claude Code (slash command) |
| G6 | Support batch processing: an entire folder of CSVs in one command, one output file per input |
| G7 | Deliver output files to AWS S3 in addition to (or instead of) local disk, with zero code changes |

### Success metrics

| Metric | Target |
|--------|--------|
| Time to onboard a new vendor (after CSV is available) | ≤ 15 minutes |
| Required FOCUS columns populated | 100% (validated before output) |
| Output row count == input row count | 100% (1-to-1 row fidelity) |
| Unit test coverage — transform functions | 100% of named transforms |
| Batch: output file count == input file count | 100% (one output per input CSV) |
| Zero third-party runtime dependencies (core) | ✅ stdlib only; boto3 optional for S3 |

---

## 4. Target Users

| Persona | Role | How they use the tool |
|---------|------|----------------------|
| **FinOps Engineer** | CoreStack internal | Runs the CLI monthly to load SaaS spend into cost platform |
| **Platform Engineer** | CoreStack internal | Adds new vendor mappers; extends transform functions |
| **Data Engineer** | CoreStack / customer | Integrates the tool into a pipeline (cron, Airflow, etc.) |
| **Claude Code user** | Developer | Uses `/generate-mapper` to create mapper files without running CLI |

---

## 5. Use Cases

### UC-1 — Monthly SaaS billing ingestion (primary)

**Actor:** FinOps Engineer
**Trigger:** Monthly SaaS billing export available
**Steps:**
1. Download usage export CSV from SaaS vendor portal (e.g. GitHub Copilot)
2. Place CSV at `usage_report.csv` in the workspace
3. Run `python3 main.py transform` (or `/generate-mapper` in Claude Code)
4. Upload resulting `focus_cur_output.csv` to CoreStack cost platform

**Outcome:** SaaS spend appears in FinOps dashboards with correct cost allocation, tags, and billing period.

---

### UC-2 — First-time vendor onboarding

**Actor:** Platform Engineer
**Trigger:** New SaaS vendor added to the organisation
**Steps:**
1. Export a sample usage CSV from the new vendor
2. Run `python3 main.py generate` to auto-generate `mappers/<vendor>_mapper.json`
3. Review the mapper and correct any mismatched columns
4. Run `python3 main.py transform` to produce and validate the output
5. Commit the mapper file to the repo

**Outcome:** New vendor is onboarded in < 15 minutes with a reusable mapper.

---

### UC-3 — Claude Code mapper generation

**Actor:** Developer using Claude Code
**Trigger:** User types `/generate-mapper` in Claude Code
**Steps:**
1. Claude reads `usage_report.csv` from the workspace root
2. Claude applies semantic scoring rules to map source columns → FOCUS columns
3. Claude writes `mappers/<tool_name>_mapper.json`
4. Claude asks: "Run transform now?"
5. User confirms → Claude executes `python3 main.py transform`

**Outcome:** Mapper generated and output produced without touching the CLI.

---

### UC-4 — Batch multi-vendor processing

**Actor:** Data Engineer
**Trigger:** Monthly pipeline run
**Steps:**
1. Place all vendor CSV exports in a single `usage_reports/` folder
2. Run `python3 main.py run --usage_dir ../usage_reports/ --output_dir ../focus_cur_outputs/`
3. The engine detects each file's vendor, reuses or auto-generates the correct mapper, and writes one output per file
4. Upload all `*_focus_cur.csv` outputs from the output folder to the cost platform

**Outcome:** All SaaS vendors processed in a single command; output files are individually named `<input_stem>_focus_cur.csv`.

---

### UC-5 — Automated delivery to AWS S3

**Actor:** Data Engineer / FinOps Engineer
**Trigger:** Monthly pipeline run where the cost platform ingests from S3
**Steps:**
1. Set `[s3] bucket`, `prefix`, and (optionally) `region`/`profile` in `config.ini`
2. Run `python3 main.py run` (no additional flags needed)
3. Each output CSV is written locally and uploaded to `s3://<bucket>/<prefix>/<filename>` immediately after conversion
4. The cost platform ingestion job reads from the S3 path directly

**Outcome:** SaaS FOCUS outputs delivered to S3 automatically as part of the existing CLI run; no separate upload step required.

---

## 6. Functional Requirements

### FR-1 — Mapper Generator

| ID | Requirement |
|----|-------------|
| FR-1.1 | `generate` command inspects a SaaS CSV and auto-generates a `mapper.json` |
| FR-1.2 | Generator uses semantic pattern scoring to match source columns to FOCUS columns |
| FR-1.3 | Generator detects contextual columns (username, org, team, etc.) for `Tags` |
| FR-1.4 | Generator infers `tool_name` from the CSV's product column value or filename |
| FR-1.5 | Generator infers `ProductFamily` from `tool_name` via a keyword lookup table |
| FR-1.6 | Generator writes a structured JSON with `meta`, `defaults`, and `mappings` sections |
| FR-1.7 | `--tool_name`, `--provider_name`, `--product_family`, `--billing_currency` flags allow manual overrides |

### FR-2 — Transformation Engine

| ID | Requirement |
|----|-------------|
| FR-2.1 | `transform` command converts a SaaS CSV to a FOCUS-compliant CUR CSV using a mapper |
| FR-2.2 | Output column order follows `saas_template.csv` row 0 |
| FR-2.3 | Three-tier value resolution: CLI params (Tier 1) > mapper mappings (Tier 2) > mapper defaults (Tier 3) |
| FR-2.4 | All 14 required FOCUS columns are validated against the first data row before writing |
| FR-2.5 | `--skip_validation` flag bypasses required-field check (for debugging) |
| FR-2.6 | `--tag_key` / `--tag_value` injects an extra tag into every output row's `Tags` column |
| FR-2.7 | Output row count must equal input row count (1-to-1 transformation, no merging or splitting) |

### FR-3 — Transform Functions

| ID | Requirement |
|----|-------------|
| FR-3.1 | 13 built-in transform functions: `identity`, `to_iso8601_start`, `to_iso8601_end`, `to_billing_period_end`, `humanize`, `title_case`, `to_uppercase`, `to_lowercase`, `strip_whitespace`, `to_decimal`, `build_tags`, `static`, `first_non_empty` |
| FR-3.2 | All transforms accept `(value, row, config)` and return a string |
| FR-3.3 | New transforms can be added without changing any existing code |
| FR-3.4 | `build_tags` produces compact JSON (`{"key":"val"}`) with no null/empty values |
| FR-3.5 | Date transforms handle 7 input formats and produce ISO-8601 UTC output |
| FR-3.6 | `to_decimal` strips currency symbols, commas, and whitespace; empty input → `"0"` |

### FR-4 — Pipeline (`run` command)

| ID | Requirement |
|----|-------------|
| FR-4.1 | `run` executes generate + transform in one command |
| FR-4.2 | If a mapper already exists, generation is skipped (reuse existing) |
| FR-4.3 | `--regenerate_mapper` flag forces re-generation even if mapper exists |
| FR-4.4 | `--mapper` flag allows specifying an explicit mapper path |

### FR-7 — AWS S3 Output Destination

| ID | Requirement |
|----|-------------|
| FR-7.1 | When `s3.bucket` is configured (via config.ini or `--s3_bucket`), each output CSV is uploaded to S3 after local write |
| FR-7.2 | S3 key = `<prefix>/<output_filename>` where prefix defaults to empty string (bucket root) |
| FR-7.3 | Local output file is always written regardless of S3 configuration |
| FR-7.4 | S3 upload failure is non-fatal: a warning is logged and the file is not marked as failed in `run_state.json` |
| FR-7.5 | Credentials resolved via standard boto3 chain (env vars → `~/.aws/credentials` → IAM role); never stored in config |
| FR-7.6 | `--s3_region` and `--s3_profile` flags allow selecting a specific AWS region and named credentials profile |
| FR-7.7 | S3 upload requires `boto3`; a clear `ImportError` with install instructions is raised if boto3 is missing |
| FR-7.8 | S3 destination is shown in the per-run summary output and in `logs/latest.log` |

### FR-5 — Batch Input Mode

| ID | Requirement |
|----|-------------|
| FR-5.1 | `--usage_dir DIR` flag accepts a folder path; all `*.csv` files in the folder are processed in alphabetical order |
| FR-5.2 | `--usage_dir` and `--usage_report` are mutually exclusive on the same sub-command |
| FR-5.3 | Each input file produces a separate output file named `<input_stem>_focus_cur.csv` in `--output_dir` |
| FR-5.4 | `--output_dir` is created automatically if it does not exist |
| FR-5.5 | In `run` batch mode, mapper is auto-detected per file via tool name inference; a single `--mapper` flag applies the same mapper to all files |
| FR-5.6 | Batch summary line reports total files processed and total rows written |
| FR-5.7 | If `--usage_dir` points to an empty folder or contains no `*.csv` files, raise a clear `ValueError` |

### FR-6 — CLI UX

| ID | Requirement |
|----|-------------|
| FR-6.1 | Must be run from the `saas_to_focus_formatter/` directory |
| FR-6.2 | Input files (`usage_report.csv`, `saas_template.csv`) default to `../` relative paths |
| FR-6.3 | Clear error messages for: missing mapper, empty required column, unknown transform, unparseable date |
| FR-6.4 | Progress logging to stderr (with `[N/M]` prefix in batch mode); final summary to stdout |

---

## 7. Non-Functional Requirements

| ID | Category | Requirement |
|----|----------|-------------|
| NFR-1 | Dependencies | Zero third-party packages for core pipeline; Python 3.10+ stdlib only. `boto3` is an optional dependency required only for S3 upload. |
| NFR-2 | Performance | 10,000-row CSV processes in < 5 seconds on standard hardware |
| NFR-3 | Correctness | Output passes FOCUS 1.0 schema validation (all required columns populated) |
| NFR-4 | Extensibility | New vendor: add one JSON file, zero code changes |
| NFR-5 | Testability | All transform functions are pure (no I/O), unit-testable in isolation |
| NFR-6 | Portability | Runs on macOS, Linux; no OS-specific dependencies |
| NFR-7 | Encoding | Input CSVs may use BOM (`utf-8-sig`); engine handles transparently |

---

## 8. Out of Scope

| Item | Rationale |
|------|-----------|
| Direct API / webhook ingestion from SaaS vendors | Out of v1; CSV export is the universal baseline |
| Database or data warehouse output | v1 targets CSV only; future versions may add Parquet, JSON Lines |
| Multi-file merge into a single output CSV | Each input file produces its own output file; merging is a downstream concern |
| GUI or web interface | CLI and Claude Code are sufficient for current users |
| Automatic upload to CoreStack platform API | Out of scope; S3 delivery covers the upload-to-platform use case via S3 ingestion |
| Real-time / streaming processing | Monthly batch is the target cadence |

---

## 9. Assumptions & Constraints

1. SaaS vendor exports at least one billing period as a CSV
2. The output `saas_template.csv` is the authoritative FOCUS column order and is not modified between runs
3. Billing account metadata (`--billing_account_id`, `--billing_account_name`) is always provided via CLI or mapper defaults
4. One mapper JSON file per SaaS vendor/tool is sufficient (not per-account)
5. The tool is run on a machine with Python 3.10+

---

## 10. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Vendor changes their CSV schema silently | Medium | High | Required-column validation catches empty fields immediately; mapper review step on re-runs |
| Auto-generated mapper misidentifies a column | Medium | Medium | Mapper review step (Section 9.3 of SKILL) before first production run |
| Date format not in `_DATE_FORMATS` list | Low | Medium | Warning logged; empty string emitted; `_DATE_FORMATS` is easily extensible |
| Large CSV (100k+ rows) causes memory issues | Low | Medium | `rows = list(reader)` loads all rows; future: chunk-based streaming |
| Required FOCUS column evolves in FOCUS 1.1+ | Low | High | `REQUIRED_FOCUS_COLUMNS` and `focus_schema.json` are the single source of truth; update them |
