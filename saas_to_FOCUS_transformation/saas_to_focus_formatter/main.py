#!/usr/bin/env python3
"""
main.py  —  SaaS Usage → FOCUS/CUR Converter  (mapper-driven)
==============================================================

Orchestrates a four-step pipeline:

  Step 1  [generate]   Inspect SaaS CSV → auto-generate mapper.json
  Step 2  [transform]  Apply mapper.json to CSV → FOCUS-compliant CUR CSV
  Step 3  [run]        Steps 1 + 2 in one command (full pipeline)

Input modes
-----------
  Single file   --usage_report path/to/file.csv
  Batch folder  --usage_dir    path/to/folder/    (all *.csv files, alphabetical order)

Config file
-----------
  All path and billing values can be stored in config.ini (auto-loaded from
  the same directory as main.py).  CLI args always override config values.

  python3 main.py run          # reads everything from config.ini
  python3 main.py run --usage_report other.csv   # overrides paths.usage_report

Logging & auditing
------------------
  Every run writes:
    logs/latest.log       — full structured log, overwritten each run
    logs/run_state.json   — JSON checkpoint updated per file (for --resume)

  --resume         Skip files that already completed in the last run
  --max_retries N  Retry each failed file up to N times (default: 1)
  --log_dir DIR    Override the log directory (default: logs/)

Output destinations
-------------------
  Local folder  --output_dir DIR   (or output_dir in config.ini [paths])
  AWS S3        --s3_bucket BUCKET  (or bucket in config.ini [s3])

  Both can be active simultaneously: the file is always written locally first,
  then uploaded to S3 if a bucket is configured.  S3 upload uses the standard
  boto3 credential chain (env vars → ~/.aws/credentials → IAM role).

Extending to a new SaaS vendor
-------------------------------
  1. Export the vendor's usage CSV.
  2. Run:  python3 main.py generate --usage_report <vendor>.csv
  3. Inspect the generated mapper.json; edit if needed.
  4. Run:  python3 main.py transform or run
  No engine code changes required.
"""

from __future__ import annotations

import argparse
import configparser
import glob
import logging
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-5s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

# ── Project root on path ──────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from mapper_generator.generate_mapper import (
    generate_mapper,
    read_focus_schema_file,
    read_usage_csv,
    write_mapper,
    _infer_tool_name,
)
from transform_engine.transformer import convert
from audit.run_logger import RunLogger

# ─────────────────────────────────────────────────────────────────────────────
# Default paths (relative to project root)
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_SCHEMA      = os.path.join(_ROOT, "schemas", "focus_schema.json")
DEFAULT_TEMPLATE    = os.path.join(_ROOT, "..", "saas_template.csv")
DEFAULT_MAPPERS_DIR = os.path.join(_ROOT, "mappers")
DEFAULT_CONFIG      = os.path.join(_ROOT, "config.ini")
DEFAULT_LOG_DIR     = os.path.join(_ROOT, "logs")


# ─────────────────────────────────────────────────────────────────────────────
# Config file helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_config(config_path: str) -> configparser.ConfigParser:
    """Load an INI config file. Returns an empty parser if the file does not exist."""
    cfg = configparser.ConfigParser(inline_comment_prefixes=('#',))
    cfg.read(config_path)  # silently returns [] if file is missing
    return cfg


