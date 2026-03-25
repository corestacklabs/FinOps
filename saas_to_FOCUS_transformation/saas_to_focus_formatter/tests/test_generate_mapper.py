"""
tests/test_generate_mapper.py
==============================
Unit tests for mapper_generator/generate_mapper.py
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mapper_generator.generate_mapper import (
    _detect_tag_sources,
    _find_best_match,
    _infer_default_unit,
    _infer_product_family,
    _infer_tool_name,
    _score_column,
    generate_mapper,
)

# Minimal FOCUS schema for generate_mapper tests (mirrors focus_schema.json structure)
_FOCUS_SCHEMA = {
    "columns": [
        {"name": "BillingPeriodStart"},
        {"name": "BillingPeriodEnd"},
        {"name": "ChargePeriodStart"},
        {"name": "ChargePeriodEnd"},
        {"name": "BilledCost"},
        {"name": "EffectiveCost"},
        {"name": "ListCost"},
        {"name": "ServiceName"},
        {"name": "SkuId"},
        {"name": "UsageType"},
        {"name": "ConsumedQuantity"},
        {"name": "ConsumedUnit"},
        {"name": "ResourceId"},
        {"name": "ResourceName"},
        {"name": "RegionName"},
        {"name": "Tags"},
        {"name": "ProductFamily"},
        # CLI-only columns (should be skipped by generator)
        {"name": "ProviderName"},
        {"name": "BillingAccountId"},
        {"name": "BillingAccountName"},
        # Static-default columns
        {"name": "BillingCurrency"},
        {"name": "ChargeCategory"},
        {"name": "ChargeFrequency"},
    ]
}


# ─────────────────────────────────────────────────────────────────────────────
# _score_column
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreColumn(unittest.TestCase):

    def test_no_match_returns_zero(self):
        score, _ = _score_column("irrelevant_col", [("net_amount", 10, "identity")])
        self.assertEqual(score, 0)

    def test_exact_pattern_match(self):
        score, transform = _score_column("net_amount", [("net_amount", 10, "identity")])
        self.assertEqual(score, 10)
        self.assertEqual(transform, "identity")

    def test_substring_match(self):
        # "amount" is in "net_amount"
        score, _ = _score_column("net_amount", [("amount", 3, "identity")])
        self.assertEqual(score, 3)

    def test_best_score_wins(self):
        patterns = [
            ("cost",       2, "identity"),
            ("net_amount", 10, "identity"),
            ("amount",     3, "identity"),
        ]
        score, transform = _score_column("net_amount", patterns)
        self.assertEqual(score, 10)

    def test_case_insensitive(self):
        score, _ = _score_column("NET_AMOUNT", [("net_amount", 10, "identity")])
        self.assertEqual(score, 10)

    def test_hyphen_treated_as_underscore(self):
        score, _ = _score_column("net-amount", [("net_amount", 10, "identity")])
        self.assertEqual(score, 10)


# ─────────────────────────────────────────────────────────────────────────────
# _find_best_match
# ─────────────────────────────────────────────────────────────────────────────

class TestFindBestMatch(unittest.TestCase):

    def test_finds_date_column(self):
        result = _find_best_match("BillingPeriodStart", ["date", "product", "cost"])
        self.assertIsNotNone(result)
        src, transform = result
        self.assertEqual(src, "date")
        self.assertEqual(transform, "to_iso8601_start")

    def test_finds_cost_column(self):
        result = _find_best_match("BilledCost", ["product", "net_amount", "quantity"])
        self.assertIsNotNone(result)
        src, _ = result
        self.assertEqual(src, "net_amount")

    def test_prefers_higher_score(self):
        # "net_amount" (score 10) should beat "cost" (score 4)
        result = _find_best_match("BilledCost", ["cost", "net_amount"])
        self.assertIsNotNone(result)
        src, _ = result
        self.assertEqual(src, "net_amount")

    def test_returns_none_when_no_match(self):
        result = _find_best_match("BilledCost", ["product_name", "service_label"])
        self.assertIsNone(result)

    def test_returns_none_for_unknown_focus_column(self):
        result = _find_best_match("NonExistentFocusCol", ["date", "cost"])
        self.assertIsNone(result)

    def test_service_name_humanize_transform(self):
        result = _find_best_match("ServiceName", ["product_name", "sku", "date"])
        self.assertIsNotNone(result)
        src, transform = result
        self.assertEqual(src, "product_name")
        self.assertEqual(transform, "humanize")


# ─────────────────────────────────────────────────────────────────────────────
# _detect_tag_sources
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectTagSources(unittest.TestCase):

    def test_detects_username(self):
        self.assertIn("username", _detect_tag_sources(["username", "cost", "date"]))

    def test_detects_organization(self):
        self.assertIn("organization", _detect_tag_sources(["organization"]))

    def test_detects_repository(self):
        self.assertIn("repository", _detect_tag_sources(["repository"]))

    def test_detects_cost_center(self):
        self.assertIn("cost_center_name", _detect_tag_sources(["cost_center_name"]))

    def test_no_tag_columns_returns_empty(self):
        result = _detect_tag_sources(["date", "product", "cost", "quantity"])
        self.assertEqual(result, [])

    def test_does_not_include_cost_or_date(self):
        result = _detect_tag_sources(["date", "net_amount", "product"])
        self.assertEqual(result, [])

    def test_mixed_columns(self):
        cols = ["date", "username", "product", "organization", "net_amount"]
        result = _detect_tag_sources(cols)
        self.assertIn("username", result)
        self.assertIn("organization", result)
        self.assertNotIn("date", result)
        self.assertNotIn("net_amount", result)

    def test_case_insensitive_detection(self):
        result = _detect_tag_sources(["Username", "ORGANIZATION"])
        self.assertIn("Username", result)
        self.assertIn("ORGANIZATION", result)


# ─────────────────────────────────────────────────────────────────────────────
# _infer_product_family
# ─────────────────────────────────────────────────────────────────────────────

class TestInferProductFamily(unittest.TestCase):

    def test_copilot(self):
        self.assertEqual(_infer_product_family("copilot"), "Developer Tools")

    def test_github(self):
        self.assertEqual(_infer_product_family("github"), "Developer Tools")

    def test_claude(self):
        self.assertEqual(_infer_product_family("claude"), "AI / Machine Learning")

    def test_anthropic(self):
        self.assertEqual(_infer_product_family("anthropic"), "AI / Machine Learning")

    def test_datadog(self):
        self.assertEqual(_infer_product_family("datadog"), "Observability")

    def test_snowflake(self):
        self.assertEqual(_infer_product_family("snowflake"), "Data & Analytics")

    def test_salesforce(self):
        self.assertEqual(_infer_product_family("salesforce"), "CRM")

    def test_unknown_returns_saas(self):
        self.assertEqual(_infer_product_family("unknown_vendor_xyz"), "SaaS")

    def test_case_insensitive(self):
        self.assertEqual(_infer_product_family("Copilot"), "Developer Tools")


# ─────────────────────────────────────────────────────────────────────────────
# _infer_tool_name
# ─────────────────────────────────────────────────────────────────────────────

class TestInferToolName(unittest.TestCase):

    def test_from_product_column_in_row(self):
        rows = [{"product": "copilot_for_business", "cost": "9.99"}]
        result = _infer_tool_name("usage_report.csv", ["product", "cost"], rows)
        self.assertEqual(result, "copilot")

    def test_from_filename_stem(self):
        # "slack_report" → strips "_report" noise word → "slack"
        result = _infer_tool_name("slack_report.csv", ["cost"], [])
        self.assertIn("slack", result)

    def test_strips_date_suffix_from_filename(self):
        result = _infer_tool_name("copilot_usage_2026.csv", ["cost"], [])
        self.assertIn("copilot", result)

    def test_empty_rows_falls_back_to_filename(self):
        result = _infer_tool_name("slack_export.csv", ["date", "cost"], [])
        self.assertIn("slack", result)


# ─────────────────────────────────────────────────────────────────────────────
# _infer_default_unit
# ─────────────────────────────────────────────────────────────────────────────

class TestInferDefaultUnit(unittest.TestCase):

    def test_reads_from_sample_data_first(self):
        rows = [{"unit_type": "user-months"}]
        result = _infer_default_unit("copilot", rows, "unit_type")
        self.assertEqual(result, "user-months")

    def test_ai_tool_returns_tokens(self):
        result = _infer_default_unit("claude", [], "unit_type")
        self.assertEqual(result, "Tokens")

    def test_copilot_returns_seats(self):
        result = _infer_default_unit("copilot", [], "unit_type")
        self.assertEqual(result, "Seats")

    def test_datadog_returns_events(self):
        result = _infer_default_unit("datadog", [], "unit_type")
        self.assertEqual(result, "Events")

    def test_snowflake_returns_credits(self):
        result = _infer_default_unit("snowflake", [], "unit_type")
        self.assertEqual(result, "Credits")

    def test_unknown_returns_units(self):
        result = _infer_default_unit("unknown_vendor", [], "unit_type")
        self.assertEqual(result, "Units")


# ─────────────────────────────────────────────────────────────────────────────
# generate_mapper — integration
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateMapper(unittest.TestCase):

    def _copilot_columns(self):
        return [
            "date", "product", "sku", "quantity", "unit_type",
            "applied_cost_per_quantity", "gross_amount", "discount_amount",
            "net_amount", "username", "organization", "repository",
            "workflow_path", "cost_center_name",
        ]

    def _copilot_rows(self):
        return [{
            "date": "2026-03-01",
            "product": "copilot_for_business",
            "sku": "copilot_for_business_seat",
            "quantity": "1",
            "unit_type": "user-months",
            "applied_cost_per_quantity": "0",
            "gross_amount": "19.00",
            "discount_amount": "0",
            "net_amount": "19.00",
            "username": "alice",
            "organization": "CoreStack-Engg",
            "repository": "api-gateway",
            "workflow_path": "",
            "cost_center_name": "eng",
        }]

    def test_mapper_has_required_top_level_keys(self):
        mapper = generate_mapper(
            source_columns=self._copilot_columns(),
            sample_rows=self._copilot_rows(),
            focus_schema=_FOCUS_SCHEMA,
            tool_name="copilot",
            provider_name="GitHub",
        )
        self.assertIn("meta", mapper)
        self.assertIn("defaults", mapper)
        self.assertIn("mappings", mapper)

    def test_meta_tool_name(self):
        mapper = generate_mapper(
            source_columns=self._copilot_columns(),
            sample_rows=self._copilot_rows(),
            focus_schema=_FOCUS_SCHEMA,
            tool_name="copilot",
        )
        self.assertEqual(mapper["meta"]["tool_name"], "copilot")

    def test_meta_source_columns(self):
        cols = self._copilot_columns()
        mapper = generate_mapper(
            source_columns=cols,
            sample_rows=self._copilot_rows(),
            focus_schema=_FOCUS_SCHEMA,
            tool_name="copilot",
        )
        self.assertEqual(mapper["meta"]["source_columns"], cols)

    def test_defaults_include_static_columns(self):
        mapper = generate_mapper(
            source_columns=self._copilot_columns(),
            sample_rows=self._copilot_rows(),
            focus_schema=_FOCUS_SCHEMA,
            tool_name="copilot",
            provider_name="GitHub",
        )
        self.assertEqual(mapper["defaults"]["ChargeCategory"], "Usage")
        self.assertEqual(mapper["defaults"]["ChargeFrequency"], "Monthly")
        self.assertEqual(mapper["defaults"]["BillingCurrency"], "USD")
        self.assertEqual(mapper["defaults"]["ProviderName"], "GitHub")

    def test_billing_period_start_mapped_to_date(self):
        mapper = generate_mapper(
            source_columns=self._copilot_columns(),
            sample_rows=self._copilot_rows(),
            focus_schema=_FOCUS_SCHEMA,
            tool_name="copilot",
        )
        bp = mapper["mappings"]["BillingPeriodStart"]
        self.assertEqual(bp["source"], "date")
        self.assertEqual(bp["transform"], "to_iso8601_start")

    def test_billed_cost_mapped_to_net_amount(self):
        mapper = generate_mapper(
            source_columns=self._copilot_columns(),
            sample_rows=self._copilot_rows(),
            focus_schema=_FOCUS_SCHEMA,
            tool_name="copilot",
        )
        bc = mapper["mappings"]["BilledCost"]
        self.assertEqual(bc["source"], "net_amount")
        self.assertEqual(bc["default_value"], "0")

    def test_tags_mapping_contains_contextual_columns(self):
        mapper = generate_mapper(
            source_columns=self._copilot_columns(),
            sample_rows=self._copilot_rows(),
            focus_schema=_FOCUS_SCHEMA,
            tool_name="copilot",
        )
        tags = mapper["mappings"]["Tags"]
        self.assertEqual(tags["transform"], "build_tags")
        tag_sources = tags["tag_sources"]
        self.assertIn("username", tag_sources)
        self.assertIn("organization", tag_sources)

    def test_product_family_is_static(self):
        mapper = generate_mapper(
            source_columns=self._copilot_columns(),
            sample_rows=self._copilot_rows(),
            focus_schema=_FOCUS_SCHEMA,
            tool_name="copilot",
        )
        pf = mapper["mappings"]["ProductFamily"]
        self.assertEqual(pf["transform"], "static")
        self.assertEqual(pf["static_value"], "Developer Tools")

    def test_cli_only_columns_not_in_mappings(self):
        mapper = generate_mapper(
            source_columns=self._copilot_columns(),
            sample_rows=self._copilot_rows(),
            focus_schema=_FOCUS_SCHEMA,
            tool_name="copilot",
        )
        for col in ("ProviderName", "BillingAccountId", "BillingAccountName"):
            self.assertNotIn(col, mapper["mappings"])

    def test_static_columns_not_in_mappings(self):
        mapper = generate_mapper(
            source_columns=self._copilot_columns(),
            sample_rows=self._copilot_rows(),
            focus_schema=_FOCUS_SCHEMA,
            tool_name="copilot",
        )
        for col in ("ChargeCategory", "ChargeFrequency", "BillingCurrency"):
            self.assertNotIn(col, mapper["mappings"])

    def test_custom_product_family_overrides_inference(self):
        mapper = generate_mapper(
            source_columns=self._copilot_columns(),
            sample_rows=self._copilot_rows(),
            focus_schema=_FOCUS_SCHEMA,
            tool_name="copilot",
            product_family="Custom Category",
        )
        self.assertEqual(mapper["mappings"]["ProductFamily"]["static_value"], "Custom Category")

    def test_custom_currency(self):
        mapper = generate_mapper(
            source_columns=self._copilot_columns(),
            sample_rows=self._copilot_rows(),
            focus_schema=_FOCUS_SCHEMA,
            tool_name="copilot",
            currency="EUR",
        )
        self.assertEqual(mapper["defaults"]["BillingCurrency"], "EUR")

    def test_no_provider_name_not_in_defaults(self):
        mapper = generate_mapper(
            source_columns=self._copilot_columns(),
            sample_rows=self._copilot_rows(),
            focus_schema=_FOCUS_SCHEMA,
            tool_name="copilot",
            provider_name="",
        )
        self.assertNotIn("ProviderName", mapper["defaults"])


if __name__ == "__main__":
    unittest.main()
