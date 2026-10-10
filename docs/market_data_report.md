# Market data report

Generated 2026-10-02, updated same day with a follow-up pass (KONE price anomaly investigation,
`boundary_match` column, automated revenue verification). Covers next-steps priorities 1-2 from
the internal project notes: revenue, prices, and carbon intensity. No QUBO or quantum work is included here
(out of scope for this pass).

**Reproduce the derived tables** (deterministic, no network access; re-run any time
`data/bronze/emissions_raw.csv`, `financials_raw.csv`, or the review CSVs change):

```
uv run python scripts/build_carbon_intensity.py
uv run python scripts/build_cleaned_prices.py
```

**Refresh market data from Yahoo** (network access; cached under
`data/bronze/yfinance_cache/`, which is git-ignored — reruns don't refetch unless `--refresh`
is passed):

```
uv run python scripts/fetch_market_data.py [--refresh]
```

**Verify revenue against the yfinance cache** (no network access, reads the cache; fails
loudly on any undocumented >2% mismatch, otherwise writes `revenue_source` into
`financials_raw.csv`):

```
uv run python scripts/verify_financials.py
```

## 1. Ticker verification

All 15 tickers verified: correct company name returned, currency EUR, ~5 years of daily
history, no gap over the 5-business-day flag threshold.

| Ticker | Verified | Name returned | Currency | First date | Last date | Rows | Max gap (bdays) |
|---|---|---|---|---|---|---|---|
| NESTE.HE | yes | Neste Oyj | EUR | 2021-10-04 | 2026-10-02 | 1256 | 4 |
| FORTUM.HE | yes | Fortum Oyj | EUR | 2021-10-04 | 2026-10-02 | 1256 | 4 |
| OUT1V.HE | yes | Outokumpu Oyj | EUR | 2021-10-04 | 2026-10-02 | 1256 | 4 |
| STERV.HE | yes | Stora Enso Oyj | EUR | 2021-10-04 | 2026-10-02 | 1256 | 4 |
| UPM.HE | yes | UPM-Kymmene Oyj | EUR | 2021-10-04 | 2026-10-02 | 1256 | 4 |
| KEMIRA.HE | yes | Kemira Oyj | EUR | 2021-10-04 | 2026-10-02 | 1256 | 4 |
| WRT1V.HE | yes | Wärtsilä Oyj Abp | EUR | 2021-10-04 | 2026-10-02 | 1256 | 4 |
| METSO.HE | yes | Metso Oyj | EUR | 2021-10-04 | 2026-10-02 | 1256 | 4 |
| KESKOB.HE | yes | Kesko Oyj | EUR | 2021-10-04 | 2026-10-02 | 1256 | 4 |
| KNEBV.HE | yes | KONE Oyj | EUR | 2021-10-04 | 2026-10-02 | 1256 | 4 |
| NOKIA.HE | yes | Nokia Oyj | EUR | 2021-10-04 | 2026-10-02 | 1256 | 4 |
| ELISA.HE | yes | Elisa Oyj | EUR | 2021-10-04 | 2026-10-02 | 1256 | 4 |
| ORNBV.HE | yes | Orion Oyj | EUR | 2021-10-04 | 2026-10-02 | 1256 | 4 |
| NDA-FI.HE | yes | Nordea Bank Abp | EUR | 2021-10-04 | 2026-10-02 | 1256 | 4 |
| SAMPO.HE | yes | Sampo Oyj | EUR | 2021-10-04 | 2026-10-02 | 1256 | 4 |

The identical 4-business-day max gap across every ticker is a shared Nasdaq Helsinki
non-trading day somewhere in the 5-year window (a market-wide holiday), not a per-company
data problem — none exceed the 5-day flag threshold, so `check_prices` raised no P03 flags.

Note: "Wärtsilä" prints with replacement characters (`W�rtsil�`) in this terminal/report
rendering, but the underlying cached JSON stores it correctly as proper UTF-8
(`Wärtsilä Oyj Abp`) — a display artifact only, not a data error.

## 2. `check_prices` flags

Only **one flag** across all 15 tickers × ~5 years of daily data:

| Check | Company | Detail |
|---|---|---|
| P02 (daily return >25%) | KNEBV.HE (KONE) | +30% on 2025-07-29 (54.02 → 70.00), then back to 53.12 the next day. |

