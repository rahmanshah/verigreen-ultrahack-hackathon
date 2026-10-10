"""Read-only report: daily returns and volume for all 15 tickers around 2025-07-29 (the KONE / Elisa round trip).

Returns come from `adj_close` in prices_raw.parquet (git-ignored, untouched); volume from the cached yfinance history
(data/bronze/yfinance_cache/*_history.parquet, git-ignored). z = return / std of the ticker's daily returns over the
250 trading days before the window; volume ratio = volume / median volume over the same 250 days. Descriptive only:
not a quality check, writes nothing, changes no price.

Run: uv run python scripts/report_price_window.py [start end]   (default 2025-07-28 2025-07-31)
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PRICES = ROOT / "data/bronze/prices_raw.parquet"
CACHE = ROOT / "data/bronze/yfinance_cache"
LOOKBACK = 250


def main(start: str = "2025-07-28", end: str = "2025-07-31") -> None:
    p = pd.read_parquet(PRICES)
    p["date"] = pd.to_datetime(p["date"]).dt.tz_localize(None).dt.normalize()
    px = p.pivot(index="date", columns="company_id", values="adj_close").sort_index()
    rets = px.pct_change(fill_method=None)
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    before = rets[rets.index < s].tail(LOOKBACK)
    rows = []
    for c in px.columns:
        h = pd.read_parquet(CACHE / f"{c}_history.parquet")
        h["Date"] = pd.to_datetime(h["Date"], utc=True).dt.tz_localize(None).dt.normalize()
        vol = h.set_index("Date")["Volume"]
        vol_med = vol[vol.index < s].tail(LOOKBACK).median()
        for d in rets.index[(rets.index >= s) & (rets.index <= e)]:
            r = rets.at[d, c]
            rows.append({"company_id": c, "date": d.date(), "adj_close": px.at[d, c], "return_pct": 100 * r,
                         "z": r / before[c].std(), "volume": vol.get(d), "volume_ratio": vol.get(d) / vol_med})
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print(f"returns and volume {start} .. {end} (z and volume ratio vs the {LOOKBACK} prior trading days)\n")
    print(df.round(2).to_string(index=False))
    wide = df.pivot(index="company_id", columns="date", values="return_pct").round(2)
    print("\nreturn % by date:\n" + wide.to_string())
    big = df[df["z"].abs() > 4]
    print("\n|z| > 4:\n" + (big.round(2).to_string(index=False) if len(big) else "none"))


if __name__ == "__main__":
    main(*sys.argv[1:3])
