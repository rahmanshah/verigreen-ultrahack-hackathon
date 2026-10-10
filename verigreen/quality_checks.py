"""VeriGreen data-quality checks: bronze (raw CSVs) -> silver (clean tables + flags).

Plain pandas so the same code runs in a Databricks notebook (data is tiny, so
driver-side pandas is fine) and locally for the Streamlit demo and tests.

Every check appends rows to a long-format flags table:
    dataset | company_id | fiscal_year | check_id | severity | message | value
Severities: "error" (value unusable as-is), "warn" (plausible but suspicious),
"info" (worth knowing, e.g. a gap that imputation will fill).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

UNIT_TO_TONNES = {"tCO2e": 1.0, "ktCO2e": 1_000.0, "MtCO2e": 1_000_000.0}
EMISSION_COLS = ["scope1", "scope2_location", "scope2_market"]
# Sources in order of preference when several exist for a company-year. "third_party"
# (aggregators such as data vendors or scraped profiles) is only used when nothing better exists.
PRIMARY_SOURCES = ["sustainability_report", "annual_report", "cdp", "third_party"]
REGULATORY_SOURCES = ["eu_ets"]
MSCI_SCALE = ["CCC", "B", "BB", "BBB", "A", "AA", "AAA"]
FLAG_COLS = ["dataset", "company_id", "fiscal_year", "check_id", "severity", "message", "value"]


@dataclass(frozen=True)
class Thresholds:
    yoy_jump: float = 0.5            # |YoY change| in Scope 1 above this -> warn
    source_disagreement: float = 0.10  # two company-reported sources differ by more -> warn
    ets_tolerance: float = 0.05      # EU ETS may exceed reported Scope 1 by at most this
    intensity_ratio: float = 10.0    # intensity >10x or <1/10 of sector median -> warn
    min_sector_peers: int = 3        # need this many companies in a sector for the intensity check
    rating_max_age_days: int = 548   # ~18 months
    rating_conflict: float = 0.40    # percentile-rank gap between providers -> warn
    price_spike: float = 0.25        # |daily return| above this -> warn
    price_gap_bdays: int = 5         # more business days than this between rows -> warn
    stale_run: int = 5               # identical closes in a row -> warn


class Flags:
    def __init__(self) -> None:
        self._rows: list[dict] = []

    def add(self, dataset, company_id, fiscal_year, check_id, severity, message, value=None):
        self._rows.append(dict(zip(FLAG_COLS, [dataset, company_id, fiscal_year,
                                               check_id, severity, message, value])))

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self._rows, columns=FLAG_COLS)


def drop_examples(df: pd.DataFrame) -> pd.DataFrame:
    """Remove the template's EXAMPLE rows so they never reach silver."""
    return df[df["company_id"].astype(str).str.upper() != "EXAMPLE"].copy()


# --------------------------------------------------------------------------- emissions

