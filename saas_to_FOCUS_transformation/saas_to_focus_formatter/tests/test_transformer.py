"""
tests/test_transformer.py
==========================
Unit tests for transform_engine/transformer.py
"""

import json
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from transform_engine.transformer import (
    REQUIRED_FOCUS_COLUMNS,
    MapperDrivenTransformer,
    inject_extra_tag,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA = [
    "ProviderName", "BillingAccountId", "BillingAccountName", "BillingCurrency",
    "BillingPeriodEnd", "BillingPeriodStart", "BilledCost", "EffectiveCost",
    "ListCost", "ChargeCategory", "ChargeFrequency", "ChargePeriodEnd",
    "ChargePeriodStart", "ServiceName", "ConsumedQuantity", "ConsumedUnit",
    "RegionName", "ResourceId", "ResourceName", "SkuId", "Tags",
    "UsageType", "ProductFamily",
]

MINIMAL_MAPPER = {
    "meta": {"tool_name": "test"},
    "defaults": {
        "ChargeCategory": "Usage",
        "ChargeFrequency": "Monthly",
        "BillingCurrency": "USD",
        "ProviderName": "TestCo",
    },
    "mappings": {
        "BillingPeriodStart": {"source": "date", "transform": "to_iso8601_start"},
        "BillingPeriodEnd":   {"source": "date", "transform": "to_billing_period_end"},
        "ChargePeriodStart":  {"source": "date", "transform": "to_iso8601_start"},
        "ChargePeriodEnd":    {"source": "date", "transform": "to_iso8601_end"},
        "BilledCost":         {"source": "cost", "transform": "identity", "default_value": "0"},
        "EffectiveCost":      {"source": "cost", "transform": "identity", "default_value": "0"},
        "ListCost":           {"source": "cost", "transform": "identity", "default_value": "0"},
        "ServiceName":        {"source": "product", "transform": "humanize"},
        "ProductFamily":      {"transform": "static", "static_value": "Developer Tools"},
        "Tags": {
            "transform": "build_tags",
            "tag_sources": ["username", "organization"],
        },
    },
}

SAMPLE_ROW = {
    "date": "2026-03-15",
    "product": "copilot_for_business",
    "cost": "19.99",
    "username": "alice",
    "organization": "CoreStack-Engg",
}

FULL_CLI_PARAMS = {
    "ProviderName": "GitHub",
    "BillingAccountId": "org-CoreStack-Engg",
    "BillingAccountName": "CoreStack Engineering",
    "BillingCurrency": "USD",
}


# ─────────────────────────────────────────────────────────────────────────────
# MapperDrivenTransformer tests
# ─────────────────────────────────────────────────────────────────────────────

class TestThreeTierResolution(unittest.TestCase):
    """Tier 1 (CLI) beats Tier 2 (mappings), which beats Tier 3 (defaults)."""

    def test_tier1_cli_wins_over_defaults(self):
        t = MapperDrivenTransformer(MINIMAL_MAPPER, SCHEMA, {"ProviderName": "Override"})
        out = t.transform_row(SAMPLE_ROW)
        self.assertEqual(out["ProviderName"], "Override")

    def test_tier3_default_used_when_no_mapping(self):
        t = MapperDrivenTransformer(MINIMAL_MAPPER, SCHEMA, {})
        out = t.transform_row(SAMPLE_ROW)
        self.assertEqual(out["ChargeCategory"], "Usage")
        self.assertEqual(out["ChargeFrequency"], "Monthly")
        self.assertEqual(out["BillingCurrency"], "USD")

    def test_tier2_mapping_produces_transformed_value(self):
        t = MapperDrivenTransformer(MINIMAL_MAPPER, SCHEMA, {})
        out = t.transform_row(SAMPLE_ROW)
        self.assertEqual(out["BillingPeriodStart"], "2026-03-15T00:00:00Z")
        self.assertEqual(out["ChargePeriodEnd"], "2026-03-15T23:59:59Z")

    def test_missing_column_resolves_to_empty_string(self):
        t = MapperDrivenTransformer(MINIMAL_MAPPER, SCHEMA, {})
        out = t.transform_row(SAMPLE_ROW)
        # ConsumedUnit has no mapping in MINIMAL_MAPPER and no default — should be ""
        self.assertEqual(out["ConsumedUnit"], "")

    def test_output_has_all_schema_columns(self):
        t = MapperDrivenTransformer(MINIMAL_MAPPER, SCHEMA, {})
        out = t.transform_row(SAMPLE_ROW)
        for col in SCHEMA:
            self.assertIn(col, out)


class TestTransformRowBehaviours(unittest.TestCase):

    def test_humanize_transform(self):
        t = MapperDrivenTransformer(MINIMAL_MAPPER, SCHEMA, {})
        out = t.transform_row(SAMPLE_ROW)
        self.assertEqual(out["ServiceName"], "Copilot For Business")

    def test_static_value_mapping(self):
        t = MapperDrivenTransformer(MINIMAL_MAPPER, SCHEMA, {})
        out = t.transform_row(SAMPLE_ROW)
        self.assertEqual(out["ProductFamily"], "Developer Tools")

    def test_build_tags_mapping(self):
        t = MapperDrivenTransformer(MINIMAL_MAPPER, SCHEMA, {})
        out = t.transform_row(SAMPLE_ROW)
        tags = json.loads(out["Tags"])
        self.assertEqual(tags["username"], "alice")
        self.assertEqual(tags["organization"], "CoreStack-Engg")

    def test_billing_period_end_next_month(self):
        t = MapperDrivenTransformer(MINIMAL_MAPPER, SCHEMA, {})
        out = t.transform_row(SAMPLE_ROW)
        self.assertEqual(out["BillingPeriodEnd"], "2026-04-01T00:00:00Z")

    def test_cost_passthrough(self):
        t = MapperDrivenTransformer(MINIMAL_MAPPER, SCHEMA, {})
        out = t.transform_row(SAMPLE_ROW)
        self.assertEqual(out["BilledCost"], "19.99")


class TestFallbackSources(unittest.TestCase):

    def test_fallback_used_when_primary_empty(self):
        mapper = {
            "meta": {"tool_name": "t"},
            "defaults": {},
            "mappings": {
                "BilledCost": {
                    "source": "net_amount",
                    "transform": "identity",
                    "fallback_sources": ["gross_amount"],
                    "default_value": "0",
                }
            },
        }
        row = {"net_amount": "", "gross_amount": "50.00"}
        t = MapperDrivenTransformer(mapper, ["BilledCost"], {})
        out = t.transform_row(row)
        self.assertEqual(out["BilledCost"], "50.00")

    def test_default_value_used_when_all_sources_empty(self):
        mapper = {
            "meta": {"tool_name": "t"},
            "defaults": {},
            "mappings": {
                "BilledCost": {
                    "source": "net_amount",
                    "transform": "identity",
                    "fallback_sources": ["gross_amount"],
                    "default_value": "0",
                }
            },
        }
        row = {"net_amount": "", "gross_amount": ""}
        t = MapperDrivenTransformer(mapper, ["BilledCost"], {})
        out = t.transform_row(row)
        self.assertEqual(out["BilledCost"], "0")

    def test_primary_source_used_when_available(self):
        mapper = {
            "meta": {"tool_name": "t"},
            "defaults": {},
            "mappings": {
                "BilledCost": {
                    "source": "net_amount",
                    "transform": "identity",
                    "fallback_sources": ["gross_amount"],
                    "default_value": "0",
                }
            },
        }
        row = {"net_amount": "10.00", "gross_amount": "15.00"}
        t = MapperDrivenTransformer(mapper, ["BilledCost"], {})
        out = t.transform_row(row)
        self.assertEqual(out["BilledCost"], "10.00")


class TestValidateRequiredColumns(unittest.TestCase):

    def _full_mapper(self):
        return {
            "meta": {"tool_name": "t"},
            "defaults": {
                "ChargeCategory": "Usage",
                "ChargeFrequency": "Monthly",
            },
            "mappings": {
                "BillingPeriodStart": {"source": "date", "transform": "to_iso8601_start"},
                "BillingPeriodEnd":   {"source": "date", "transform": "to_billing_period_end"},
                "ChargePeriodStart":  {"source": "date", "transform": "to_iso8601_start"},
                "ChargePeriodEnd":    {"source": "date", "transform": "to_iso8601_end"},
                "BilledCost":         {"source": "cost", "transform": "identity", "default_value": "0"},
                "EffectiveCost":      {"source": "cost", "transform": "identity", "default_value": "0"},
                "ListCost":           {"source": "cost", "transform": "identity", "default_value": "0"},
                "ServiceName":        {"source": "product", "transform": "identity"},
            },
        }

    def _full_cli(self):
        return {
            "ProviderName": "GitHub",
            "BillingAccountId": "acct-123",
            "BillingAccountName": "My Org",
            "BillingCurrency": "USD",
        }

    def test_passes_when_all_required_filled(self):
        t = MapperDrivenTransformer(self._full_mapper(), SCHEMA, self._full_cli())
        row = {"date": "2026-03-01", "cost": "9.99", "product": "Copilot"}
        empty = t.validate_required_columns(row)
        self.assertEqual(empty, [])

    def test_raises_when_required_column_empty(self):
        t = MapperDrivenTransformer(self._full_mapper(), SCHEMA, {})  # no CLI params
        row = {"date": "2026-03-01", "cost": "9.99", "product": "Copilot"}
        with self.assertRaises(ValueError) as ctx:
            t.validate_required_columns(row)
        error_msg = str(ctx.exception)
        # BillingAccountId, BillingAccountName, ProviderName are missing
        self.assertIn("BillingAccountId", error_msg)
        self.assertIn("BillingAccountName", error_msg)

    def test_lists_all_missing_columns_in_error(self):
        empty_mapper = {"meta": {}, "defaults": {}, "mappings": {}}
        t = MapperDrivenTransformer(empty_mapper, SCHEMA, {})
        with self.assertRaises(ValueError) as ctx:
            t.validate_required_columns({})
        error_msg = str(ctx.exception)
        for col in REQUIRED_FOCUS_COLUMNS:
            self.assertIn(col, error_msg)


class TestInjectExtraTag(unittest.TestCase):

    def test_injects_into_empty_tags(self):
        row = {"Tags": "{}"}
        inject_extra_tag(row, "env", "prod")
        tags = json.loads(row["Tags"])
        self.assertEqual(tags["env"], "prod")

    def test_injects_into_existing_tags(self):
        row = {"Tags": '{"username":"alice"}'}
        inject_extra_tag(row, "env", "prod")
        tags = json.loads(row["Tags"])
        self.assertEqual(tags["username"], "alice")
        self.assertEqual(tags["env"], "prod")

    def test_does_nothing_when_tag_key_empty(self):
        row = {"Tags": '{"username":"alice"}'}
        inject_extra_tag(row, "", "prod")
        self.assertEqual(row["Tags"], '{"username":"alice"}')

    def test_overwrites_existing_key(self):
        row = {"Tags": '{"env":"staging"}'}
        inject_extra_tag(row, "env", "prod")
        tags = json.loads(row["Tags"])
        self.assertEqual(tags["env"], "prod")

    def test_handles_missing_tags_column(self):
        row = {}
        inject_extra_tag(row, "env", "prod")
        tags = json.loads(row["Tags"])
        self.assertEqual(tags["env"], "prod")

    def test_handles_malformed_json_gracefully(self):
        row = {"Tags": "not-json"}
        inject_extra_tag(row, "env", "prod")
        tags = json.loads(row["Tags"])
        self.assertEqual(tags["env"], "prod")

    def test_output_is_compact_json(self):
        row = {"Tags": "{}"}
        inject_extra_tag(row, "k", "v")
        self.assertNotIn(" ", row["Tags"])


class TestFirstNonEmptyMapping(unittest.TestCase):
    """Test the first_non_empty transform path in _apply_mapping."""

    def test_first_non_empty_via_mapper(self):
        mapper = {
            "meta": {"tool_name": "t"},
            "defaults": {},
            "mappings": {
                "ResourceId": {
                    "transform": "first_non_empty",
                    "sources": ["empty_col", "username"],
                }
            },
        }
        row = {"empty_col": "", "username": "bob"}
        t = MapperDrivenTransformer(mapper, ["ResourceId"], {})
        out = t.transform_row(row)
        self.assertEqual(out["ResourceId"], "bob")

    def test_first_non_empty_falls_back_to_default(self):
        mapper = {
            "meta": {"tool_name": "t"},
            "defaults": {},
            "mappings": {
                "ResourceId": {
                    "transform": "first_non_empty",
                    "sources": ["missing_a", "missing_b"],
                    "default_value": "unknown",
                }
            },
        }
        t = MapperDrivenTransformer(mapper, ["ResourceId"], {})
        out = t.transform_row({})
        self.assertEqual(out["ResourceId"], "unknown")


if __name__ == "__main__":
    unittest.main()