No P01 (missing/non-positive), P03 (>5-day gap), or P04 (stale run) flags anywhere.

### KONE anomaly: second-source investigation (follow-up, same day)

Tried to independently confirm this was a bad tick rather than a real price move:

- **No stock split or dividend** recorded in the price series on or around that date.
- **Not an earnings reaction**: KONE's Q2 2025 results were released 2025-07-18, 11 days
  before the anomaly (confirmed via web search).
- **No news found** of a trading halt, price correction, or corporate action on that date.
- **Immediate full reversion** the next trading day (53.12, back in the pre-spike range) — the
  classic signature of a single bad print, not a sustained repricing.
- **Could NOT obtain an independent second source's exact closing price** for 2025-07-29
  specifically: Stooq's and Nasdaq Nordic's data-export endpoints returned 404/non-data
  responses from this environment, and other sites (stockanalysis.com, investing.com) only
  expose a rolling recent-data window via static fetch, with no way to query a specific past
  date without interactive JavaScript.

**Conclusion: strong circumstantial evidence of a Yahoo Finance data error, but not
independently confirmed.** Per instruction, this was **not treated** — `prices_raw.parquet`
is untouched, and the new cleaned series (below) leaves this point's value exactly as
reported, flagged `unconfirmed`. Revisit if a second source becomes reachable.

### Cleaned price series (follow-up)

`data/bronze/prices_cleaned.parquet` (git-ignored, same as `prices_raw.parquet` — built by
`scripts/build_cleaned_prices.py`) adds `adj_close_cleaned`, `anomaly_status`, and
`anomaly_reason` columns, driven entirely by `data/bronze/price_anomaly_reviews.csv` (a
human-reviewed table, committed). Only rows explicitly marked `confirmed_bad_tick` with a
`treatment` other than `none` get a different `adj_close_cleaned` value; everything else
(including the KONE point above, marked `unconfirmed`) passes through unchanged but flagged.
Currently 1 of 18,840 rows is flagged, 0 are treated.

## 3. Revenue

### Source per company-year

Full detail and reasoning for every row is in `data/bronze/financials_raw.csv`'s `notes`
column; summary:

- **11 companies** (Neste*, Outokumpu, Stora Enso, UPM, Wärtsilä, Kesko, KONE, Elisa, Orion,
  plus most years of Fortum/Nokia): yfinance `Ticker.income_stmt` "Total Revenue", first pass,
  not independently verified beyond the spot-checks below. (*Neste's 2025 value was
  spot-checked and matched exactly; 2023/2024 use the same yfinance field, unverified.)
- **Kemira** (all 3 years): primary source, Kemira Annual Report 2025 p.51 "Revenue" —
  Kemira's own as-reported figure, which still includes Oil & Gas revenue through its actual
  divestment date (2 Feb 2024), matching the emissions boundary.
- **Metso** (all 3 years): primary source, Metso Annual Reports 2023 & 2025, consolidated
  "Sales" line — continuing-operations basis (Metals & Chemical Processing and Ferrous & Heat
  Transfer discontinued from Sep 2023).
- **Fortum** 2024/2025: primary source, `Fortum-Financials2025.pdf` consolidated "Sales" —
  continuing operations, excludes the recycling & waste business (divested Nov 2024). Fortum's
  own report ties this exact figure to its GHG-intensity calculation. Fortum 2023: yfinance,
  unverified (see §5, unresolved).
- **Nokia** 2024/2025: primary source, Nokia Annual Report 2025 "Net sales" — continuing
  operations (excludes Submarine Networks, discontinued June 2024; includes Infinera from
  2025). Nokia 2023: primary source **overriding** yfinance — Nokia Annual Report 2023 p.77,
  "Net sales in 2023 were EUR 22,258 million" (see mismatch table below).
- **Nordea** (all 3 years): primary source, "Total operating income" from Nordea Annual
  Report 2025 p.136 — **overriding** yfinance's generic "Total Revenue" per your approved
  decision. Nordea's own report states this exact figure is the denominator for its own GHG
  intensity metric.
- **Sampo** 2024/2025: primary source, "Insurance revenue" (Group IFRS statement of profit and
  other comprehensive income, p.138) — **overriding** yfinance. Sampo 2023: **blank**, not
  invented (see §5, unresolved).

### Automated verification (follow-up): `revenue_source` column

