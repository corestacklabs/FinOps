"""
audit/run_logger.py  —  Structured run logging + JSON checkpoint state
=======================================================================

Creates / updates two files in <log_dir>/ on every run:

  latest.log       Full human-readable log, overwritten each run.
                   Written to both the file and stderr simultaneously.
  run_state.json   Atomic JSON checkpoint updated after every file;
                   used by --resume to skip already-done files.

Typical usage (in main.py)
--------------------------
  audit = RunLogger(log_dir="logs")
  audit.start_run("run", files, config_path, params)

  for i, path in enumerate(files, 1):
      audit.start_file(i, n, path, out_path, mapper_path)
      for attempt in range(1, max_retries + 1):
          try:
              rows = convert(...)
              audit.finish_file(i, n, path, rows, elapsed)
              break
          except Exception as exc:
              audit.fail_file(i, n, path, exc, elapsed, final=(attempt == max_retries))

  audit.finish_run(done, failed, skipped, total_rows)
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


class RunLogger:
    """
    Dual-sink logger:
      * Writes structured lines to <log_dir>/latest.log  (overwritten per run)
      * Maintains   <log_dir>/run_state.json             (atomic JSON checkpoint)

    All public methods are safe to call even if the log directory cannot be
    created — errors are printed to stderr and execution continues.
    """

    LOG_FILE   = "latest.log"
    STATE_FILE = "run_state.json"

    def __init__(self, log_dir: str) -> None:
        self.log_dir    = log_dir
        self.run_id     = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.log_path   = os.path.join(log_dir, self.LOG_FILE)
        self.state_path = os.path.join(log_dir, self.STATE_FILE)

        self._state: Dict      = {}
        self._run_start: float = 0.0

        try:
            os.makedirs(log_dir, exist_ok=True)
            self._setup_file_logger()
        except OSError as exc:
            logging.warning("audit: cannot create log dir %s — %s", log_dir, exc)
            self._file_log = logging.getLogger("audit.noop")

    # ── Logger setup ──────────────────────────────────────────────────────────

    def _setup_file_logger(self) -> None:
        """Configure a logger that writes to latest.log (overwrite) + stderr."""
        name = f"audit.{self.run_id}"
        self._file_log = logging.getLogger(name)
        self._file_log.setLevel(logging.DEBUG)
        self._file_log.propagate = False   # avoid duplicate output via root logger

        fmt = logging.Formatter(
            "%(asctime)s  %(levelname)-5s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # File sink — overwrite each run so latest.log is always the current run
        fh = logging.FileHandler(self.log_path, mode="w", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        self._file_log.addHandler(fh)

        # Console sink — INFO and above, same as root logger
        sh = logging.StreamHandler()
        sh.setLevel(logging.INFO)
        sh.setFormatter(logging.Formatter("%(levelname)-5s %(message)s"))
        self._file_log.addHandler(sh)

    # ── State persistence (atomic write) ─────────────────────────────────────

    def _save_state(self) -> None:
        try:
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, default=str)
            os.replace(tmp, self.state_path)
        except OSError as exc:
            self._file_log.warning("audit: could not save state — %s", exc)

    def _load_prev_state(self) -> Dict:
        if not os.path.exists(self.state_path):
            return {}
        try:
            with open(self.state_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    # ── Run lifecycle ─────────────────────────────────────────────────────────

    def start_run(
        self,
        command: str,
        input_files: List[str],
        config_path: str,
        params: Dict,
    ) -> None:
        """Log run start and initialise the checkpoint state."""
        self._run_start = time.monotonic()
        # Preserve existing done-file entries so --resume works across calls
        prev = self._load_prev_state()
        prev_files = prev.get("files", {})
        files_state = {}
        for f in input_files:
            prev_entry = prev_files.get(f, {"status": "pending"})
            # Reset attempts for each new run; preserve status so --resume still works.
            files_state[f] = {**prev_entry, "attempts": 0}

        self._state = {
            "run_id":     self.run_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "command":    command,
            "config":     config_path,
            "params":     {k: v for k, v in params.items() if v},
            "files":      files_state,
        }
        self._save_state()

        sep = "=" * 72
        self._file_log.info(sep)
        self._file_log.info(
            "RUN START   run_id=%-20s  command=%s", self.run_id, command
        )
        self._file_log.info("Config      : %s", config_path)
        self._file_log.info("Input files : %d", len(input_files))
        for i, f in enumerate(input_files, 1):
            self._file_log.info("  [%d/%d] %s", i, len(input_files), f)
        if params:
            self._file_log.info("Parameters  :")
            for k, v in params.items():
                if v:
                    self._file_log.info("  %-26s: %s", k, v)
        self._file_log.info("-" * 72)

    def start_file(
        self,
        index: int,
        total: int,
        input_path: str,
        output_path: str,
        mapper_path: str,
        attempt: int = 1,
    ) -> None:
        """Log that a file is now being processed."""
        prev_attempts = self._state["files"].get(input_path, {}).get("attempts", 0)
        self._state["files"][input_path] = {
            "status":     "in_progress",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "output":     output_path,
            "mapper":     mapper_path,
            "attempts":   prev_attempts + 1,
        }
        self._save_state()

        prefix = f"[{index}/{total}]"
        if attempt > 1:
            self._file_log.info(
                "%s START  (attempt %d)  %s", prefix, attempt, input_path
            )
        else:
            self._file_log.info("%s START   %s", prefix, input_path)
        self._file_log.info("%s   output : %s", prefix, output_path)
        self._file_log.info("%s   mapper : %s", prefix, mapper_path)

    def finish_file(
        self,
        index: int,
        total: int,
        input_path: str,
        rows_written: int,
        elapsed: float,
    ) -> None:
        """Log successful completion of one file."""
        entry = self._state["files"].get(input_path, {})
        entry.update({
            "status":      "done",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "rows":        rows_written,
            "elapsed_s":   round(elapsed, 3),
        })
        self._state["files"][input_path] = entry
        self._save_state()

        self._file_log.info(
            "[%d/%d] DONE    rows=%-6d  elapsed=%.2fs  %s",
            index, total, rows_written, elapsed, input_path,
        )

    def fail_file(
        self,
        index: int,
        total: int,
        input_path: str,
        error: Exception,
        elapsed: float,
        final: bool = True,
    ) -> None:
        """
        Log a file processing failure.
        final=True  → permanent failure, status set to 'failed'
        final=False → will be retried, status set to 'retrying'
        """
        entry = self._state["files"].get(input_path, {})
        entry.update({
            "status":    "failed" if final else "retrying",
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "error":     str(error),
            "elapsed_s": round(elapsed, 3),
        })
        self._state["files"][input_path] = entry
        self._save_state()

        level = logging.ERROR if final else logging.WARNING
        label = "FAIL  " if final else "RETRY "
        self._file_log.log(
            level,
            "[%d/%d] %s  elapsed=%.2fs  error=%s  file=%s",
            index, total, label, elapsed, error, input_path,
        )

    def finish_run(
        self,
        done: int,
        failed: int,
        skipped: int,
        total_rows: int,
    ) -> None:
        """Log run summary and finalise the checkpoint."""
        elapsed = time.monotonic() - self._run_start
        self._state["finished_at"] = datetime.now(timezone.utc).isoformat()
        self._state["summary"] = {
            "done":       done,
            "failed":     failed,
            "skipped":    skipped,
            "total_rows": total_rows,
            "elapsed_s":  round(elapsed, 3),
        }
        self._save_state()

        status = "COMPLETE" if not failed else "COMPLETE WITH ERRORS"
        self._file_log.info("-" * 72)
        self._file_log.info(
            "RUN %-20s done=%d  failed=%d  skipped=%d  rows=%d  elapsed=%.2fs",
            status, done, failed, skipped, total_rows, elapsed,
        )
        self._file_log.info("Log   : %s", self.log_path)
        self._file_log.info("State : %s", self.state_path)
        self._file_log.info("=" * 72)

    # ── Resume helpers ────────────────────────────────────────────────────────

    def filter_resumable_files(
        self, all_files: List[str]
    ) -> Tuple[List[str], int]:
        """
        For --resume: return (pending_files, skipped_count).
        Files with status='done' in the previous run_state.json are skipped.
        Any file not in the previous state (new files) is included.
        """
        prev = self._load_prev_state()
        if not prev:
            self._file_log.info("Resume: no previous state found — processing all files.")
            return all_files, 0

        done_set = {
            f for f, info in prev.get("files", {}).items()
            if info.get("status") == "done"
        }
        pending = [f for f in all_files if f not in done_set]
        skipped = len(all_files) - len(pending)
        if skipped:
            self._file_log.info(
                "Resume: skipping %d already-done file(s); %d remaining.",
                skipped, len(pending),
            )
        failed_prev = [
            f for f in all_files
            if prev.get("files", {}).get(f, {}).get("status") == "failed"
        ]
        if failed_prev:
            self._file_log.info(
                "Resume: retrying %d previously-failed file(s).", len(failed_prev)
            )
        return pending, skipped
