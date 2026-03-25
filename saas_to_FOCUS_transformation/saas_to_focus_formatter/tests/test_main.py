"""
tests/test_main.py
==================
Unit tests for the batch helper functions in main.py:
  - _get_input_files()
  - _resolve_output_path()

All tests run without I/O to the transform engine or mapper — only the
argument-parsing and path-resolution helpers are exercised.

Run:
    python3 -m unittest tests.test_main -v
"""

import argparse
import os
import sys
import tempfile
import unittest

# ── Make sure the project root is importable ─────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from main import _get_input_files, _resolve_output_path


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_args(**kwargs) -> argparse.Namespace:
    """Build a minimal Namespace with sensible defaults."""
    defaults = {
        "usage_report": None,
        "usage_dir": None,
        "output": "focus_cur_output.csv",
        "output_dir": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# TestGetInputFiles
# ─────────────────────────────────────────────────────────────────────────────

class TestGetInputFiles(unittest.TestCase):
    """Tests for _get_input_files()."""

    def test_single_file_returns_list_of_one(self):
        args = _make_args(usage_report="path/to/report.csv")
        result = _get_input_files(args)
        self.assertEqual(result, ["path/to/report.csv"])

    def test_single_file_no_usage_dir(self):
        args = _make_args(usage_report="/abs/path/usage.csv", usage_dir=None)
        self.assertEqual(_get_input_files(args), ["/abs/path/usage.csv"])

    def test_batch_folder_returns_sorted_csv_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create CSV files in non-alphabetical order
            for name in ["charlie.csv", "alpha.csv", "bravo.csv"]:
                open(os.path.join(tmpdir, name), "w").close()
            # Also create a non-CSV file that must be excluded
            open(os.path.join(tmpdir, "notes.txt"), "w").close()

            args = _make_args(usage_dir=tmpdir)
            result = _get_input_files(args)

        basenames = [os.path.basename(p) for p in result]
        self.assertEqual(basenames, ["alpha.csv", "bravo.csv", "charlie.csv"])

    def test_batch_folder_excludes_non_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "data.csv"), "w").close()
            open(os.path.join(tmpdir, "data.json"), "w").close()
            open(os.path.join(tmpdir, "data.txt"), "w").close()

            args = _make_args(usage_dir=tmpdir)
            result = _get_input_files(args)

        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].endswith("data.csv"))

    def test_batch_folder_single_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "only.csv"), "w").close()
            args = _make_args(usage_dir=tmpdir)
            result = _get_input_files(args)

        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].endswith("only.csv"))

    def test_empty_folder_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _make_args(usage_dir=tmpdir)
            with self.assertRaises(ValueError) as ctx:
                _get_input_files(args)
        self.assertIn(tmpdir, str(ctx.exception))

    def test_folder_with_no_csv_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "readme.txt"), "w").close()
            args = _make_args(usage_dir=tmpdir)
            with self.assertRaises(ValueError):
                _get_input_files(args)

    def test_usage_dir_takes_precedence_over_usage_report(self):
        """When usage_dir is set, usage_report is ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "batch.csv"), "w").close()
            # Both are set — usage_dir wins
            args = _make_args(usage_report="single.csv", usage_dir=tmpdir)
            result = _get_input_files(args)

        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].endswith("batch.csv"))

    def test_multiple_csv_files_all_returned(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            names = [f"file_{i:02d}.csv" for i in range(5)]
            for name in names:
                open(os.path.join(tmpdir, name), "w").close()
            args = _make_args(usage_dir=tmpdir)
            result = _get_input_files(args)

        self.assertEqual(len(result), 5)


# ─────────────────────────────────────────────────────────────────────────────
# TestResolveOutputPath
# ─────────────────────────────────────────────────────────────────────────────

class TestResolveOutputPath(unittest.TestCase):
    """Tests for _resolve_output_path()."""

    def test_single_file_mode_returns_args_output(self):
        args = _make_args(output="../focus_cur_output.csv", output_dir=None)
        result = _resolve_output_path("../usage_report.csv", args)
        self.assertEqual(result, "../focus_cur_output.csv")

    def test_single_file_mode_custom_output(self):
        args = _make_args(output="/custom/path/out.csv", output_dir=None)
        result = _resolve_output_path("some_input.csv", args)
        self.assertEqual(result, "/custom/path/out.csv")

    def test_batch_mode_uses_output_dir_and_stem(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _make_args(output_dir=tmpdir)
            result = _resolve_output_path("/data/usage_reports/copilot_march.csv", args)

        expected_name = "copilot_march_focus_cur.csv"
        self.assertEqual(os.path.basename(result), expected_name)

    def test_batch_mode_output_in_correct_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _make_args(output_dir=tmpdir)
            result = _resolve_output_path("copilot_april.csv", args)

        self.assertEqual(os.path.dirname(result), tmpdir)

    def test_batch_mode_creates_output_dir_if_missing(self):
        with tempfile.TemporaryDirectory() as parent:
            new_dir = os.path.join(parent, "outputs", "sub")
            args = _make_args(output_dir=new_dir)
            _resolve_output_path("input.csv", args)
            self.assertTrue(os.path.isdir(new_dir))

    def test_batch_mode_strips_extension_correctly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _make_args(output_dir=tmpdir)

            for stem in ["data", "vendor_export", "usage_2026_03"]:
                result = _resolve_output_path(f"{stem}.csv", args)
                self.assertEqual(
                    os.path.basename(result), f"{stem}_focus_cur.csv",
                    msg=f"Stem '{stem}' produced wrong output name"
                )

    def test_batch_mode_handles_path_with_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _make_args(output_dir=tmpdir)
            result = _resolve_output_path("/some/deep/path/slack_march.csv", args)

        self.assertEqual(os.path.basename(result), "slack_march_focus_cur.csv")

    def test_single_file_mode_no_output_dir_set(self):
        """output_dir=None must fall through to args.output regardless of input path."""
        args = _make_args(output="focus_cur_output.csv", output_dir=None)
        # Different input paths should all yield the same single output
        for inp in ["a.csv", "b.csv", "/path/c.csv"]:
            result = _resolve_output_path(inp, args)
            self.assertEqual(result, "focus_cur_output.csv")


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main()