`scripts/verify_financials.py` now checks every `revenue_eur_m` in `financials_raw.csv`
against the cached yfinance `Total Revenue` for that company-year and writes a
`revenue_source` column: `yfinance` (28 rows — unverified first pass), `primary_report`
(14 rows — a primary source that agrees with yfinance within 2%), `override` (2 rows — Nokia
2023 and Sampo 2024, where the primary source deliberately disagrees by more than 2% and
`notes` documents why), and blank (1 row — Sampo 2023, no revenue at all). The script **fails
loudly** (non-zero exit, no file written) if any primary-sourced row disagrees with yfinance
by more than 2% without the word "override" in its notes — this makes an undocumented
mismatch a hard stop, not a silent gap.

### Spot-checks (7 companies, exceeding the required 5 — includes Kemira and Metso, two of the
four portfolio-change companies, plus Nordea and Sampo)

| Company | Year | yfinance value (EUR m) | Report value (EUR m) | Diff | Note |
|---|---|---|---|---|---|
| Neste | 2025 | 19,016.0 | 19,016.0 | 0.0% | Exact match |
| Fortum | 2024 | 5,800.0 | 5,800.0 | 0.0% | Exact match |
| Fortum | 2025 | 4,989.0 | 4,989.0 | 0.0% | Exact match |
| Kemira | 2023 | 3,383.7 | 3,383.7 | 0.0% | Exact match |
| Kemira | 2024 | 2,948.1 | 2,948.1 | 0.0% | Exact match |
| Kemira | 2025 | 2,753.5 | 2,753.5 | 0.0% | Exact match |
| Metso | 2023 | 5,390.0 | 5,390.0 | 0.0% | Exact match |
| Metso | 2024 | 5,026.0 | 5,026.0 | 0.0% | Exact match |
| Metso | 2025 | 5,240.0 | 5,240.0 | 0.0% | Exact match |
| Nokia | 2023 | 21,138.0 | 22,258.0 | **5.0%** | **>2% mismatch.** yfinance backfills to Nokia's current continuing-operations classification (excludes Submarine Networks' EUR 1,120m); report figure used instead to match the emissions boundary (see §5) |
| Nokia | 2024 | 19,220.0 | 19,220.0 | 0.0% | Exact match |
| Nokia | 2025 | 19,889.0 | 19,889.0 | 0.0% | Exact match |
| Nordea | 2023 | 11,737.0 | 11,742.0 | 0.0% | Different metrics (generic Total Revenue vs. Total operating income), coincidentally close |
| Nordea | 2024 | 12,039.0 | 12,100.0 | 0.5% | Different metrics, close |
| Nordea | 2025 | 11,719.0 | 11,743.0 | 0.2% | Different metrics, close |
| Sampo | 2024 | 9,203.0 | 9,450.0 | **2.6%** | **>2% mismatch.** Different metrics: yfinance's generic Total Revenue vs. Sampo's own "Insurance revenue" (IFRS 17); report figure used |
| Sampo | 2025 | 10,322.0 | 10,272.0 | 0.5% | Different metrics, coincidentally close this year |