def _apply_config_defaults(args: argparse.Namespace, cfg: configparser.ConfigParser) -> None:
    """
    Fill unset arg values from the config file.
    CLI arguments always take precedence — this only sets values that are
    still None / empty after argparse has run.
    """
    def get(section: str, key: str, fallback: str = "") -> str:
        return cfg.get(section, key, fallback=fallback) if cfg.has_section(section) else fallback

    # ── Input paths ──────────────────────────────────────────────────────────
    # Only consult config when neither --usage_report nor --usage_dir was given.
    if not getattr(args, "usage_report", None) and not getattr(args, "usage_dir", None):
        cfg_usage_dir    = get("paths", "usage_dir")
        cfg_usage_report = get("paths", "usage_report")
        if cfg_usage_dir:
            args.usage_dir = cfg_usage_dir
        if cfg_usage_report and hasattr(args, "usage_report"):
            # Always set usage_report if present so `generate` can use it even
            # when usage_dir is also set (generate only accepts single files).
            args.usage_report = cfg_usage_report

    # ── Output paths ─────────────────────────────────────────────────────────
    if not getattr(args, "output_dir", None):
        cfg_output_dir = get("paths", "output_dir")
        if cfg_output_dir:
            args.output_dir = cfg_output_dir

    if getattr(args, "output", None) is None:
        cfg_output = get("paths", "output")
        args.output = cfg_output if cfg_output else "focus_cur_output.csv"

    if getattr(args, "cur_template", None) is None:
        cfg_template = get("paths", "cur_template")
        args.cur_template = cfg_template if cfg_template else DEFAULT_TEMPLATE

    # ── Mapper paths ─────────────────────────────────────────────────────────
    if not getattr(args, "output_mapper", None):
        cfg_output_mapper = get("mapper", "output_mapper")
        if cfg_output_mapper:
            args.output_mapper = cfg_output_mapper

    if not getattr(args, "mapper", None):
        cfg_mapper = get("mapper", "mapper")
        if cfg_mapper:
            args.mapper = cfg_mapper

    # ── Billing defaults ─────────────────────────────────────────────────────
    def cfg_fill(attr: str, section: str, key: str, fallback: str = "") -> None:
        if not getattr(args, attr, None):
            val = get(section, key, fallback)
            if val:
                setattr(args, attr, val)

    cfg_fill("provider_name",        "billing", "provider_name")
    cfg_fill("billing_account_id",   "billing", "billing_account_id")
    cfg_fill("billing_account_name", "billing", "billing_account_name")
    cfg_fill("billing_currency",     "billing", "billing_currency", "USD")
    cfg_fill("region_name",          "billing", "region_name")

    # ── Mapper metadata hints ─────────────────────────────────────────────────
    cfg_fill("tool_name",      "mapper", "tool_name")
    cfg_fill("product_family", "mapper", "product_family")

    # ── Logging / audit settings ──────────────────────────────────────────────
    if not getattr(args, "log_dir", None):
        cfg_log_dir = get("logging", "log_dir")
        args.log_dir = cfg_log_dir if cfg_log_dir else DEFAULT_LOG_DIR

    if getattr(args, "max_retries", None) is None:
        cfg_retries = get("logging", "max_retries", "1")
        try:
            args.max_retries = int(cfg_retries)
        except ValueError:
            args.max_retries = 1

    # ── S3 upload settings ────────────────────────────────────────────────────
    cfg_fill("s3_bucket",  "s3", "bucket")
    cfg_fill("s3_prefix",  "s3", "prefix")
    cfg_fill("s3_region",  "s3", "region")
    cfg_fill("s3_profile", "s3", "profile")

    # ── Apply final hardcoded defaults for anything still unset ──────────────
    if not getattr(args, "billing_currency", None):
        args.billing_currency = "USD"
    if not getattr(args, "region_name", None):
        args.region_name = "global"
    if not getattr(args, "charge_category", None):
        args.charge_category = "Usage"
    if not getattr(args, "charge_frequency", None):
        args.charge_frequency = "Monthly"
    if getattr(args, "max_retries", None) is None:
        args.max_retries = 1


def _validate_input_source(args: argparse.Namespace) -> None:
    """
    Ensure exactly one input source is present after config defaults are applied.
    Raises ValueError with a helpful message if not.
    """
    has_report = bool(getattr(args, "usage_report", None))
    has_dir    = bool(getattr(args, "usage_dir", None))
    if not has_report and not has_dir:
        raise ValueError(
            "No input source specified.\n"
            "  Provide --usage_report FILE  or  --usage_dir DIR on the command line,\n"
            "  or set  paths.usage_report  /  paths.usage_dir  in config.ini."
        )


