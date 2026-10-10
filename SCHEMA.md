# VeriGreen data schema and quality rules

## Bronze: manually collected CSVs (`templates/`)

Each template has one `EXAMPLE` row showing the format. The pipeline drops `EXAMPLE` rows automatically, but delete them once you start filling in real data.

**`emissions_raw.csv`**: one row per company × fiscal year × source.

| Column | Rule |
|---|---|
| `company_id` | yfinance ticker, e.g. `FORTUM.HE` |
| `fiscal_year` | integer year the emissions relate to (not the report's publication year) |
| `scope1`, `scope2_location`, `scope2_market` | numbers exactly as reported; leave blank if not reported (never 0 for "unknown") |
| `unit` | `tCO2e`, `ktCO2e` or `MtCO2e`, as printed in the report |
| `boundary` | `operational_control`, `financial_control` or `equity_share` (usually stated in the methodology section) |
| `source_type` | `sustainability_report`, `annual_report`, `cdp`, `third_party` (aggregator sites; used only when nothing better exists) or `eu_ets` |
| `source_url`, `source_page` | direct link to the PDF and page number; required |
| `retrieved_date` | date you looked it up |
| `notes` | restatements, divestments, anything odd |

Collection rules: enter the most recent reported figure for each year. If a later report restates an earlier year, add the restated value as a new row with a note rather than overwriting. For EU ETS rows, sum verified emissions of the company's installations and fill `scope1` only.

**`ratings_raw.csv`**: one row per company × provider. `rating_scale` is `msci_letter` (CCC–AAA) or `sustainalytics_risk` (0–100, lower is better). Enter `rating_raw` exactly as shown on the provider's site.

**`companies.csv`**: `company_id`, name, `sector`, exchange, currency.

**`financials_raw.csv`**: revenue in EUR millions per fiscal year (needed for intensity checks and PCAF-style estimation).
`revenue_source` (`primary_report` / `yfinance` / `override` / blank if `revenue_eur_m` itself is blank) is written by
`scripts/verify_financials.py`, not hand-entered — it checks every value against the `yfinance_cache/` and fails loudly
on any >2% mismatch whose `notes` don't contain the word "override". Never hand-edit this column; re-run the script.

**`price_anomaly_reviews.csv`**: one row per human-reviewed `check_prices` flag that needed a judgment call
(`company_id`, `date`, `check_id`, `status` — `confirmed_bad_tick` / `unconfirmed` / `real_event` —, `treatment` —
`interpolate` / `drop` / `none` —, `reason`, `reviewed_date`). `check_id = manual` marks a point found by inspection
rather than by a check (Elisa 2025-07-29). Consumed by `verigreen/price_cleaning.py` to build
`prices_cleaned.parquet`; points not listed here pass through unchanged. `unconfirmed` is never auto-treated, no
matter what `treatment` says — see `docs/decisions_log.md`.

**`revenue_boundary_reviews.csv`**: documented exceptions to `carbon_intensity.csv`'s `boundary_match` column
(`company_id`, `fiscal_year`, `boundary_match` — `true` / `false` / `unknown` —, `reason`). Rows not listed default
to `true`; only genuinely unresolved or known mismatches get an explicit row here.

**`financials_yfinance_firstpass.csv`**: the raw, unreconciled yfinance "Total Revenue" pull, kept for audit against
`financials_raw.csv`. Never used directly by any check or the intensity build.

**`emissions_naive_vs_trusted.csv`**: hand-curated, one row per company-year where a documented
naive-pipeline value differs from the trusted figure in `emissions_raw.csv`. Feeds the raw-vs-trusted
optimiser demo. `error_category` is one of `aggregator_error`, `pre_restatement`, `financed_emissions`,
`unit_error` (the original value was wrong because of a unit mistake in the report; the report's own restatement note says so).
`verification_status` is `verified_pdf` (the raw value was read in a PDF in `data/raw_pdfs/`, either in the original report or
quoted in a later report's restatement note; `raw_source` must cite the page) or `from_notes` (the number is not on disk; taken
from `emissions_raw.csv` notes or `docs/verification_log.md`, never derived or invented). Checked by
`verigreen/naive_vs_trusted.py` (every trusted value must equal a row in `emissions_raw.csv`).
`raw_scope1`/`raw_scope2_location`/`raw_scope2_market` hold the naive value when it's a like-for-like
substitute for those fields (wrong source, wrong vintage); `raw_combined_footprint` +
`raw_combined_footprint_label` hold it instead when the naive number is a different metric entirely
(e.g. financed emissions mistaken for own operations) that doesn't map onto a Scope 1/2 split. Every
row must cite a source for the raw value in `raw_source` — see `docs/decisions_log.md` (2026-09-26
entry) for how each row was verified and what was deliberately left out.

## Silver: checks in `verigreen/quality_checks.py`

All checks write to one long-format flags table (`dataset, company_id, fiscal_year, check_id, severity, message, value`).

| ID | Check | Severity |
|---|---|---|
| E01 | Required field missing | error |
| E02 | Unknown unit | error |
| E03 | Negative emissions | error |
| E04 | Duplicate company-year-source rows | warn |
| E05 | Company-reported sources disagree on Scope 1 by >10% | warn |
| E06 | Scope 2 location-based only, or missing | info / warn |
| E07 | No reported Scope 1 for an expected year (imputation target) | info |
| E08 | Scope 1 changes >50% year over year | warn |
| E09 | EU ETS verified emissions exceed reported Scope 1 by >5% | error |
| E10 | Reporting boundary changes across years | warn |
| E12 | Unknown `source_type` | error |
| E11 | Scope 1+2 intensity >10× or <0.1× sector peer median (needs ≥3 peers) | warn |
| R01 | Rating not valid for its scale | error |
| R02 | Rating older than ~18 months | warn |
| R03 | Only one provider covers the company | info |
| R04 | Provider percentile ranks differ by ≥0.40 | warn |
| P01 | Missing or non-positive price | error |
| P02 | Daily return beyond ±25% | warn |
| P03 | Gap of more than 5 business days | warn |
| P04 | Five or more identical closes in a row | warn |

Why these rules matter:

- **E09 is directional.** EU ETS only covers EU installations, so it is normally *below* a company's total Scope 1. Being above it is a real inconsistency.
- **R04 compares ranks, not scores.** MSCI letters and Sustainalytics risk scores are on different scales with opposite directions, so each provider is converted to a percentile rank within the universe (1.0 = best).
- **Financial companies** (Nordea, Sampo) have tiny Scope 1+2 but large financed emissions. The checks treat them like anyone else. Say so explicitly in the pitch.

All thresholds live in the `Thresholds` dataclass so they can be tuned in one place.

## Derived tables

**`data/silver/carbon_intensity.csv`** (`verigreen/carbon_intensity.py`, built by
`scripts/build_carbon_intensity.py`): Scope1+Scope2 per EUR m revenue, market-based and
location-based computed independently (no fallback between methods — blank, never
substituted or divided by zero, when either input is missing). `boundary_match` (`true` /
`false` / `unknown`) flags whether revenue and emissions cover the same organisational
boundary for that company-year, from `revenue_boundary_reviews.csv`; defaults to `true`.
Filter on this column before feeding a company-year to the optimiser.

**`data/bronze/prices_cleaned.parquet`** (`verigreen/price_cleaning.py`, built by
`scripts/build_cleaned_prices.py`): `prices_raw.parquet` plus `adj_close_cleaned`,
`anomaly_status`, `anomaly_reason` from `price_anomaly_reviews.csv`. `prices_raw.parquet`
itself is never modified.

## Running on Databricks

Datasets are tiny, so the same pandas code runs on the driver in a notebook: read bronze Delta tables with `spark.table(...).toPandas()`, run the checks, and write silver plus the flags table back with `spark.createDataFrame(...)`. For the production-path story, the row-level rules (E01–E03, R01, P01) map directly onto Lakeflow expectations (`@dlt.expect_or_drop`, `@dlt.expect`). The cross-row rules (E05, E07–E11, R04) stay in Python.

## Tests

```
python tests/test_quality_checks.py   # or: pytest tests/
```