def check_emissions(raw: pd.DataFrame, expected_years: list[int],
                    t: Thresholds = Thresholds()) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validate raw emissions rows.

    Returns (silver, flags). Silver has one row per company-year from the preferred
    company-reported source, values in tonnes CO2e, plus scope12_t (Scope 1 + Scope 2,
    market-based where available, else location-based) and scope2_method.
    """
    f = Flags()
    df = drop_examples(raw)
    df["unit"] = df["unit"].astype(str).str.strip()
    df["source_type"] = df["source_type"].astype(str).str.strip().str.lower()

    # E01 required fields
    for col in ["company_id", "fiscal_year", "unit", "source_type", "source_url"]:
        for _, r in df[df[col].isna() | (df[col].astype(str).str.strip() == "")].iterrows():
            f.add("emissions", r["company_id"], r["fiscal_year"], "E01", "error",
                  f"missing required field '{col}'")

    # E12 unknown source type (rows would otherwise be silently ignored)
    for _, r in df[~df["source_type"].isin(PRIMARY_SOURCES + REGULATORY_SOURCES)].iterrows():
        f.add("emissions", r["company_id"], r["fiscal_year"], "E12", "error",
              "unknown source_type", r["source_type"])

    # E02 unit valid -> convert to tonnes
    bad_unit = ~df["unit"].isin(UNIT_TO_TONNES)
    for _, r in df[bad_unit].iterrows():
        f.add("emissions", r["company_id"], r["fiscal_year"], "E02", "error",
              "unknown unit", r["unit"])
    factor = df["unit"].map(UNIT_TO_TONNES)
    for c in EMISSION_COLS:
        df[f"{c}_t"] = pd.to_numeric(df[c], errors="coerce") * factor

    # E03 negative values
    for c in EMISSION_COLS:
        for _, r in df[df[f"{c}_t"] < 0].iterrows():
            f.add("emissions", r["company_id"], r["fiscal_year"], "E03", "error",
                  f"negative {c}", r[c])

    # E04 duplicates on company-year-source
    dup = df.duplicated(["company_id", "fiscal_year", "source_type"], keep=False)
    for (cid, yr, src), _ in df[dup].groupby(["company_id", "fiscal_year", "source_type"]):
        f.add("emissions", cid, yr, "E04", "warn", f"duplicate rows for source '{src}'")

    primary = df[df["source_type"].isin(PRIMARY_SOURCES)].copy()
    ets = df[df["source_type"].isin(REGULATORY_SOURCES)]

    # E05 company-reported sources disagree on Scope 1
    for (cid, yr), g in primary.dropna(subset=["scope1_t"]).groupby(["company_id", "fiscal_year"]):
        if g["source_type"].nunique() > 1:
            lo, hi = g["scope1_t"].min(), g["scope1_t"].max()
            if hi > 0 and (hi - lo) / hi > t.source_disagreement:
                f.add("emissions", cid, yr, "E05", "warn",
                      f"sources disagree on Scope 1 by {(hi - lo) / hi:.0%}",
                      ", ".join(g["source_type"]))

    # Pick one primary row per company-year by source preference
    primary["_rank"] = primary["source_type"].map({s: i for i, s in enumerate(PRIMARY_SOURCES)})
    silver = (primary.sort_values("_rank")
                     .drop_duplicates(["company_id", "fiscal_year"])
                     .drop(columns="_rank"))

    # E06 Scope 2 method
    has_mkt, has_loc = silver["scope2_market_t"].notna(), silver["scope2_location_t"].notna()
    silver["scope2_method"] = np.select([has_mkt, has_loc], ["market", "location"], default="missing")
    for _, r in silver[~has_mkt & has_loc].iterrows():
        f.add("emissions", r["company_id"], r["fiscal_year"], "E06", "info",
              "Scope 2 location-based only; not comparable with market-based peers")
    for _, r in silver[~has_mkt & ~has_loc].iterrows():
        f.add("emissions", r["company_id"], r["fiscal_year"], "E06", "warn", "Scope 2 missing")
    s2 = silver["scope2_market_t"].fillna(silver["scope2_location_t"])
    silver["scope12_t"] = silver["scope1_t"] + s2  # NaN if either part missing

    # E07 coverage gaps: these are what imputation fills
    have = set(zip(silver.dropna(subset=["scope1_t"])["company_id"],
                   silver.dropna(subset=["scope1_t"])["fiscal_year"].astype(int)))
    for cid in sorted(df["company_id"].dropna().unique()):
        for yr in expected_years:
            if (cid, yr) not in have:
                f.add("emissions", cid, yr, "E07", "info", "no reported Scope 1 (gap)")

    # E08 year-over-year jump
    s = silver.dropna(subset=["scope1_t"]).sort_values(["company_id", "fiscal_year"])
    s = s.assign(_prev=s.groupby("company_id")["scope1_t"].shift(),
                 _prev_year=s.groupby("company_id")["fiscal_year"].shift())
    s = s[(s["fiscal_year"] - s["_prev_year"] == 1) & (s["_prev"] > 0)]
    change = (s["scope1_t"] - s["_prev"]) / s["_prev"]
    for (_, r), ch in zip(s[change.abs() > t.yoy_jump].iterrows(), change[change.abs() > t.yoy_jump]):
        f.add("emissions", r["company_id"], r["fiscal_year"], "E08", "warn",
              "Scope 1 YoY change: unit error, divestment or restatement?", round(float(ch), 3))

    # E09 EU ETS exceeds reported Scope 1 (ETS covers only EU installations, so it
    # should normally be <= company total; the reverse is a real inconsistency)
    m = silver.merge(ets[["company_id", "fiscal_year", "scope1_t"]],
                     on=["company_id", "fiscal_year"], suffixes=("", "_ets"))
    for _, r in m[m["scope1_t_ets"] > m["scope1_t"] * (1 + t.ets_tolerance)].iterrows():
        f.add("emissions", r["company_id"], r["fiscal_year"], "E09", "error",
              "EU ETS verified emissions exceed reported Scope 1",
              round(float(r["scope1_t_ets"] / r["scope1_t"]), 3))

    # E10 reporting boundary changed between years
    for cid, g in silver.dropna(subset=["boundary"]).groupby("company_id"):
        if g["boundary"].nunique() > 1:
            f.add("emissions", cid, None, "E10", "warn",
                  "reporting boundary changes across years", ", ".join(sorted(g["boundary"].unique())))

    keep = ["company_id", "company_name", "fiscal_year", "scope1_t", "scope2_location_t",
            "scope2_market_t", "scope2_method", "scope12_t", "boundary", "source_type",
            "source_url", "source_page"]
    silver = silver[[c for c in keep if c in silver.columns]].reset_index(drop=True)
    return silver, f.frame()


def check_intensity(emissions_silver: pd.DataFrame, financials: pd.DataFrame,
                    companies: pd.DataFrame, t: Thresholds = Thresholds()) -> pd.DataFrame:
    """E11: Scope 1+2 intensity (t / EUR m revenue) far from sector median -> likely unit error."""
    f = Flags()
    d = (emissions_silver.merge(drop_examples(financials)[["company_id", "fiscal_year", "revenue_eur_m"]],
                                on=["company_id", "fiscal_year"])
                         .merge(drop_examples(companies)[["company_id", "sector"]], on="company_id"))
    d = d[(d["revenue_eur_m"] > 0) & d["scope12_t"].notna()].copy()
    d["intensity"] = d["scope12_t"] / d["revenue_eur_m"]
    for (sector, yr), g in d.groupby(["sector", "fiscal_year"]):
        if g["company_id"].nunique() < t.min_sector_peers:
            continue
        for _, r in g.iterrows():
            peers = g.loc[g["company_id"] != r["company_id"], "intensity"]
            med = peers.median()
            if med > 0:
                ratio = r["intensity"] / med
                if ratio > t.intensity_ratio or ratio < 1 / t.intensity_ratio:
                    f.add("emissions", r["company_id"], yr, "E11", "warn",
                          f"intensity {ratio:.1f}x {sector} peer median: check units", round(float(ratio), 2))
    return f.frame()


# --------------------------------------------------------------------------- ratings

def check_ratings(raw: pd.DataFrame, as_of: str | pd.Timestamp,
                  t: Thresholds = Thresholds()) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validate ESG ratings and detect provider conflicts.

    Scales are not comparable (MSCI letters: higher is better; Sustainalytics risk
    score: lower is better), so each provider is converted to a percentile rank
    within the universe, where 1.0 = best ESG in the universe. Conflict = large rank gap.
    """
    f = Flags()
    df = drop_examples(raw)
    as_of = pd.Timestamp(as_of)

    def to_score(r):
        v = str(r["rating_raw"]).strip().upper()
        if r["rating_scale"] == "msci_letter":
            return float(MSCI_SCALE.index(v)) if v in MSCI_SCALE else np.nan
        if r["rating_scale"] == "sustainalytics_risk":
            x = pd.to_numeric(v, errors="coerce")
            return -float(x) if pd.notna(x) and 0 <= x <= 100 else np.nan  # negate: higher = better
        return np.nan

    df["score"] = df.apply(to_score, axis=1)
    for _, r in df[df["score"].isna()].iterrows():  # R01
        f.add("ratings", r["company_id"], None, "R01", "error",
              f"invalid rating for scale '{r['rating_scale']}'", r["rating_raw"])

    age = (as_of - pd.to_datetime(df["rating_date"], errors="coerce")).dt.days
    for (_, r), a in zip(df[age > t.rating_max_age_days].iterrows(), age[age > t.rating_max_age_days]):
        f.add("ratings", r["company_id"], None, "R02", "warn",  # R02
              f"{r['provider']} rating is {int(a)} days old", r["rating_date"])

    df = df.dropna(subset=["score"])
    df["pct_rank"] = df.groupby("provider")["score"].rank(pct=True)
    wide = df.pivot_table(index="company_id", columns="provider", values="pct_rank").reset_index()
    wide.columns.name = None
    providers = [c for c in wide.columns if c != "company_id"]

    for _, r in wide.iterrows():
        present = [p for p in providers if pd.notna(r[p])]
        if len(present) < 2:  # R03
            f.add("ratings", r["company_id"], None, "R03", "info",
                  f"only one provider: {', '.join(present) or 'none'}")
    if len(providers) >= 2:
        wide["rank_gap"] = wide[providers].max(axis=1) - wide[providers].min(axis=1)
        wide["provider_conflict"] = wide["rank_gap"] >= t.rating_conflict
        for _, r in wide[wide["provider_conflict"]].iterrows():  # R04
            f.add("ratings", r["company_id"], None, "R04", "warn",
                  "ESG providers disagree strongly on relative ranking", round(float(r["rank_gap"]), 2))
    return wide, f.frame()