# ─────────────────────────────────────────────────────────────────────────────
# S3 upload helper
# ─────────────────────────────────────────────────────────────────────────────

def _upload_to_s3(local_path: str, args: argparse.Namespace) -> Optional[str]:
    """
    Upload a local file to S3 if s3_bucket is configured.

    Returns the s3:// URI on success, or None if S3 is not configured.
    Raises ImportError if boto3 is not installed.
    Raises botocore.exceptions.BotoCoreError / ClientError on upload failure.

    Credentials are resolved via the standard boto3 chain:
      1. Environment variables (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)
      2. ~/.aws/credentials (named profile via --s3_profile / config.ini [s3] profile)
      3. IAM instance role / ECS task role / etc.
    """
    bucket = getattr(args, "s3_bucket", None)
    if not bucket:
        return None

    try:
        import boto3  # noqa: PLC0415 — optional dependency; imported here to keep stdlib-only baseline
    except ImportError:
        raise ImportError(
            "boto3 is required for S3 upload.\n"
            "  Install it with:  pip install boto3\n"
            "  Or add it to your virtual environment and re-run."
        )

    prefix  = (getattr(args, "s3_prefix",  None) or "").rstrip("/")
    region  = getattr(args, "s3_region",  None) or None
    profile = getattr(args, "s3_profile", None) or None

    filename = os.path.basename(local_path)
    s3_key   = f"{prefix}/{filename}" if prefix else filename

    session_kwargs: dict = {}
    if profile:
        session_kwargs["profile_name"] = profile
    session = boto3.Session(**session_kwargs)

    client_kwargs: dict = {}
    if region:
        client_kwargs["region_name"] = region
    s3 = session.client("s3", **client_kwargs)

    s3.upload_file(local_path, bucket, s3_key)

    s3_uri = f"s3://{bucket}/{s3_key}"
    return s3_uri


# ─────────────────────────────────────────────────────────────────────────────
# Batch helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_input_files(args: argparse.Namespace) -> List[str]:
    """Return ordered list of CSV paths from --usage_dir (batch) or --usage_report (single)."""
    usage_dir = getattr(args, "usage_dir", None)
    if usage_dir:
        files = sorted(glob.glob(os.path.join(usage_dir, "*.csv")))
        if not files:
            raise ValueError(f"No .csv files found in directory: {usage_dir}")
        return files
    return [args.usage_report]


def _resolve_output_path(input_path: str, args: argparse.Namespace) -> str:
    """Resolve the output CSV path for a given input file."""
    output_dir = getattr(args, "output_dir", None)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(input_path))[0]
        return os.path.join(output_dir, f"{stem}_focus_cur.csv")
    return args.output


# ─────────────────────────────────────────────────────────────────────────────
# Sub-command handlers
# ─────────────────────────────────────────────────────────────────────────────

def cmd_generate(args: argparse.Namespace, audit: RunLogger) -> None:
    """Generate a mapper.json from a SaaS usage CSV (single file only)."""
    schema_path = args.schema or DEFAULT_SCHEMA
    focus_schema = read_focus_schema_file(schema_path)
    source_columns, sample_rows = read_usage_csv(args.usage_report)

    mapper = generate_mapper(
        source_columns=source_columns,
        sample_rows=sample_rows,
        focus_schema=focus_schema,
        tool_name=args.tool_name or "",
        provider_name=args.provider_name or "",
        product_family=args.product_family or "",
        currency=args.billing_currency or "USD",
        filename=args.usage_report,
    )

    output_mapper = args.output_mapper
    if not output_mapper:
        tool = mapper["meta"]["tool_name"]
        output_mapper = os.path.join(DEFAULT_MAPPERS_DIR, f"{tool}_mapper.json")

    write_mapper(mapper, output_mapper)

    # Audit log for generate
    audit._file_log.info("GENERATE  input=%s  mapper=%s", args.usage_report, output_mapper)

    print(f"\n✓ Mapper generated: {output_mapper}")
    print("  Review and edit if needed, then run: python3 main.py transform")
    print(f"  Log: {audit.log_path}")


