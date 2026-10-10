"""Build data/silver/carbon_intensity.csv from the current bronze emissions and revenue data.

Reproducible, deterministic, no network access. Re-run this any time emissions_raw.csv or
financials_raw.csv changes.

Usage:
    uv run python scripts/build_carbon_intensity.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verigreen.quality_checks import check_emissions  # noqa: E402
from verigreen.carbon_intensity import build_carbon_intensity  # noqa: E402

YEARS = [2023, 2024, 2025]


def main() -> None:
    bronze = ROOT / "data" / "bronze"
    raw = pd.read_csv(bronze / "emissions_raw.csv")
    silver, flags = check_emissions(raw, YEARS)
    silver = silver[silver["fiscal_year"].isin(YEARS)]

    errors = flags[flags["severity"] == "error"]
    if not errors.empty:
        print(f"WARNING: {len(errors)} error-severity flags from check_emissions:")
        print(errors.to_string(index=False))

    financials = pd.read_csv(bronze / "financials_raw.csv")
    boundary_reviews = pd.read_csv(bronze / "revenue_boundary_reviews.csv")
    intensity = build_carbon_intensity(silver, financials, boundary_reviews)

    out_path = ROOT / "data" / "silver" / "carbon_intensity.csv"
    intensity.to_csv(out_path, index=False)
    print(f"Wrote {len(intensity)} rows to {out_path}")


if __name__ == "__main__":
    main()
