import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verigreen.returns import (DECISION_DATE, LOOKBACK_YEARS, WINSOR_LOWER, WINSOR_UPPER,  # noqa: E402
                               annualised_covariance, daily_returns, estimation_window,
                               price_matrix, winsorise_returns)

ROOT = Path(__file__).resolve().parents[1]


def frame(n=500, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n)
    return pd.DataFrame(rng.normal(0, 0.01, (n, 3)), index=idx, columns=["A", "B", "C"])


def test_daily_returns_are_simple_returns_per_asset():
    long = pd.DataFrame({"date": ["2024-01-01", "2024-01-02", "2024-01-01", "2024-01-02"],
                         "company_id": ["A", "A", "B", "B"],
                         "adj_close_cleaned": [100.0, 110.0, 50.0, 45.0]})
    r = daily_returns(price_matrix(long))
    assert len(r) == 1
    assert np.isclose(r.loc["2024-01-02", "A"], 0.10) and np.isclose(r.loc["2024-01-02", "B"], -0.10)


def test_winsorise_clips_outliers_to_the_assets_own_quantiles_and_leaves_interior_alone():
    r = frame()
    r.loc[r.index[100], "A"] = 0.30
    r.loc[r.index[200], "A"] = -0.25
    w = winsorise_returns(r)
    hi, lo = r["A"].quantile(WINSOR_UPPER), r["A"].quantile(WINSOR_LOWER)
    assert np.isclose(w["A"].max(), hi) and np.isclose(w["A"].min(), lo)
    assert hi < 0.30 and lo > -0.25
    inside = (r >= r.quantile(WINSOR_LOWER)) & (r <= r.quantile(WINSOR_UPPER))
    assert (w.where(inside) == r.where(inside)).values[inside.values].all()


def test_winsorise_uses_the_same_quantiles_for_every_asset():
    r = frame()
    r["C"] = r["C"] * 10                       # a much more volatile asset
    w = winsorise_returns(r)
    for c in r.columns:
        n = len(r)
        clipped = int(((w[c] != r[c])).sum())
        assert abs(clipped - 2 * round(0.01 * n)) <= 4, (c, clipped)   # ~1% in each tail, for every column
    assert (w["C"].abs().max() > w["A"].abs().max() * 5)               # cut-offs scale with volatility


def test_winsorise_does_not_mutate_input_and_stays_within_original_bounds():
    r = frame()
    before = r.copy()
    w = winsorise_returns(r)
    pd.testing.assert_frame_equal(r, before)
    assert (w.max() <= r.max()).all() and (w.min() >= r.min()).all()
    # not idempotent in general: clipped values pile up at the cut-offs and shift the next pass's quantiles


def test_winsorise_rejects_bad_quantiles_and_keeps_nan():
    r = frame()
    for lo, hi in [(0.6, 0.4), (-0.1, 0.9), (0.1, 1.2), (0.5, 0.5)]:
        try:
            winsorise_returns(r, lo, hi)
        except ValueError:
            continue
        raise AssertionError(f"accepted {lo}, {hi}")
    r.iloc[5, 0] = np.nan
    assert np.isnan(winsorise_returns(r).iloc[5, 0])


def test_winsorising_reduces_the_covariance_driven_by_a_shared_spike():
    r = frame()
    r.iloc[250, 0], r.iloc[250, 1] = 0.30, 0.25      # two assets share one wild day
    raw = annualised_covariance(r).loc["A", "B"]
    win = annualised_covariance(winsorise_returns(r)).loc["A", "B"]
    assert raw > 0.03 and abs(win) < raw / 5     # 0.30 * 0.25 / 499 * 252 = 0.038 before clipping


def test_estimation_window_is_three_years_ending_on_the_decision_date():
    assert DECISION_DATE == pd.Timestamp("2025-03-31") and LOOKBACK_YEARS == 3
    idx = pd.bdate_range("2021-10-04", "2026-10-02")
    r = pd.DataFrame({"A": 0.001}, index=idx)
    w = estimation_window(r)
    assert w.index.max() == DECISION_DATE
    assert w.index.min() == pd.Timestamp("2022-04-01")
    assert (w.index > pd.Timestamp("2022-03-31")).all()
    assert estimation_window(r, end=pd.Timestamp("2024-12-31"), years=1).index.min() == pd.Timestamp("2024-01-01")


def test_kone_anomaly_date_is_after_the_decision_date_so_main_window_excludes_it():
    assert pd.Timestamp("2025-07-29") > DECISION_DATE


def test_winsorising_never_touches_prices_files():
    paths = [ROOT / "data/bronze/prices_raw.parquet"]
    if not paths[0].exists():
        return                                    # git-ignored file: nothing to check on a fresh clone
    before = hashlib.md5(paths[0].read_bytes()).hexdigest()
    prices = pd.read_parquet(paths[0])
    winsorise_returns(daily_returns(price_matrix(prices, column="adj_close")))
    assert hashlib.md5(paths[0].read_bytes()).hexdigest() == before


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(tests)} passed")