def cmd_transform(args: argparse.Namespace, audit: RunLogger) -> int:
    """
    Transform SaaS usage CSV(s) using an existing mapper.json.
    Returns the count of failed files (0 = all succeeded).
    """
    max_retries  = getattr(args, "max_retries", 1)
    resume       = getattr(args, "resume", False)
    input_files  = _get_input_files(args)
    cli_params   = _build_cli_params(args)

    skipped = 0
    if resume:
        input_files, skipped = audit.filter_resumable_files(input_files)
        if not input_files:
            log.info("Resume: all files already done — nothing to process.")
            audit.finish_run(done=0, failed=0, skipped=skipped, total_rows=0)
            return 0

    audit.start_run(
        command="transform",
        input_files=input_files,
        config_path=getattr(args, "_config_path", DEFAULT_CONFIG),
        params=_build_audit_params(args),
    )

    total_rows: int     = 0
    failed_files: List[str] = []

    for i, usage_path in enumerate(input_files, 1):
        output_path = _resolve_output_path(usage_path, args)
        file_start  = time.monotonic()
        last_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            audit.start_file(i, len(input_files), usage_path, output_path, args.mapper, attempt)
            try:
                rows_written = convert(
                    usage_path=usage_path,
                    mapper_path=args.mapper,
                    template_path=args.cur_template,
                    output_path=output_path,
                    cli_params=cli_params,
                    tag_key=args.tag_key or "",
                    tag_value=args.tag_value or "",
                    validate=not args.skip_validation,
                )
                elapsed = time.monotonic() - file_start
                audit.finish_file(i, len(input_files), usage_path, rows_written, elapsed)
                total_rows += rows_written
                last_error  = None

                # ── S3 upload (non-fatal — local file is always kept) ─────────
                try:
                    s3_uri = _upload_to_s3(output_path, args)
                    if s3_uri:
                        audit._file_log.info("[%d/%d]   s3     : %s", i, len(input_files), s3_uri)
                except Exception as s3_exc:
                    log.warning("[%d/%d] S3 upload failed (local file kept): %s", i, len(input_files), s3_exc)

                break  # success — no more retries

            except Exception as exc:
                last_error = exc
                elapsed    = time.monotonic() - file_start
                is_final   = attempt >= max_retries
                audit.fail_file(i, len(input_files), usage_path, exc, elapsed, final=is_final)
                if not is_final:
                    log.warning("[%d/%d] attempt %d failed — retrying: %s", i, len(input_files), attempt, exc)

        if last_error is not None:
            failed_files.append(usage_path)

    done = len(input_files) - len(failed_files)
    audit.finish_run(done=done, failed=len(failed_files), skipped=skipped, total_rows=total_rows)

    _print_summary("transform", input_files, failed_files, skipped, total_rows, args, audit)
    return len(failed_files)


