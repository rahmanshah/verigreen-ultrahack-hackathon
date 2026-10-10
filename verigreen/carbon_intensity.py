"""Carbon intensity: Scope 1 + Scope 2 tonnes per EUR million revenue.

Builds on the silver table from `quality_checks.check_emissions` (already unit-converted
to tonnes, one preferred source per company-year) and `financials_raw.csv`-shaped revenue
data. Computes two variants, market-based and location-based Scope 2, independently --
there is no fallback between methods here, unlike `check_emissions`' combined `scope12_t`
column (which prefers market-based and falls back to location-based).
"""
from __future__ import annotations

import pandas as pd

from verigreen.quality_checks import drop_examples

INTENSITY_COLS = [
    "company_id", "company_name", "fiscal_year", "revenue_eur_m",
    "scope1_t", "scope2_market_t", "scope2_location_t",
    "intensity_market_tco2e_per_eurm", "intensity_location_tco2e_per_eurm",
    "boundary", "boundary_match", "revenue_source", "notes",
]
VALID_BOUNDARY_MATCH = {"true", "false", "unknown"}


def build_carbon_intensity(emissions_silver: pd.DataFrame, financials: pd.DataFrame,
                           boundary_reviews: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per company-year present in `emissions_silver`, with revenue joined in.

    A value is left blank (NaN) -- never substituted, never divided by zero -- when:
    - the relevant Scope 2 method (market or location) is missing for that company-year;
    - revenue is missing, zero, or negative for that company-year.

    `emissions_silver`: output of `quality_checks.check_emissions` (needs company_id,
    company_name, fiscal_year, scope1_t, scope2_market_t, scope2_location_t, boundary).
    `financials`: `financials_raw.csv`-shaped (company_id, fiscal_year, revenue_eur_m,
    source_url); EXAMPLE rows are dropped automatically.

    `boundary_match` records whether revenue and the emissions figures cover the same
    organisational boundary for that company-year -- 'true', 'false', or 'unknown'. It
    defaults to 'true' (no known mismatch) and is overridden by `boundary_reviews`
    (company_id, fiscal_year, boundary_match, reason), e.g. `revenue_boundary_reviews.csv`
    -- a specific, documented exception, never an inferred guess. The optimiser can filter
    on this column to exclude company-years with an unresolved or known boundary mismatch.
    """
    fin = (drop_examples(financials)[["company_id", "fiscal_year", "revenue_eur_m", "source_url"]]
           .rename(columns={"source_url": "revenue_source"}))
    d = emissions_silver.merge(fin, on=["company_id", "fiscal_year"], how="left")

    revenue_ok = d["revenue_eur_m"].notna() & (d["revenue_eur_m"] > 0)
    safe_revenue = d["revenue_eur_m"].where(revenue_ok)

    d["intensity_market_tco2e_per_eurm"] = (d["scope1_t"] + d["scope2_market_t"]) / safe_revenue
    d["intensity_location_tco2e_per_eurm"] = (d["scope1_t"] + d["scope2_location_t"]) / safe_revenue

    d["notes"] = ""
    stora_enso = d["company_id"] == "STERV.HE"
    d.loc[stora_enso, "notes"] = (
        "Uses operational-control (GHG Protocol) boundary rows, selected by check_emissions' "
        "source-type preference; financial-control (ESRS) rows for the same years exist in "
        "emissions_raw.csv but are not used or substituted here."
    )

    d["boundary_match"] = "true"
    if boundary_reviews is not None and not boundary_reviews.empty:
        bad = set(boundary_reviews["boundary_match"]) - VALID_BOUNDARY_MATCH
        if bad:
            raise ValueError(f"unknown boundary_match value: {bad}")
        for _, row in boundary_reviews.iterrows():
            mask = (d["company_id"] == row["company_id"]) & (d["fiscal_year"] == row["fiscal_year"])
            d.loc[mask, "boundary_match"] = row["boundary_match"]
            d.loc[mask, "notes"] = (d.loc[mask, "notes"] + " " + row["reason"]).str.strip()

    return d[INTENSITY_COLS].sort_values(["company_id", "fiscal_year"]).reset_index(drop=True)
