"""Fetch market data (prices, first-pass revenue) for the 15 VeriGreen tickers via yfinance.

Caches raw yfinance responses under data/bronze/yfinance_cache/ (git-ignored) so reruns
don't refetch from Yahoo -- output files are rebuilt from the cache every run, so the
script is idempotent: same cache in, same files out. Pass --refresh to force re-fetching.

This script writes:
  - data/bronze/prices_raw.parquet            (long format: date, company_id, adj_close)
  - data/bronze/financials_yfinance_firstpass.csv   (yfinance "Total Revenue" only)

It does NOT write data/bronze/financials_raw.csv. That file is hand-reconciled against
primary sources (see docs/decisions_log.md) starting from the first-pass file above --
regenerating it from this script would silently overwrite those corrections.

Usage:
    uv run python scripts/fetch_market_data.py [--refresh]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verigreen.quality_checks import check_prices  # noqa: E402

CACHE_DIR = ROOT / "data" / "bronze" / "yfinance_cache"
BRONZE_DIR = ROOT / "data" / "bronze"

# Must match data/bronze/companies.csv.
TICKERS = [
    "NESTE.HE", "FORTUM.HE", "OUT1V.HE", "STERV.HE", "UPM.HE", "KEMIRA.HE", "WRT1V.HE",
    "METSO.HE", "KESKOB.HE", "KNEBV.HE", "NOKIA.HE", "ELISA.HE", "ORNBV.HE", "NDA-FI.HE", "SAMPO.HE",
]
FISCAL_YEARS = [2023, 2024, 2025]
MIN_YEARS_HISTORY = 3
GAP_BDAYS_FLAG = 5  # matches Thresholds.price_gap_bdays in verigreen.quality_checks


def _cache_path(ticker: str, kind: str, ext: str) -> Path:
    return CACHE_DIR / f"{ticker.replace('/', '_')}_{kind}.{ext}"


def fetch_info(ticker: str, refresh: bool) -> dict:
    """Ticker.info, cached as JSON. Falls back to fast_info if .info raises or is empty."""
    path = _cache_path(ticker, "info", "json")
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))

    t = yf.Ticker(ticker)
    try:
        info = dict(t.info)
        if not info:
            raise ValueError("empty info")
    except Exception as e:
        fast = t.fast_info
        info = {
            "longName": None,
            "shortName": None,
            "currency": getattr(fast, "currency", None),
            "_fallback_reason": f".info failed ({e}); used fast_info",
        }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(info, default=str), encoding="utf-8")
    return info


def fetch_history(ticker: str, refresh: bool, period: str = "5y") -> pd.DataFrame:
    """Daily OHLC + Adj Close, auto_adjust=False, cached as parquet.

    We use auto_adjust=False and read the explicit 'Adj Close' column, rather than the
    newer yfinance default (auto_adjust=True, adjusted values folded into 'Close'), so the
    adjusted-for-splits-and-dividends series has its own unambiguous name -- matching what
    check_prices expects as 'adj_close' and what 'Close'/'Adj Close' mean everywhere else
    in finance tooling.
    """
    path = _cache_path(ticker, "history", "parquet")
    if path.exists() and not refresh:
        return pd.read_parquet(path)

    t = yf.Ticker(ticker)
    hist = t.history(period=period, auto_adjust=False).reset_index()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    hist.to_parquet(path)
    return hist


def fetch_income_stmt(ticker: str, refresh: bool) -> pd.DataFrame:
    """Annual income statement, cached as parquet. Used only for the first-pass revenue file."""
    path = _cache_path(ticker, "income_stmt", "parquet")
    if path.exists() and not refresh:
        return pd.read_parquet(path)

    inc = yf.Ticker(ticker).income_stmt
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    inc.to_parquet(path)
    return inc


def verify_tickers(tickers: list[str], refresh: bool) -> pd.DataFrame:
    """Two attempts per ticker (first with the given refresh flag, second forcing a live
    refetch); report and move on if both fail, per the timebox."""
    rows = []
    for ticker in tickers:
        name = currency = first_date = last_date = None
        n_rows = max_gap = 0
        status, last_err = "ok", None
        for attempt in range(2):
            force = refresh or attempt == 1
            try:
                info = fetch_info(ticker, force)
                name = info.get("longName") or info.get("shortName")
                currency = info.get("currency")

                hist = fetch_history(ticker, force).dropna(subset=["Close"])
                if hist.empty:
                    raise ValueError("empty price history")
                dates = pd.to_datetime(hist["Date"]).dt.tz_localize(None).sort_values()
                first_date, last_date = dates.iloc[0], dates.iloc[-1]
                n_rows = len(hist)
                d = dates.to_numpy().astype("datetime64[D]")
                if len(d) > 1:
                    max_gap = int(np.busday_count(d[:-1], d[1:]).max())
                last_err = None
                break
            except Exception as e:
                last_err = e

        if last_err is not None:
            status = f"failed after 2 attempts: {last_err}"
        elif (last_date - first_date).days / 365.25 < MIN_YEARS_HISTORY:
            status = f"under {MIN_YEARS_HISTORY} years of history"
        elif max_gap > GAP_BDAYS_FLAG:
            status = f"gap of {max_gap} business days"

        rows.append(dict(company_id=ticker, verified=(status == "ok"), name_returned=name,
                         currency=currency, first_date=first_date, last_date=last_date,
                         n_rows=n_rows, max_gap_bdays=max_gap, status=status))
    return pd.DataFrame(rows)


def build_prices_parquet(tickers: list[str], refresh: bool, out_path: Path) -> pd.DataFrame:
    frames = []
    for ticker in tickers:
        hist = fetch_history(ticker, refresh).rename(columns={"Date": "date", "Adj Close": "adj_close"})
        hist["date"] = pd.to_datetime(hist["date"]).dt.tz_localize(None)
        hist = hist.dropna(subset=["adj_close"])  # drop incomplete/unsettled bars
        assert not hist.empty, f"{ticker}: empty price series after dropping incomplete bars"
        frames.append(hist[["date", "adj_close"]].assign(company_id=ticker))

    long = pd.concat(frames, ignore_index=True)[["date", "company_id", "adj_close"]]
    assert long["company_id"].nunique() == len(tickers), "ticker count mismatch building prices_raw"
    long.to_parquet(out_path, index=False)
    return long


def build_financials_firstpass(tickers: list[str], years: list[int], refresh: bool,
                               out_path: Path) -> pd.DataFrame:
    """yfinance 'Total Revenue' only -- a starting point, not the final financials_raw.csv."""
    rows = []
    for ticker in tickers:
        try:
            inc = fetch_income_stmt(ticker, refresh)
            revenue = inc.loc["Total Revenue"] if "Total Revenue" in inc.index else pd.Series(dtype=float)
        except Exception as e:
            revenue = pd.Series(dtype=float)
            print(f"  {ticker}: income_stmt failed ({e})", file=sys.stderr)

        for year in years:
            value = next((revenue[c] for c in revenue.index if pd.Timestamp(c).year == year), None)
            rows.append(dict(
                company_id=ticker, fiscal_year=year,
                revenue_eur_m=round(value / 1e6, 1) if value is not None else None,
                source_url="yfinance Ticker.income_stmt, row 'Total Revenue'",
                notes="first pass, not verified against primary source" if value is not None
                      else "yfinance has no value for this company-year",
            ))
    df = pd.DataFrame(rows)
    df.to_csv(out_path, index=False)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="re-fetch from Yahoo, ignoring cache")
    args = parser.parse_args()

    assert len(TICKERS) == 15, "expected exactly 15 tickers"
    pd.set_option("display.width", 160)

    print("=== 1. Ticker verification ===")
    report = verify_tickers(TICKERS, args.refresh)
    print(report.to_string(index=False))
    failed = report[~report["verified"]]
    if not failed.empty:
        print(f"\n{len(failed)} ticker(s) need attention:\n{failed[['company_id', 'status']].to_string(index=False)}")

    print("\n=== 2. Price download ===")
    prices_path = BRONZE_DIR / "prices_raw.parquet"
    prices = build_prices_parquet(TICKERS, args.refresh, prices_path)
    print(f"Wrote {len(prices)} rows to {prices_path}")

    flags = check_prices(prices)
    print(f"check_prices: {len(flags)} flags")
    if not flags.empty:
        print(flags.groupby(["check_id", "company_id"]).size().to_string())

    print("\n=== 3. Revenue first pass (yfinance only -- NOT the final financials_raw.csv) ===")
    firstpass_path = BRONZE_DIR / "financials_yfinance_firstpass.csv"
    fin = build_financials_firstpass(TICKERS, FISCAL_YEARS, args.refresh, firstpass_path)
    print(f"Wrote {len(fin)} rows to {firstpass_path}")
    missing = fin[fin["revenue_eur_m"].isna()]
    if not missing.empty:
        print(f"{len(missing)} company-year(s) with no yfinance revenue value:\n"
              f"{missing[['company_id', 'fiscal_year']].to_string(index=False)}")


if __name__ == "__main__":
    main()