def cmd_run(args: argparse.Namespace, audit: RunLogger) -> int:
    """
    Full pipeline: generate mapper (if missing) then transform.

    Batch mode: mapper is auto-detected/generated per file from column names.
    Returns the count of failed files (0 = all succeeded).
    """
    schema_path  = args.schema or DEFAULT_SCHEMA
    max_retries  = getattr(args, "max_retries", 1)
    resume       = getattr(args, "resume", False)
    input_files  = _get_input_files(args)
    cli_params   = _build_cli_params(args)

    skipped = 0
    if resume:
        input_files, skipped = audit.filter_resumable_files(input_files)
        if not input_files:
            log.info("Resume: all files already done — nothing to process.")
            audit.finish_run(done=0, failed=0, skipped=skipped, total_rows=0)
            return 0

    audit.start_run(
        command="run",
        input_files=input_files,
        config_path=getattr(args, "_config_path", DEFAULT_CONFIG),
        params=_build_audit_params(args),
    )

    total_rows: int     = 0
    failed_files: List[str] = []

    for i, usage_path in enumerate(input_files, 1):
        file_start = time.monotonic()

        # ── Read CSV (needed for tool detection and/or mapper generation) ─────
        source_columns, sample_rows = read_usage_csv(usage_path)

        # ── Resolve mapper path for this file ─────────────────────────────────
        if args.mapper:
            file_mapper_path = args.mapper
        else:
            stem             = os.path.splitext(os.path.basename(usage_path))[0]
            detected_tool    = _infer_tool_name(stem, source_columns, sample_rows)
            file_mapper_path = os.path.join(DEFAULT_MAPPERS_DIR, f"{detected_tool}_mapper.json")

        # ── Generate mapper if missing or forced ──────────────────────────────
        if not os.path.exists(file_mapper_path) or args.regenerate_mapper:
            log.info(
                "[%d/%d] Mapper not found%s — auto-generating: %s",
                i, len(input_files),
                " (--regenerate_mapper)" if args.regenerate_mapper else "",
                file_mapper_path,
            )
            focus_schema = read_focus_schema_file(schema_path)
            mapper = generate_mapper(
                source_columns=source_columns,
                sample_rows=sample_rows,
                focus_schema=focus_schema,
                tool_name=args.tool_name or "",
                provider_name=args.provider_name or "",
                product_family=args.product_family or "",
                currency=args.billing_currency or "USD",
                filename=usage_path,
            )
            write_mapper(mapper, file_mapper_path)
            log.info("[%d/%d] Mapper saved: %s", i, len(input_files), file_mapper_path)
        else:
            log.info("[%d/%d] Using existing mapper: %s", i, len(input_files), file_mapper_path)

        # ── Transform with retry ───────────────────────────────────────────────
        output_path = _resolve_output_path(usage_path, args)
        last_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            audit.start_file(i, len(input_files), usage_path, output_path, file_mapper_path, attempt)
            try:
                rows_written = convert(
                    usage_path=usage_path,
                    mapper_path=file_mapper_path,
                    template_path=args.cur_template,
                    output_path=output_path,
                    cli_params=cli_params,
                    tag_key=args.tag_key or "",
                    tag_value=args.tag_value or "",
                    validate=not args.skip_validation,
                )
                elapsed = time.monotonic() - file_start
                audit.finish_file(i, len(input_files), usage_path, rows_written, elapsed)
                total_rows += rows_written
                last_error  = None

                # ── S3 upload (non-fatal — local file is always kept) ─────────
                try:
                    s3_uri = _upload_to_s3(output_path, args)
                    if s3_uri:
                        audit._file_log.info("[%d/%d]   s3     : %s", i, len(input_files), s3_uri)
                except Exception as s3_exc:
                    log.warning("[%d/%d] S3 upload failed (local file kept): %s", i, len(input_files), s3_exc)

                break  # success

            except Exception as exc:
                last_error = exc
                elapsed    = time.monotonic() - file_start
                is_final   = attempt >= max_retries
                audit.fail_file(i, len(input_files), usage_path, exc, elapsed, final=is_final)
                if not is_final:
                    log.warning("[%d/%d] attempt %d failed — retrying: %s", i, len(input_files), attempt, exc)

        if last_error is not None:
            failed_files.append(usage_path)

    done = len(input_files) - len(failed_files)
    audit.finish_run(done=done, failed=len(failed_files), skipped=skipped, total_rows=total_rows)

    _print_summary("run", input_files, failed_files, skipped, total_rows, args, audit)
    return len(failed_files)


# ─────────────────────────────────────────────────────────────────────────────
# Print helpers
# ─────────────────────────────────────────────────────────────────────────────