Two spot-checks exceed the 2% mismatch threshold (Nokia 2023, Sampo 2024) — both are
explained by a deliberate, documented metric/boundary choice (continuing-vs-total operations,
and IFRS 17 "Insurance revenue" vs. Yahoo's generic "Total Revenue"), not a data error. The
report's figure was used in both cases.

## 4. Carbon intensity (`data/silver/carbon_intensity.csv`)

tCO2e per EUR million revenue, Scope 1 + Scope 2, computed separately for market-based and
location-based Scope 2 (no fallback between methods — see `verigreen/carbon_intensity.py`).
Blank means the value could not be computed (missing Scope 2 method or missing revenue), not
zero.

**`boundary_match` column (follow-up)**: records whether revenue and emissions cover the same
organisational boundary, from `data/bronze/revenue_boundary_reviews.csv`. Defaults to `true`
(42 of 45 rows); `unknown` for exactly the three genuinely unresolved company-years —
**Fortum 2023**, **Metso 2023**, and **Sampo 2023** (the last has no revenue at all, so no
comparison is possible). **Nokia 2023 is `true`**, not `unknown` or `false`: the override
above (using the as-originally-reported EUR 22,258m instead of yfinance) was specifically
chosen to make it match. The optimiser should filter on this column rather than assume every
row is comparable. Not shown in the table below (would make it too wide) — see the CSV
directly or §5.

| Company | Year | Revenue (EURm) | Market-based | Location-based |
|---|---|---|---|---|
| ELISA.HE | 2023 | 2,180.5 | 2.60 | 30.79 |
| ELISA.HE | 2024 | 2,191.5 | 1.08 | 20.51 |
| ELISA.HE | 2025 | 2,257.1 | 0.86 | 16.22 |
| FORTUM.HE | 2023 | 6,711.0 | 250.41 | 252.29 |
| FORTUM.HE | 2024 | 5,800.0 | 237.16 | 240.98 |
| FORTUM.HE | 2025 | 4,989.0 | 178.07 | 187.85 |
| KEMIRA.HE | 2023 | 3,383.7 | 197.00 | 219.13 |
| KEMIRA.HE | 2024 | 2,948.1 | 202.27 | 252.67 |
| KEMIRA.HE | 2025 | 2,753.5 | 184.94 | 210.15 |
| KESKOB.HE | 2023 | 11,783.8 | 6.61 | *(blank — open gap)* |
| KESKOB.HE | 2024 | 11,920.1 | 7.65 | 8.63 |
| KESKOB.HE | 2025 | 12,474.7 | 5.95 | 7.21 |
| KNEBV.HE | 2023 | 10,952.3 | 10.86 | 13.33 |
| KNEBV.HE | 2024 | 11,098.4 | 10.65 | 13.09 |
| KNEBV.HE | 2025 | 11,245.2 | 9.90 | 12.45 |
| METSO.HE | 2023 | 5,390.0 | 5.97 | 19.48 |
| METSO.HE | 2024 | 5,026.0 | 7.49 | 22.09 |
| METSO.HE | 2025 | 5,240.0 | 7.28 | 23.09 |
| NDA-FI.HE | 2023 | 11,742.0 | 0.36 | 0.64 |
| NDA-FI.HE | 2024 | 12,100.0 | 1.52 | 1.54 |
| NDA-FI.HE | 2025 | 11,743.0 | 1.18 | 1.25 |
| NESTE.HE | 2023 | 22,927.0 | 120.12 | 121.87 |
| NESTE.HE | 2024 | 20,635.0 | 130.02 | 133.75 |
| NESTE.HE | 2025 | 19,016.0 | 162.02 | 164.86 |
| NOKIA.HE | 2023 | 22,258.0 | 8.80 | *(blank — not reported)* |
| NOKIA.HE | 2024 | 19,220.0 | 4.71 | 18.33 |
| NOKIA.HE | 2025 | 19,889.0 | 2.85 | 18.26 |
| ORNBV.HE | 2023 | 1,189.6 | 11.72 | 14.49 |
| ORNBV.HE | 2024 | 1,542.4 | 7.10 | 10.94 |
| ORNBV.HE | 2025 | 1,889.5 | 5.07 | 6.24 |
| OUT1V.HE | 2023 | 6,961.0 | 165.91 | 211.25 |
| OUT1V.HE | 2024 | 5,942.0 | 228.10 | 242.21 |
| OUT1V.HE | 2025 | 5,468.0 | 256.24 | 267.63 |
| SAMPO.HE | 2023 | *(blank — revenue unresolved)* | *(blank)* | *(blank)* |
| SAMPO.HE | 2024 | 9,450.0 | 0.54 | 0.42 |
| SAMPO.HE | 2025 | 10,272.0 | 0.29 | 0.34 |
| STERV.HE | 2023 | 9,396.0 | 162.84 | *(blank — operational-control rows have no location-based value)* |
| STERV.HE | 2024 | 9,049.0 | 137.03 | *(blank)* |
| STERV.HE | 2025 | 9,326.0 | 110.44 | *(blank)* |
| UPM.HE | 2023 | 10,460.0 | 355.64 | 369.02 |
| UPM.HE | 2024 | 10,339.0 | 326.92 | 369.47 |
| UPM.HE | 2025 | 9,656.0 | 297.22 | 374.90 |
| WRT1V.HE | 2023 | 6,015.0 | 9.31 | 10.35 |
| WRT1V.HE | 2024 | 6,449.0 | 7.73 | 8.83 |
| WRT1V.HE | 2025 | 6,914.0 | 6.77 | 8.53 |

Stora Enso uses the operational-control (GHG Protocol) emissions rows throughout, per
`check_emissions`' source-type preference — the financial-control (ESRS) rows for the same
years exist in `emissions_raw.csv` but are not used or substituted (see note column in the
CSV). This is why Stora Enso's location-based intensity is blank for all three years: the
operational-control table simply doesn't report a location-based Scope 2 figure.

**Nordea and Sampo's intensities are not comparable with the industrial/materials companies
above.** Both are financial companies whose own Scope 1+2 covers only their own operations
(offices, company cars, data centres) — their actual climate-relevant exposure is financed
emissions (Scope 3, category 15: investments and lending), which is 1,000-1,400x larger and
excluded from this table by design (per the the internal project notes data rule "never use financed
emissions for financial companies' own Scope 1/2"). An intensity of ~0.3-1.5 tCO2e/EURm for
Sampo/Nordea next to ~100-350 for Neste/Fortum/UPM does not mean banks and insurers are
"cleaner" — it means this metric doesn't capture what makes their footprint large. Don't rank
companies across sectors on this column without that caveat attached.

## 5. Unresolved, assumed, or needing a human check

- **Sampo 2023 revenue is blank** (`boundary_match=unknown`, since there's nothing to compare).
  No primary-source "Insurance revenue" figure for 2023 is available in `data/raw_pdfs` (the
  2025 board report only shows 2024/2025 comparatives; the 2023 sustainability report doesn't
  contain full P&L financials). yfinance's generic "Total Revenue" (EUR 8,511m) is a different,
  much larger concept than "Insurance revenue" and using it would fabricate a false intensity
  jump between 2023 and 2024. Needs Sampo's actual 2023 or 2024 Annual Report (board/financial
  statements) to fill in properly.
- **Fortum 2023 revenue (EUR 6,711m, yfinance) is unverified** (`boundary_match=unknown`), and
  it's not confirmed whether it's on the same continuing-operations boundary (excl. recycling &
  waste, divested Nov 2024) as `emissions_raw.csv`'s Fortum 2023 Scope1/2 row, which already
  excludes that business per its own note. If the revenue figure is on the old (pre-exclusion)
  boundary, Fortum's 2023 intensity would be understated relative to 2024/2025. Treat with
  caution.
- **Metso 2023's continuing-operations revenue boundary may not match its emissions boundary**
  (`boundary_match=unknown`). Metso's 2023/2024/2025 revenue is confirmed continuing-operations
  (excludes businesses discontinued Sep 2023 and a further one in 2025). `emissions_raw.csv`'s
  Metso 2022/2023 Scope1/2 figures come from a separate GRI supplement document, not these
  financial statements, and it's unconfirmed whether that supplement uses the same
  discontinued-operations boundary. **Metso 2024/2025 are marked `boundary_match=true`**
  instead: both their revenue and emissions come from the same current document (Metso Annual
  Report 2025), making a boundary mismatch far less likely — a reasoned distinction, not a
  blanket assumption across all three years. Needs a human to check the GRI supplement's own
  scope description if more certainty is wanted for 2023.
- **The known emissions-data open gaps are reflected correctly, not patched over**: Kesko,
  Nokia, and Sampo all have a blank location-based Scope 2 for 2023 (per the internal project notes'
  documented open gap), and Stora Enso has no location-based figure in any year on the boundary
  used. None of these were filled in or estimated.
- **The KONE P02 price flag (2025-07-29, +30%/-24% round trip) has strong circumstantial
  evidence of a bad tick but is not independently confirmed** — see the dedicated
  investigation in §2. Left untreated in `prices_cleaned.parquet`, flagged `unconfirmed`.
- **Ticker verification, price download, and the first-pass revenue pull all depend on live
  Yahoo Finance data**, which can and does change (restatements, backfills — as seen directly
  with Nokia's 2023 figure). Re-running `scripts/fetch_market_data.py --refresh` today could
  return different numbers than this report; the committed `financials_raw.csv` is the
  reconciled, intentionally-frozen source of truth, not the first-pass file.
- **No secrets in any committed file.** `prices_raw.parquet`, `prices_cleaned.parquet`, and
  `data/bronze/yfinance_cache/` are git-ignored (Yahoo terms + no reason to commit regenerable
  data); nothing else in this pass touches `.env` or API tokens.
