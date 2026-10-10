"""Verify every revenue_eur_m in data/bronze/financials_raw.csv against the yfinance cache,
classify its source, and write a revenue_source column back into the file.

revenue_source values:
  - 'yfinance'      : source_url itself is the yfinance pull (first pass, not reconciled).
  - 'primary_report': source_url is a primary document, and its value agrees with the
                       cached yfinance figure for that company-year within 2%.
  - 'override'       : source_url is a primary document that DISAGREES with yfinance by
                       more than 2%, and the notes column explicitly documents why (the
                       word 'OVERRIDE', case-insensitive).
  - blank            : revenue_eur_m itself is blank (nothing to classify or compare).

Fails loudly (non-zero exit, no file written) if any primary-sourced row disagrees with
yfinance by more than 2% WITHOUT an explicit override note -- that combination means either
the primary-source figure is wrong, or a deliberate choice was made but not documented.

Needs data/bronze/yfinance_cache/ populated (run scripts/fetch_market_data.py first).

Usage:
    uv run python scripts/verify_financials.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BRONZE = ROOT / "data" / "bronze"
MISMATCH_THRESHOLD = 0.02  # 2%


def yfinance_revenue_by_ticker_year(cache_dir: Path) -> dict[tuple[str, int], float]:
    """Reads cached income_stmt parquet files, returns {(ticker, year): revenue_eur_m}."""
    out: dict[tuple[str, int], float] = {}
    for path in cache_dir.glob("*_income_stmt.parquet"):
        ticker = path.name.removesuffix("_income_stmt.parquet")
        inc = pd.read_parquet(path)
        if "Total Revenue" not in inc.index:
            continue
        revenue = inc.loc["Total Revenue"]
        for col, value in revenue.items():
            if pd.notna(value):
                out[(ticker, pd.Timestamp(col).year)] = value / 1e6
    return out


def classify(row: pd.Series, yf_revenue: dict[tuple[str, int], float]) -> tuple[str, str | None]:
    """Returns (revenue_source, error_message_or_None)."""
    if pd.isna(row["revenue_eur_m"]):
        return "", None

    if str(row["source_url"]).lower().startswith("yfinance"):
        return "yfinance", None

    key = (row["company_id"], int(row["fiscal_year"]))
    yf_value = yf_revenue.get(key)
    if yf_value is None:
        return "primary_report", None  # nothing in the cache to compare against

    diff = abs(row["revenue_eur_m"] - yf_value) / yf_value
    if diff <= MISMATCH_THRESHOLD:
        return "primary_report", None

    if "override" in str(row["notes"]).lower():
        return "override", None

    return "override", (
        f"{row['company_id']} {row['fiscal_year']}: primary-source value {row['revenue_eur_m']} "
        f"disagrees with yfinance {yf_value:.1f} by {diff:.1%} (> {MISMATCH_THRESHOLD:.0%}), "
        f"but notes contain no 'override' justification. Fix the data or document the override."
    )


def main() -> None:
    fin_path = BRONZE / "financials_raw.csv"
    fin = pd.read_csv(fin_path)
    cache_dir = BRONZE / "yfinance_cache"
    if not any(cache_dir.glob("*_income_stmt.parquet")):
        sys.exit(f"No yfinance cache found at {cache_dir}. Run scripts/fetch_market_data.py first.")

    yf_revenue = yfinance_revenue_by_ticker_year(cache_dir)

    sources, errors = [], []
    for _, row in fin.iterrows():
        source, error = classify(row, yf_revenue)
        sources.append(source)
        if error:
            errors.append(error)

    if errors:
        print(f"FAILED: {len(errors)} unexplained mismatch(es) above {MISMATCH_THRESHOLD:.0%}:",
              file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    fin["revenue_source"] = sources
    fin.to_csv(fin_path, index=False)

    counts = pd.Series(sources).value_counts(dropna=False)
    print(f"OK: no unexplained mismatches. Wrote revenue_source to {fin_path}")
    print(counts.to_string())


if __name__ == "__main__":
    main()