def _print_summary(
    command: str,
    input_files: List[str],
    failed_files: List[str],
    skipped: int,
    total_rows: int,
    args: argparse.Namespace,
    audit: RunLogger,
) -> None:
    done = len(input_files) - len(failed_files)
    s3_bucket = getattr(args, "s3_bucket", None)
    s3_prefix = getattr(args, "s3_prefix", "") or ""
    if len(input_files) == 1 and not failed_files:
        label = "Pipeline complete." if command == "run" else "FOCUS CUR output ready."
        print(f"\n✓ {label}")
        print(f"  Output : {_resolve_output_path(input_files[0], args)}  ({total_rows} rows)")
        if s3_bucket:
            print(f"  S3     : s3://{s3_bucket}/{s3_prefix}")
    else:
        status = "✓" if not failed_files else "⚠"
        print(f"\n{status} Batch complete: {done} done, {len(failed_files)} failed, {skipped} skipped — {total_rows} total rows")
        if getattr(args, "output_dir", None):
            print(f"  Output dir : {args.output_dir}")
        if s3_bucket:
            print(f"  S3 dest    : s3://{s3_bucket}/{s3_prefix}")
        if failed_files:
            print("  Failed files:")
            for f in failed_files:
                print(f"    - {f}")
    print(f"  Log   : {audit.log_path}")
    print(f"  State : {audit.state_path}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI parameter builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_cli_params(args: argparse.Namespace) -> Dict[str, str]:
    """
    Build the Tier-1 CLI override dict from parsed args.
    Only non-empty values are included so they don't overwrite
    mapper-level defaults with empty strings.
    """
    params: Dict[str, str] = {}
    _set_if(params, "ProviderName",       args.provider_name)
    _set_if(params, "BillingAccountId",   args.billing_account_id)
    _set_if(params, "BillingAccountName", args.billing_account_name)
    _set_if(params, "BillingCurrency",    args.billing_currency)
    _set_if(params, "RegionName",         getattr(args, "region_name", ""))
    _set_if(params, "ChargeCategory",     getattr(args, "charge_category", ""))
    _set_if(params, "ChargeFrequency",    getattr(args, "charge_frequency", ""))
    return params


def _build_audit_params(args: argparse.Namespace) -> Dict[str, str]:
    """Build a human-readable params dict for audit log headers."""
    params = {
        "provider_name":        getattr(args, "provider_name", ""),
        "billing_account_id":   getattr(args, "billing_account_id", ""),
        "billing_account_name": getattr(args, "billing_account_name", ""),
        "billing_currency":     getattr(args, "billing_currency", ""),
        "region_name":          getattr(args, "region_name", ""),
        "cur_template":         getattr(args, "cur_template", ""),
        "max_retries":          str(getattr(args, "max_retries", 1)),
        "resume":               str(getattr(args, "resume", False)),
    }
    s3_bucket = getattr(args, "s3_bucket", None)
    if s3_bucket:
        prefix = getattr(args, "s3_prefix", "") or ""
        params["s3_destination"] = f"s3://{s3_bucket}/{prefix}"
    return params


def _set_if(d: Dict[str, str], key: str, value: Optional[str]) -> None:
    if value:
        d[key] = value


# ─────────────────────────────────────────────────────────────────────────────
# Argument parser
# ─────────────────────────────────────────────────────────────────────────────

def _add_input_group(p: argparse.ArgumentParser) -> None:
    """Mutually exclusive --usage_report / --usage_dir input group.
    Both are optional here; _validate_input_source() enforces that exactly
    one is set after config defaults are applied."""
    group = p.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "--usage_report",
        metavar="FILE",
        help="Path to a single SaaS usage export CSV.",
    )
    group.add_argument(
        "--usage_dir",
        metavar="DIR",
        help="Folder of SaaS usage CSVs — all *.csv processed in alphabetical order (batch mode).",
    )


def _add_common_args(p: argparse.ArgumentParser) -> None:
    """Shared arguments across sub-commands (excluding the input source group)."""
    p.add_argument("--schema",        default=None,  help=f"Path to focus_schema.json (default: {DEFAULT_SCHEMA}).")
    p.add_argument("--provider_name", default="",    help="SaaS provider name (e.g. GitHub).")
    p.add_argument("--billing_account_id",   default="", help="Provider billing account ID.")
    p.add_argument("--billing_account_name", default="", help="Provider billing account name.")
    p.add_argument("--billing_currency", default=None, help="ISO 4217 currency code (default: USD).")
    p.add_argument("--tool_name",      default="",   help="Tool/vendor name (auto-detected if omitted).")
    p.add_argument("--product_family", default="",   help="ProductFamily label (auto-inferred if omitted).")


