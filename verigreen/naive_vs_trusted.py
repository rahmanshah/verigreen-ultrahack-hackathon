"""Validation for data/bronze/emissions_naive_vs_trusted.csv (the raw-vs-trusted demo dataset).

Returns a list of human-readable problems rather than raising, so a caller can report
everything wrong at once. An empty list means the file is consistent with SCHEMA.md and
with data/bronze/emissions_raw.csv (every trusted value must be an actual verified row).
"""
from __future__ import annotations

import math
import re

import pandas as pd

from verigreen.quality_checks import UNIT_TO_TONNES

VALID_CATEGORY = {"aggregator_error", "pre_restatement", "financed_emissions", "unit_error"}
VALID_STATUS = {"verified_pdf", "from_notes"}
SCOPE_COLS = ["scope1", "scope2_location", "scope2_market"]
REQUIRED_TEXT = ["raw_source", "trusted_source", "notes"]
PAGE_CITATION = re.compile(r"\bp\.?\s*\d+", re.IGNORECASE)


def _num(x) -> float:
    return float(x) if pd.notna(x) and str(x).strip() != "" else math.nan


def _same(a: float, b: float) -> bool:
    return (math.isnan(a) and math.isnan(b)) or (not math.isnan(a) and not math.isnan(b)
                                                  and math.isclose(a, b, rel_tol=1e-9))


def _tonnes(row: pd.Series, prefix: str) -> list[float]:
    f = UNIT_TO_TONNES.get(str(row["unit"]).strip(), math.nan)
    return [_num(row[f"{prefix}{c}"]) * f for c in SCOPE_COLS]


def validate_naive_vs_trusted(nvt: pd.DataFrame, emissions_raw: pd.DataFrame) -> list[str]:
    problems: list[str] = []
    dup = nvt.duplicated(["company_id", "fiscal_year", "error_category"], keep=False)
    for (cid, yr, cat), _ in nvt[dup].groupby(["company_id", "fiscal_year", "error_category"]):
        problems.append(f"{cid} {yr} ({cat}): duplicate row for the same error category")
    raw = emissions_raw.copy()
    raw["unit"] = raw["unit"].astype(str).str.strip()
    for i, r in nvt.iterrows():
        tag = f"{r['company_id']} {r['fiscal_year']} ({r['error_category']})"
        if r["error_category"] not in VALID_CATEGORY:
            problems.append(f"{tag}: unknown error_category")
        if r["verification_status"] not in VALID_STATUS:
            problems.append(f"{tag}: unknown verification_status '{r['verification_status']}'")
        if str(r["unit"]).strip() not in UNIT_TO_TONNES:
            problems.append(f"{tag}: unknown unit '{r['unit']}'")
            continue
        for col in REQUIRED_TEXT:
            if pd.isna(r[col]) or not str(r[col]).strip():
                problems.append(f"{tag}: missing {col}")
        if r["verification_status"] == "verified_pdf" and not PAGE_CITATION.search(str(r["raw_source"])):
            problems.append(f"{tag}: verified_pdf row must cite a page in raw_source")

        # the naive value must be present, and must actually differ from the trusted one
        raw_vals, trusted_vals = _tonnes(r, "raw_"), _tonnes(r, "trusted_")
        has_combined = pd.notna(r["raw_combined_footprint"])
        if all(math.isnan(v) for v in raw_vals) and not has_combined:
            problems.append(f"{tag}: no raw value (raw_scope* or raw_combined_footprint)")
        if not has_combined and all(_same(a, b) for a, b in zip(raw_vals, trusted_vals)):
            problems.append(f"{tag}: raw values identical to trusted values")

        # every trusted value must come from a real row in emissions_raw for that company-year
        cand = raw[(raw["company_id"] == r["company_id"]) & (raw["fiscal_year"] == r["fiscal_year"])]
        if not any(all(_same(a, b) for a, b in zip(trusted_vals, _tonnes(c, "")))
                   for _, c in cand.iterrows()):
            problems.append(f"{tag}: trusted values match no emissions_raw row for that company-year")
    return problems
