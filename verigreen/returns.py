"""Daily returns, uniform winsorisation, and the estimation window for the covariance matrix.

Nothing here writes to disk or touches `prices_raw.parquet`. Prices come in as a frame and returns go out.

Winsorisation: every asset is clipped to its OWN 1st and 99th percentile of daily returns
(WINSOR_LOWER / WINSOR_UPPER). The procedure and the quantiles are identical for all assets, so no asset
is treated specially (in particular KONE's unconfirmed 2025-07-29 point is not hand-edited); the cut-offs
adapt to each asset's volatility, which a fixed +-X% cut-off would not. Quantiles are computed on the
frame passed in, so call it on the estimation window to avoid look-ahead.

Estimation window: a decision-date convention, NOT a backtest. The optimiser is run as if on
DECISION_DATE (2025-03-31, when the FY2024 reports were first published) using the LOOKBACK_YEARS (3) of
daily returns that end on that date. Returns dated after DECISION_DATE are never used in the main
window. The full sample is only a sensitivity.
"""
from __future__ import annotations

import pandas as pd

WINSOR_LOWER = 0.01
WINSOR_UPPER = 0.99
DECISION_DATE = pd.Timestamp("2025-03-31")
LOOKBACK_YEARS = 3
TRADING_DAYS = 252
PRICE_COLUMN = "adj_close_cleaned"


def price_matrix(prices: pd.DataFrame, column: str = PRICE_COLUMN) -> pd.DataFrame:
    """Long prices (date, company_id, <column>) -> wide frame indexed by date, one column per company."""
    wide = prices.pivot(index="date", columns="company_id", values=column)
    wide.index = pd.to_datetime(wide.index)
    return wide.sort_index()


def daily_returns(prices_wide: pd.DataFrame) -> pd.DataFrame:
    """Simple daily returns P_t / P_{t-1} - 1 per asset. The first row is dropped; gaps stay NaN."""
    return prices_wide.pct_change(fill_method=None).iloc[1:]


def winsorise_returns(returns: pd.DataFrame, lower: float = WINSOR_LOWER,
                      upper: float = WINSOR_UPPER) -> pd.DataFrame:
    """Clips each column to its own [lower, upper] quantiles. Same quantiles for every column; input unchanged."""
    if not 0.0 <= lower < upper <= 1.0:
        raise ValueError(f"need 0 <= lower < upper <= 1, got {lower}, {upper}")
    lo = returns.quantile(lower)
    hi = returns.quantile(upper)
    return returns.clip(lower=lo, upper=hi, axis=1)


def estimation_window(returns: pd.DataFrame, end: pd.Timestamp = DECISION_DATE,
                      years: int = LOOKBACK_YEARS) -> pd.DataFrame:
    """Returns dated in (end - years, end]."""
    start = end - pd.DateOffset(years=years)
    return returns[(returns.index > start) & (returns.index <= end)]


def annualised_covariance(returns: pd.DataFrame) -> pd.DataFrame:
    """Pairwise-complete sample covariance of daily returns, times TRADING_DAYS."""
    return returns.cov() * TRADING_DAYS
