"""Read-only loaders for the demo app.

Only committed files under data/gold and data/silver can be read. Nothing here imports verigreen or qiskit,
touches prices, PDFs or data/bronze, or uses the network.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
ALLOWED_DIRS = (ROOT / "data" / "gold", ROOT / "data" / "silver")


def _safe(path: str) -> Path:
    p = (ROOT / path).resolve()
    if p.parent not in ALLOWED_DIRS:
        raise ValueError(f"The app may only read files directly in data/gold or data/silver, got {path!r}")
    return p


def read_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(_safe(path))


def read_json(path: str) -> dict:
    return json.loads(_safe(path).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _short_names() -> dict[str, str]:
    c = read_csv("data/silver/carbon_intensity.csv").drop_duplicates("company_id")
    return {i: re.sub(r"\s+(Bank Abp|Oyj|Abp)$", "", n) for i, n in zip(c["company_id"], c["company_name"])}


def names(selection: str) -> list[str]:
    """'ELISA.HE;KNEBV.HE' -> ['Elisa', 'KONE'] (company names from the silver table, ticker if unknown)."""
    lookup = _short_names()
    return [lookup.get(s, s) for s in str(selection).split(";") if s]
