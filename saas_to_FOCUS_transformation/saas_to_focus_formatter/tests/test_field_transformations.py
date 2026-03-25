"""
tests/test_field_transformations.py
====================================
Unit tests for transform_engine/field_transformations.py
"""

import json
import sys
import os
import unittest

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from transform_engine.field_transformations import (
    _lookup_column,
    _parse_dt,
    apply_transform,
    build_tags,
    first_non_empty,
    humanize,
    identity,
    static_value,
    strip_whitespace,
    title_case,
    to_billing_period_end,
    to_decimal,
    to_iso8601_end,
    to_iso8601_start,
    to_lowercase,
    to_uppercase,
)


class TestIdentity(unittest.TestCase):
    def test_passthrough(self):
        self.assertEqual(identity("hello"), "hello")

    def test_empty(self):
        self.assertEqual(identity(""), "")

    def test_numeric_string(self):
        self.assertEqual(identity("3.14"), "3.14")


class TestToIso8601Start(unittest.TestCase):
    def test_iso_date(self):
        self.assertEqual(to_iso8601_start("2026-03-15"), "2026-03-15T00:00:00Z")

    def test_iso_datetime(self):
        self.assertEqual(to_iso8601_start("2026-03-15T14:30:00Z"), "2026-03-15T00:00:00Z")

    def test_slash_format(self):
        self.assertEqual(to_iso8601_start("2026/03/15"), "2026-03-15T00:00:00Z")

    def test_us_format(self):
        self.assertEqual(to_iso8601_start("03/15/2026"), "2026-03-15T00:00:00Z")

    def test_dmy_format(self):
        self.assertEqual(to_iso8601_start("15-03-2026"), "2026-03-15T00:00:00Z")

    def test_empty_returns_empty(self):
        self.assertEqual(to_iso8601_start(""), "")

    def test_invalid_returns_empty(self):
        self.assertEqual(to_iso8601_start("not-a-date"), "")

    def test_first_of_month(self):
        self.assertEqual(to_iso8601_start("2026-03-01"), "2026-03-01T00:00:00Z")


class TestToIso8601End(unittest.TestCase):
    def test_iso_date(self):
        self.assertEqual(to_iso8601_end("2026-03-15"), "2026-03-15T23:59:59Z")

    def test_iso_datetime(self):
        self.assertEqual(to_iso8601_end("2026-03-15T14:30:00"), "2026-03-15T23:59:59Z")

    def test_empty_returns_empty(self):
        self.assertEqual(to_iso8601_end(""), "")

    def test_invalid_returns_empty(self):
        self.assertEqual(to_iso8601_end("bad"), "")

    def test_end_of_year(self):
        self.assertEqual(to_iso8601_end("2026-12-31"), "2026-12-31T23:59:59Z")


class TestToBillingPeriodEnd(unittest.TestCase):
    def test_mid_month(self):
        # March 15 → April 1
        self.assertEqual(to_billing_period_end("2026-03-15"), "2026-04-01T00:00:00Z")

    def test_first_of_month(self):
        # March 1 → April 1
        self.assertEqual(to_billing_period_end("2026-03-01"), "2026-04-01T00:00:00Z")

    def test_december_rolls_over(self):
        # December → January of next year
        self.assertEqual(to_billing_period_end("2026-12-01"), "2027-01-01T00:00:00Z")

    def test_november(self):
        self.assertEqual(to_billing_period_end("2026-11-30"), "2026-12-01T00:00:00Z")

    def test_empty_returns_empty(self):
        self.assertEqual(to_billing_period_end(""), "")

    def test_invalid_returns_empty(self):
        self.assertEqual(to_billing_period_end("???"), "")


