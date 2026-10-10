"""Manual review and (optional) treatment of check_prices-flagged price anomalies.

Nothing here infers or guesses a "corrected" price on its own. Every row in
data/bronze/price_anomaly_reviews.csv documents a specific, human-reviewed decision for
one (company_id, date). Points not listed in the review table pass through unchanged.
Unconfirmed anomalies are flagged but never silently fixed -- `adj_close_cleaned` only
differs from `adj_close` for rows explicitly marked `status=confirmed_bad_tick` with a
treatment other than 'none'.
"""
from __future__ import annotations

import pandas as pd

REVIEW_COLS = ["company_id", "date", "check_id", "status", "treatment", "reason", "reviewed_date"]
VALID_STATUS = {"confirmed_bad_tick", "unconfirmed", "real_event"}
VALID_TREATMENT = {"interpolate", "drop", "none"}


def build_cleaned_prices(prices: pd.DataFrame, reviews: pd.DataFrame) -> pd.DataFrame:
    """Returns a copy of `prices` with adj_close_cleaned, anomaly_status, anomaly_reason.

    Treatment, applied only when status == 'confirmed_bad_tick':
    - 'none': adj_close_cleaned left identical to adj_close.
    - 'interpolate': replaced with the average of the prior and next trading day's
      adj_close for that company (NaN if there is no neighbour on either side).
    - 'drop': adj_close_cleaned set to NaN for that row.

    Any other status ('unconfirmed', 'real_event') is flagged (anomaly_status/
    anomaly_reason populated) but never alters adj_close_cleaned, regardless of what
    `treatment` says -- treatment only takes effect once a review is confirmed.
    """
    bad_status = set(reviews["status"]) - VALID_STATUS
    if bad_status:
        raise ValueError(f"unknown review status: {bad_status}")
    bad_treatment = set(reviews["treatment"]) - VALID_TREATMENT
    if bad_treatment:
        raise ValueError(f"unknown review treatment: {bad_treatment}")

    df = prices.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["company_id", "date"]).reset_index(drop=True)
    df["adj_close_cleaned"] = df["adj_close"].astype(float)
    df["anomaly_status"] = pd.Series(pd.NA, index=df.index, dtype="object")
    df["anomaly_reason"] = pd.Series(pd.NA, index=df.index, dtype="object")

    reviews = reviews.copy()
    reviews["date"] = pd.to_datetime(reviews["date"])

    for _, row in reviews.iterrows():
        company_idx = df.index[df["company_id"] == row["company_id"]]
        match = company_idx[df.loc[company_idx, "date"] == row["date"]]
        if len(match) == 0:
            continue
        idx = match[0]
        df.loc[idx, "anomaly_status"] = row["status"]
        df.loc[idx, "anomaly_reason"] = row["reason"]

        if row["status"] != "confirmed_bad_tick" or row["treatment"] == "none":
            continue  # flagged, not treated -- adj_close_cleaned stays as reported

        pos = company_idx.get_loc(idx)
        if row["treatment"] == "drop":
            df.loc[idx, "adj_close_cleaned"] = float("nan")
        elif row["treatment"] == "interpolate" and 0 < pos < len(company_idx) - 1:
            prev_v = df.loc[company_idx[pos - 1], "adj_close"]
            next_v = df.loc[company_idx[pos + 1], "adj_close"]
            df.loc[idx, "adj_close_cleaned"] = (prev_v + next_v) / 2
        elif row["treatment"] == "interpolate":
            df.loc[idx, "adj_close_cleaned"] = float("nan")  # no neighbour to interpolate from

    return df