# --------------------------------------------------------------------------- prices

def check_prices(raw: pd.DataFrame, t: Thresholds = Thresholds()) -> pd.DataFrame:
    """Expects long format: date, company_id, adj_close. Returns flags only."""
    f = Flags()
    df = raw.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["company_id", "date"])

    for cid, g in df.groupby("company_id"):
        px = pd.to_numeric(g["adj_close"], errors="coerce")
        for d in g.loc[(px <= 0) | px.isna(), "date"]:  # P01
            f.add("prices", cid, None, "P01", "error", "missing or non-positive price", str(d.date()))

        ret = px.pct_change()
        for d, r in zip(g.loc[ret.abs() > t.price_spike, "date"], ret[ret.abs() > t.price_spike]):
            f.add("prices", cid, None, "P02", "warn",  # P02
                  f"daily return {r:+.0%} on {d.date()}: split or bad tick?", round(float(r), 3))

        dates = g["date"].to_numpy().astype("datetime64[D]")
        if len(dates) > 1:
            gaps = np.busday_count(dates[:-1], dates[1:])
            for d0, d1, n in zip(dates[:-1], dates[1:], gaps):
                if n > t.price_gap_bdays:  # P03
                    f.add("prices", cid, None, "P03", "warn",
                          f"{int(n)} business-day gap {d0}..{d1}", int(n))

        same = px.diff().eq(0)
        run_id = (~same).cumsum()
        runs = same.groupby(run_id).sum()
        for rid, n in runs[runs + 1 >= t.stale_run].items():  # P04
            start = g.loc[run_id == rid, "date"].iloc[0]
            f.add("prices", cid, None, "P04", "warn",
                  f"{int(n) + 1} identical closes from {start.date()}", int(n) + 1)
    return f.frame()
