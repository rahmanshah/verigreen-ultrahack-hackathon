"""Reports how KONE's unconfirmed 2025-07-29 price point moves its covariance row.

Read-only: reads data/bronze/prices_cleaned.parquet (identical to prices_raw for this point, because the
review is `unconfirmed`), writes nothing. Two windows: MAIN (3 years ending DECISION_DATE) and the full
sample as a sensitivity. For each, three variants of the annualised covariance matrix:
  raw          daily returns as reported
  drop_point   the 2025-07-29 price excluded: both return rows built from it (07-29: +30%, 07-30: -24%) are
               removed for ALL assets so dates stay aligned
  winsorised   per-asset 1st/99th percentile clip (quantiles computed inside the window), point included
Also prints whether a 0.5/99.5 winsorisation moves any covariance entry by more than 5% vs 1/99.

Run: uv run python scripts/report_kone_covariance.py
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verigreen.returns import (DECISION_DATE, LOOKBACK_YEARS, WINSOR_LOWER, WINSOR_UPPER,  # noqa: E402
                               annualised_covariance, daily_returns, estimation_window, price_matrix,
                               winsorise_returns)

KONE = "KNEBV.HE"
BAD_PRICE_DATE = pd.Timestamp("2025-07-29")
ALT_QUANTILES = (0.005, 0.995)
ENTRY_TOLERANCE = 0.05


def variants(window: pd.DataFrame, bad_rows: list[pd.Timestamp]) -> dict[str, pd.DataFrame]:
    return {
        "raw": annualised_covariance(window),
        "drop_point": annualised_covariance(window.drop(index=[d for d in bad_rows if d in window.index])),
        "winsorised": annualised_covariance(winsorise_returns(window)),
    }


def relative_changes(a: pd.DataFrame, b: pd.DataFrame) -> pd.Series:
    """|b - a| / |a| for the unique entries (upper triangle incl. diagonal), largest first."""
    rel = ((b - a) / a.abs()).abs()
    keep = pd.DataFrame(False, index=rel.index, columns=rel.columns)
    for i in range(len(rel)):
        keep.iloc[i, i:] = True
    out = rel.where(keep).stack()
    out.index = [f"{x} x {y}" for x, y in out.index]
    return out.sort_values(ascending=False)


def main() -> None:
    prices = pd.read_parquet(ROOT / "data/bronze/prices_cleaned.parquet")
    rets = daily_returns(price_matrix(prices))
    after = rets.index[rets.index >= BAD_PRICE_DATE][:2]
    bad_rows = list(after)  # the return INTO the bad price and the return OUT of it
    print(f"returns built from the {BAD_PRICE_DATE.date()} price: {[d.date() for d in bad_rows]}")
    print(f"KONE returns on those dates: {[round(float(rets.loc[d, KONE]), 4) for d in bad_rows]}")
    print("all assets' returns on those dates (%):")
    print((rets.loc[bad_rows].T * 100).round(2).to_string())
    print(f"winsorisation: per-asset {WINSOR_LOWER:.0%}/{WINSOR_UPPER:.0%}; "
          f"main window: {LOOKBACK_YEARS}y ending {DECISION_DATE.date()}; covariance annualised x252\n")

    windows = {"MAIN (3y to decision date)": estimation_window(rets), "FULL sample (sensitivity)": rets}
    for name, w in windows.items():
        inside = [d.date().isoformat() for d in bad_rows if d in w.index]
        print(f"=== {name}: {w.index.min().date()} .. {w.index.max().date()} ({len(w)} days); "
              f"bad-point returns inside window: {inside or 'none'}")
        v = variants(w, bad_rows)
        var = pd.DataFrame({k: m.loc[KONE] for k, m in v.items()})
        vol = pd.Series({k: m.loc[KONE, KONE] ** 0.5 for k, m in v.items()}, name="KONE vol (annualised)")
        print(var.round(5).to_string())
        print(vol.round(4).to_string(), "\n")
        cov_change = (v["drop_point"].loc[KONE] / v["raw"].loc[KONE] - 1).drop(KONE)
        print("KONE covariance, drop_point vs raw (relative change, other assets):")
        print(cov_change.map("{:+.1%}".format).to_string(), "\n")
        base = v["winsorised"]
        alt = annualised_covariance(winsorise_returns(w, *ALT_QUANTILES))
        rel = relative_changes(base, alt)
        n_over = int((rel > ENTRY_TOLERANCE).sum())
        print(f"0.5/99.5 vs 1/99 winsorised covariance: {n_over} of {len(rel)} unique entries change by more than "
              f"{ENTRY_TOLERANCE:.0%}; largest: " + ", ".join(f"{k} {v:.1%}" for k, v in rel.head(3).items()))
        kone_rel = rel[[k for k in rel.index if KONE in k.split(" x ")]]
        print(f"  KONE row: max change {kone_rel.max():.1%} ({kone_rel.idxmax()})\n")


if __name__ == "__main__":
    main()