class TestHumanize(unittest.TestCase):
    def test_underscores(self):
        self.assertEqual(humanize("copilot_for_business"), "Copilot For Business")

    def test_hyphens(self):
        self.assertEqual(humanize("datadog-apm-metrics"), "Datadog Apm Metrics")

    def test_mixed(self):
        self.assertEqual(humanize("my_tool-v2"), "My Tool V2")

    def test_already_clean(self):
        self.assertEqual(humanize("GitHub"), "Github")

    def test_empty(self):
        self.assertEqual(humanize(""), "")

    def test_multiple_underscores(self):
        # [_\-]+ collapses consecutive separators into a single space
        self.assertEqual(humanize("a__b"), "A B")


class TestTitleCase(unittest.TestCase):
    def test_lowercase(self):
        self.assertEqual(title_case("developer tools"), "Developer Tools")

    def test_already_title(self):
        self.assertEqual(title_case("Developer Tools"), "Developer Tools")

    def test_preserves_symbols(self):
        # title_case does NOT replace symbols (unlike humanize)
        self.assertEqual(title_case("copilot_for_business"), "Copilot_For_Business")


class TestToUppercase(unittest.TestCase):
    def test_lowercase_input(self):
        self.assertEqual(to_uppercase("usd"), "USD")

    def test_mixed(self):
        self.assertEqual(to_uppercase("GitHub"), "GITHUB")

    def test_already_upper(self):
        self.assertEqual(to_uppercase("USD"), "USD")


class TestToLowercase(unittest.TestCase):
    def test_uppercase_input(self):
        self.assertEqual(to_lowercase("USD"), "usd")

    def test_mixed(self):
        self.assertEqual(to_lowercase("GitHub"), "github")


class TestStripWhitespace(unittest.TestCase):
    def test_leading_trailing(self):
        self.assertEqual(strip_whitespace("  foo  "), "foo")

    def test_internal_space_preserved(self):
        self.assertEqual(strip_whitespace("  foo bar  "), "foo bar")

    def test_no_spaces(self):
        self.assertEqual(strip_whitespace("foo"), "foo")


class TestToDecimal(unittest.TestCase):
    def test_integer_string(self):
        self.assertEqual(to_decimal("100"), "100")

    def test_float_string(self):
        self.assertEqual(to_decimal("3.14"), "3.14")

    def test_currency_symbol(self):
        self.assertEqual(to_decimal("$1234.56"), "1234.56")

    def test_comma_separator(self):
        self.assertEqual(to_decimal("$1,234.56"), "1234.56")

    def test_empty_returns_zero(self):
        self.assertEqual(to_decimal(""), "0")

    def test_whitespace_only_returns_zero(self):
        self.assertEqual(to_decimal("   "), "0")

    def test_invalid_returns_zero(self):
        self.assertEqual(to_decimal("not-a-number"), "0")

    def test_negative(self):
        self.assertEqual(to_decimal("-5.00"), "-5.00")

    def test_zero(self):
        self.assertEqual(to_decimal("0"), "0")


class TestBuildTags(unittest.TestCase):
    def _row(self):
        return {
            "username": "alice",
            "organization": "CoreStack-Engg",
            "repository": "api-gateway",
            "workflow_path": "",
        }

    def test_list_of_strings(self):
        config = {"tag_sources": ["username", "organization"]}
        result = json.loads(build_tags("", row=self._row(), config=config))
        self.assertEqual(result, {"username": "alice", "organization": "CoreStack-Engg"})

    def test_list_of_pairs_with_key_rename(self):
        config = {"tag_sources": [["user", "username"], ["org", "organization"]]}
        result = json.loads(build_tags("", row=self._row(), config=config))
        self.assertEqual(result, {"user": "alice", "org": "CoreStack-Engg"})

    def test_empty_values_excluded(self):
        config = {"tag_sources": ["username", "workflow_path"]}
        result = json.loads(build_tags("", row=self._row(), config=config))
        self.assertNotIn("workflow_path", result)
        self.assertIn("username", result)

    def test_no_row_returns_empty_json(self):
        config = {"tag_sources": ["username"]}
        self.assertEqual(build_tags("", row=None, config=config), "{}")

    def test_no_config_returns_empty_json(self):
        self.assertEqual(build_tags("", row=self._row(), config=None), "{}")

    def test_no_matching_columns_returns_empty_json(self):
        config = {"tag_sources": ["nonexistent_col"]}
        self.assertEqual(build_tags("", row=self._row(), config=config), "{}")

    def test_case_insensitive_lookup(self):
        row = {"USERNAME": "bob", "Org": "acme"}
        config = {"tag_sources": ["username", "org"]}
        result = json.loads(build_tags("", row=row, config=config))
        self.assertEqual(result["username"], "bob")

    def test_compact_json_no_spaces(self):
        config = {"tag_sources": ["username"]}
        output = build_tags("", row=self._row(), config=config)
        self.assertNotIn(" ", output)  # separators=(",",":")


