"""Build data/bronze/prices_cleaned.parquet from prices_raw.parquet + the manual anomaly
review table. Deterministic, no network access. prices_raw.parquet is never modified.

Usage:
    uv run python scripts/build_cleaned_prices.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verigreen.price_cleaning import build_cleaned_prices  # noqa: E402


def main() -> None:
    bronze = ROOT / "data" / "bronze"
    prices = pd.read_parquet(bronze / "prices_raw.parquet")
    reviews = pd.read_csv(bronze / "price_anomaly_reviews.csv")

    cleaned = build_cleaned_prices(prices, reviews)

    out_path = bronze / "prices_cleaned.parquet"
    cleaned.to_parquet(out_path, index=False)
    print(f"Wrote {len(cleaned)} rows to {out_path}")

    flagged = cleaned[cleaned["anomaly_status"].notna()]
    if not flagged.empty:
        print(f"{len(flagged)} flagged row(s):")
        print(flagged[["company_id", "date", "adj_close", "adj_close_cleaned",
                       "anomaly_status"]].to_string(index=False))


if __name__ == "__main__":
    main()