def _add_output_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--cur_template", default=None,
                   help=f"Path to saas_template.csv (default: {DEFAULT_TEMPLATE}; overrides config).")
    p.add_argument("--output",       default=None,
                   help="Output FOCUS CUR CSV path — single-file mode (default: focus_cur_output.csv).")
    p.add_argument("--output_dir",   default=None,
                   help="Output folder for batch mode. Each input file produces "
                        "<stem>_focus_cur.csv in this directory.")
    p.add_argument("--region_name",     default="",   help="Geographic region (default: global).")
    p.add_argument("--charge_category", default=None, help="ChargeCategory (default: Usage).")
    p.add_argument("--charge_frequency",default=None, help="ChargeFrequency (default: Monthly).")
    p.add_argument("--tag_key",   default="", help="Extra tag key injected into every row's Tags.")
    p.add_argument("--tag_value", default="", help="Extra tag value paired with --tag_key.")
    p.add_argument(
        "--skip_validation", action="store_true",
        help="Skip required-field validation (use for large files or debugging)."
    )
    # ── S3 output destination (optional) ─────────────────────────────────────
    p.add_argument(
        "--s3_bucket", default=None, metavar="BUCKET",
        help="S3 bucket name. If set, each output file is uploaded after local write. "
             "Also configurable via [s3] bucket in config.ini.",
    )
    p.add_argument(
        "--s3_prefix", default=None, metavar="PREFIX",
        help="S3 key prefix (folder path) within the bucket, e.g. 'focus-cur-outputs/'. "
             "Also configurable via [s3] prefix in config.ini.",
    )
    p.add_argument(
        "--s3_region", default=None, metavar="REGION",
        help="AWS region for the S3 bucket (e.g. us-east-1). "
             "Uses the AWS SDK default if omitted. "
             "Also configurable via [s3] region in config.ini.",
    )
    p.add_argument(
        "--s3_profile", default=None, metavar="PROFILE",
        help="AWS named profile from ~/.aws/credentials. "
             "Uses the default credential chain if omitted. "
             "Also configurable via [s3] profile in config.ini.",
    )


def _add_run_args(p: argparse.ArgumentParser) -> None:
    """Arguments for commands that run (transform / run) — logging, retry, resume."""
    p.add_argument(
        "--log_dir", default=None, metavar="DIR",
        help=f"Directory for log file and run state (default: {DEFAULT_LOG_DIR}).",
    )
    p.add_argument(
        "--max_retries", type=int, default=None, metavar="N",
        help="Max retry attempts per file on failure (default: 1 = no retry).",
    )
    p.add_argument(
        "--resume", action="store_true",
        help="Skip files already completed in the previous run (uses logs/run_state.json).",
    )


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="main.py",
        description="SaaS Usage → FOCUS/CUR Converter (mapper-driven framework)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Config file (config.ini):
  Store paths and billing defaults so you only need to pass the sub-command.
  CLI args always override config values.  Use --config for a custom INI file.

Sub-commands:
  generate   Inspect a SaaS CSV and auto-generate mapper.json
  transform  Convert CSV(s) using an existing mapper.json
  run        Full pipeline: generate mapper (if needed) + convert

