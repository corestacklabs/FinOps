Generate a FOCUS/CUR mapper JSON for a SaaS usage CSV, then optionally run the full transform pipeline.

**Usage:** `/generate-mapper` or `/generate-mapper path/to/usage_report.csv`

---

## Path Map (auto-resolved defaults from workspace root)

| File | Default path |
|------|-------------|
| usage_report.csv | `usage_report.csv` |
| saas_template.csv | `saas_template.csv` |
| focus_cur_output.csv | `focus_cur_output.csv` |
| mapper output | `saas_to_focus_formatter/mappers/<tool_name>_mapper.json` |

---

## Step 1 — Find the usage CSV

- If a path was given in `$ARGUMENTS`, use it
- Otherwise default to `usage_report.csv` in the workspace root
- Read all column headers + first 5 data rows

---

## Step 2 — Infer tool metadata

**tool_name:** Check the `product` / `tool` / `service` column value in row 1; strip suffixes (`_for_business`, version numbers); fallback to the filename stem with date/noise stripped.

**ProductFamily** lookup:

| Keyword in tool_name | ProductFamily |
|----------------------|---------------|
| copilot, github | Developer Tools |
| claude, anthropic | AI / Machine Learning |
| openai, gpt, gemini | AI / Machine Learning |
| datadog, newrelic, splunk | Observability |
| slack, zoom, teams, confluence | Collaboration |
| jira, asana, monday | Project Management |
| snowflake, databricks, bigquery | Data & Analytics |
| salesforce, hubspot | CRM |
| okta, crowdstrike, pagerduty | Identity & Security |
| *(no match)* | SaaS |

---

## Step 3 — Map source columns → FOCUS columns (semantic scoring)

For each FOCUS column below, score every source column using substring matching (case-insensitive). Pick the highest-scoring match. Ties → prefer longer/more-specific pattern.

| FOCUS Column | Patterns (score descending) | Transform |
|---|---|---|
| BillingPeriodStart | billing_period_start(10), billing_start(9), period_start(8), start_date(7), usage_date(6), date(5), day(4), timestamp(3) | `to_iso8601_start` |
| BillingPeriodEnd | billing_period_end(10), billing_end(9), period_end(8), end_date(7), usage_date(5), date(4), day(3) | `to_billing_period_end` |
| ChargePeriodStart | charge_period_start(10), charge_start(9), period_start(8), start_date(7), usage_date(6), date(5), day(4) | `to_iso8601_start` |
| ChargePeriodEnd | charge_period_end(10), charge_end(9), period_end(8), end_date(7), usage_date(6), date(5), day(4) | `to_iso8601_end` |
| BilledCost | net_amount(10), billed_cost(9), invoice_amount(8), charged_amount(8), amount_due(7), total_cost(6), cost_usd(5), cost(4), amount(3) | `identity` + fallback_sources + default_value:"0" |
| EffectiveCost | net_amount(10), effective_cost(9), amortized_cost(8), billed_cost(7), total_cost(5), cost(3) | `identity` + fallback_sources + default_value:"0" |
| ListCost | gross_amount(10), list_cost(9), list_price(9), retail_cost(8), undiscounted_cost(8), total_cost(5), cost(2) | `identity` + fallback_sources + default_value:"0" |
| ServiceName | service_name(10), service(9), product_name(9), product(8), tool_name(8), tool(7), offering(6), application(5) | `humanize` |
| SkuId | sku_id(10), sku(9), product_id(8), plan_id(7), tier_id(7), plan(6), tier(5) | `identity` |
| UsageType | usage_type(10), charge_type(9), line_item_type(8), type(6), sku(5), plan(4) | `humanize` |
| ConsumedQuantity | consumed_quantity(10), usage_quantity(9), quantity(8), qty(8), total_tokens(7), tokens(7), requests(6), api_calls(6), seats(6), count(5) | `identity` |
| ConsumedUnit | consumed_unit(10), unit_type(9), unit(8), measure(7), uom(5) | `identity` + default inferred from tool_name |
| ResourceId | resource_id(10), instance_id(9), account_id(8), workspace_id(7), project_id(7), username(5), user(4) | `identity` |
| ResourceName | resource_name(10), workspace_name(8), project_name(8), host_name(7), organization(6), username(5), user(4) | `identity` |
| RegionName | region_name(10), region(9), location(8), availability_zone(7), zone(4), site(3) | `identity` |
| ProductFamily | *(always static — from Step 2)* | `static` |
| Tags | *(always build_tags — from Step 4)* | `build_tags` |

**ConsumedUnit default** (when no source col found):
- claude/gpt/gemini/llm/ai → `"Tokens"`
- copilot/jira/slack/github → `"Seats"`
- datadog/newrelic/splunk  → `"Events"`
- snowflake/databricks     → `"Credits"`
- *(default)*              → `"Units"`

---

## Step 4 — Detect tag sources

Tag sources = every source column whose name **contains** any of:
`username`, `user`, `email`, `org`, `organization`, `team`, `department`, `project`, `repository`, `repo`, `workflow`, `environment`, `env`, `cost_center`, `budget`, `label`, `tag`

Build as `build_tags` mapping:
```json
"Tags": {
  "transform": "build_tags",
  "tag_sources": ["username", "organization", ...]
}
```

If no tag columns found, use: `{ "transform": "static", "static_value": "{}" }`

---

## Step 5 — Write the mapper JSON

**Output path:** `saas_to_focus_formatter/mappers/<tool_name>_mapper.json`

```json
{
  "meta": {
    "tool_name": "<tool_name>",
    "generated_at": "<current ISO8601 timestamp>",
    "source_columns": ["<col1>", "<col2>", "..."],
    "focus_version": "1.0",
    "generator": "Claude Code /generate-mapper"
  },
  "defaults": {
    "ChargeCategory":  "Usage",
    "ChargeFrequency": "Monthly",
    "BillingCurrency": "USD",
    "ProviderName":    "<inferred from tool_name or ask user>"
  },
  "mappings": {
    "<FocusColumn>": { "source": "<source_col>", "transform": "<fn>" },
    "BilledCost":    { "source": "<col>", "transform": "identity", "fallback_sources": ["<col2>"], "default_value": "0" },
    "Tags":          { "transform": "build_tags", "tag_sources": ["<col1>", "<col2>"] },
    "ProductFamily": { "transform": "static", "static_value": "<family>" }
  }
}
```

---

## Step 6 — Confirm and optionally run transform

After writing the mapper, display:
1. The mapper file path
2. A table showing each FOCUS column → source column mapping

Then ask the user:
> "Mapper saved to `saas_to_focus_formatter/mappers/<tool_name>_mapper.json`.
> Run the full transform now? (I'll need your `--billing_account_id` and `--billing_account_name`.)"

If user confirms, collect missing values and run:
```bash
cd saas_to_focus_formatter && python3 main.py transform \
    --usage_report         ../usage_report.csv \
    --mapper               mappers/<tool_name>_mapper.json \
    --cur_template         ../saas_template.csv \
    --output               ../focus_cur_output.csv \
    --provider_name        "<ProviderName>" \
    --billing_account_id   "<billing_account_id>" \
    --billing_account_name "<billing_account_name>" \
    --billing_currency     USD
```

Output will be written to `focus_cur_output.csv` in the workspace root.

---

## Reference

For full mapper format documentation, transform function catalogue, and additional vendor examples, see:
`SKILL_saas_to_cur_converter.md` in the workspace root.