class TestStaticValue(unittest.TestCase):
    def test_returns_static_value(self):
        self.assertEqual(static_value("ignored", config={"static_value": "Developer Tools"}), "Developer Tools")

    def test_ignores_source_value(self):
        self.assertEqual(static_value("THIS_IS_IGNORED", config={"static_value": "AI / ML"}), "AI / ML")

    def test_no_config_returns_empty(self):
        self.assertEqual(static_value("x", config=None), "")

    def test_missing_key_returns_empty(self):
        self.assertEqual(static_value("x", config={}), "")


class TestFirstNonEmpty(unittest.TestCase):
    def _row(self):
        return {"col_a": "", "col_b": "value_b", "col_c": "value_c"}

    def test_returns_first_non_empty(self):
        config = {"sources": ["col_a", "col_b", "col_c"]}
        self.assertEqual(first_non_empty("", row=self._row(), config=config), "value_b")

    def test_falls_back_to_value_if_all_empty(self):
        config = {"sources": ["col_a", "missing"]}
        self.assertEqual(first_non_empty("fallback", row=self._row(), config=config), "fallback")

    def test_no_row_returns_value(self):
        config = {"sources": ["col_b"]}
        self.assertEqual(first_non_empty("original", row=None, config=config), "original")

    def test_no_config_returns_value(self):
        self.assertEqual(first_non_empty("original", row=self._row(), config=None), "original")


class TestLookupColumn(unittest.TestCase):
    def _row(self):
        return {"date": "2026-03-01", "net_amount": "9.99", "UsagePeriod": "March"}

    def test_exact_match(self):
        self.assertEqual(_lookup_column(self._row(), "date"), "2026-03-01")

    def test_case_insensitive(self):
        self.assertEqual(_lookup_column(self._row(), "NET_AMOUNT"), "9.99")

    def test_substring_match(self):
        # "date" is a substring of "usageperiod"? No — but "period" is not either.
        # "date" IS a substring of nothing here. Let's test "amount" → "net_amount"
        self.assertEqual(_lookup_column(self._row(), "amount"), "9.99")

    def test_missing_column_returns_empty(self):
        self.assertEqual(_lookup_column(self._row(), "nonexistent"), "")

    def test_empty_row_returns_empty(self):
        self.assertEqual(_lookup_column({}, "date"), "")

    def test_strips_whitespace_from_value(self):
        row = {"col": "  value  "}
        self.assertEqual(_lookup_column(row, "col"), "value")


class TestApplyTransform(unittest.TestCase):
    def test_valid_transform(self):
        self.assertEqual(apply_transform("identity", "hello"), "hello")

    def test_date_transform(self):
        self.assertEqual(apply_transform("to_iso8601_start", "2026-03-01"), "2026-03-01T00:00:00Z")

    def test_unknown_transform_raises(self):
        with self.assertRaises(ValueError) as ctx:
            apply_transform("nonexistent_transform", "value")
        self.assertIn("nonexistent_transform", str(ctx.exception))
        self.assertIn("Available", str(ctx.exception))

    def test_returns_string(self):
        result = apply_transform("identity", "123")
        self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