Quick start:
  python3 main.py run                          # uses config.ini
  python3 main.py run --resume                 # skip already-done files
  python3 main.py run --max_retries 3          # retry each file up to 3 times
  python3 main.py run --usage_dir ../reports/  # override config input folder
        """,
    )
    root.add_argument(
        "--config", default=None, metavar="FILE",
        help=f"Path to config INI file (default: {DEFAULT_CONFIG}). "
             "CLI args always override config values.",
    )
    subs = root.add_subparsers(dest="command", required=True)

    # ── generate ──────────────────────────────────────────────────────────────
    p_gen = subs.add_parser("generate", help="Inspect CSV and generate mapper.json")
    p_gen.add_argument("--usage_report", required=False, default=None, metavar="FILE",
                       help="Path to a single SaaS usage export CSV.")
    _add_common_args(p_gen)
    p_gen.add_argument(
        "--output_mapper", default=None,
        help="Output mapper.json path (default: mappers/<tool>_mapper.json)."
    )
    p_gen.add_argument(
        "--log_dir", default=None, metavar="DIR",
        help=f"Directory for log file (default: {DEFAULT_LOG_DIR}).",
    )

    # ── transform ─────────────────────────────────────────────────────────────
    p_trn = subs.add_parser("transform", help="Convert CSV(s) using existing mapper.json")
    _add_input_group(p_trn)
    _add_common_args(p_trn)
    p_trn.add_argument("--mapper", required=False, default=None, help="Path to mapper.json.")
    _add_output_args(p_trn)
    _add_run_args(p_trn)

    # ── run ───────────────────────────────────────────────────────────────────
    p_run = subs.add_parser("run", help="Full pipeline: generate mapper (if needed) + convert")
    _add_input_group(p_run)
    _add_common_args(p_run)
    p_run.add_argument(
        "--mapper", default=None,
        help="Path to mapper.json (auto-detected/generated per file if not provided)."
    )
    p_run.add_argument(
        "--regenerate_mapper", action="store_true",
        help="Force re-generation of the mapper even if it already exists."
    )
    _add_output_args(p_run)
    _add_run_args(p_run)

    return root


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    # ── Load config and apply defaults ────────────────────────────────────────
    config_path = args.config or DEFAULT_CONFIG
    cfg = _load_config(config_path)
    if cfg.sections():
        log.info("Config loaded: %s", config_path)
    _apply_config_defaults(args, cfg)
    args._config_path = config_path  # stash for audit log

    # ── Create audit logger (shared across all sub-commands) ─────────────────
    log_dir = getattr(args, "log_dir", None) or DEFAULT_LOG_DIR
    audit   = RunLogger(log_dir=log_dir)

    exit_code = 0
    try:
        if args.command == "generate":
            if not getattr(args, "usage_report", None):
                # Auto-pick the first CSV from usage_dir when usage_report is not set.
                usage_dir = getattr(args, "usage_dir", None)
                if usage_dir:
                    candidates = sorted(glob.glob(os.path.join(usage_dir, "*.csv")))
                    if candidates:
                        args.usage_report = candidates[0]
                        log.info(
                            "No --usage_report specified — using first file from usage_dir: %s",
                            args.usage_report,
                        )
                    else:
                        raise ValueError(
                            f"No .csv files found in usage_dir: {usage_dir}\n"
                            "  Add a CSV export to that folder or set paths.usage_report in config.ini."
                        )
                else:
                    raise ValueError(
                        "No input CSV specified.\n"
                        "  Provide --usage_report FILE on the command line,\n"
                        "  or set  paths.usage_report  or  paths.usage_dir  in config.ini."
                    )
            cmd_generate(args, audit)

        elif args.command == "transform":
            _validate_input_source(args)
            if not getattr(args, "mapper", None):
                raise ValueError(
                    "No mapper specified.\n"
                    "  Provide --mapper PATH on the command line,\n"
                    "  or set  mapper.mapper  in config.ini."
                )
            failed = cmd_transform(args, audit)
            if failed:
                exit_code = 2  # partial failure

        elif args.command == "run":
            _validate_input_source(args)
            failed = cmd_run(args, audit)
            if failed:
                exit_code = 2  # partial failure

        else:
            parser.print_help()
            exit_code = 1

    except (FileNotFoundError, ValueError) as exc:
        log.error("Error: %s", exc)
        exit_code = 1
    except KeyboardInterrupt:
        log.info("Interrupted.")
        exit_code = 0

    if exit_code:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
