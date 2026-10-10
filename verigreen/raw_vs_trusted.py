"""Stage G0: the same exact QUBO on naive-pipeline vs trusted FY2024 carbon intensity. Exact enumeration only.

A case is one or more FY2024 rows of `emissions_naive_vs_trusted.csv`. The naive intensity of each affected company is
rebuilt from the raw values with the same (trusted) revenue; every other company keeps its trusted intensity.
- pre_restatement / unit_error: raw Scope 1 and raw market-based Scope 2 where given; a blank raw field keeps the
  trusted value (an assumption used only here, not stored in the data). A row that only changes location-based Scope 2
  (Outokumpu) leaves the market-based intensity unchanged.
- financed_emissions: raw_combined_footprint / revenue replaces Scope 1 + 2. If a case also holds a pre_restatement row
  for the same company, the financed row wins and the other is reported as superseded: a pipeline that took the
  headline total has no own-operations number left to restate.

Carbon conditions (Sigma, mu and u are always the trusted gold inputs):
- frozen_trusted_z (main): ln(naive intensity) z-scored with the trusted ln mean and std, trusted scales frozen. The
  other assets' coefficients are then bit-identical to the trusted QUBO.
- refit_naive: z-score on the naive inputs' own mean and std, scales re-fitted on the naive inputs.
- rank_z: rank of the naive intensity z-scored with the trusted rank mean and std, trusted rank-based scales frozen;
  its baseline is the trusted rank-based optimum.

The metric is the equal-weight WACI: the mean intensity (tCO2e/EURm) of the selected assets, each held at 1/K.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from verigreen.qubo import (CARBON_PATH, FISCAL_YEAR, LOW_PRESSURE_CONFIG, MAIN_CONFIG, ROOT, TRUST_CONFIG,
                            GoldInputs, QuboConfig, build_qubo, carbon_scores, exact_optimum, fit_scales,
                            objective_direct)

NAIVE_PATH = ROOT / "data" / "bronze" / "emissions_naive_vs_trusted.csv"
GOLD_RAW_VS_TRUSTED_PATH = ROOT / "data" / "gold" / "raw_vs_trusted_exact_fy2024.csv"

# FY2024 intensities are bimodal (0.5-10.7 and 130-327 tCO2e/EURm); "heavy emitter" = the upper cluster.
HEAVY_EMITTER_MIN = 100.0

FINANCED_BASIS = "AR2025 comparative, recalculated: a definition illustration, not what the 2024 reports printed"
RAW_BASIS = {
    ("NDA-FI.HE", "financed_emissions"): FINANCED_BASIS,
    ("SAMPO.HE", "financed_emissions"): FINANCED_BASIS,
    ("NDA-FI.HE", "pre_restatement"): "As first published for FY2024, quoted in the AR2025 restatement disclosure",
    ("KESKOB.HE", "pre_restatement"): "As first published for FY2024 ('Reported 2024' column of the AR2025 bridge "
                                      "table)",
    ("KEMIRA.HE", "pre_restatement"): "As first published for FY2024 ('Reported value' column, AR2025); market-based "
                                      "Scope 2 only",
    ("OUT1V.HE", "pre_restatement"): "As first published for FY2024, quoted in the 2025 statement footnote; "
                                     "location-based Scope 2 only",
    ("METSO.HE", "unit_error"): "As first published in the FY2024 report (Financial review 2024, p.39)",
    ("SAMPO.HE", "pre_restatement"): "Derived from the restatement delta stated in AR2025 (1,412 - 530); Scope 1 only, "
                                     "not printed in any PDF on disk",
}

HEADLINES = {
    "MAIN_CONFIG": (MAIN_CONFIG, "u"),
    "TRUST_CONFIG": (TRUST_CONFIG, "u"),
    "TRUST_CONFIG_u_high": (TRUST_CONFIG, "u_high"),
    "LOW_PRESSURE_CONFIG": (LOW_PRESSURE_CONFIG, "u"),
}
CONDITIONS = ("frozen_trusted_z", "refit_naive", "rank_z")
VINTAGE_CATEGORIES = ("pre_restatement", "unit_error")


@dataclass(frozen=True)
class NaiveRow:
    company_id: str
    category: str
    raw_scope1: float
    raw_scope2_market: float
    raw_combined: float
    verification_status: str

    @property
    def key(self) -> str:
        return f"{self.company_id}:{self.category}"

    @property
    def raw_basis(self) -> str:
        return RAW_BASIS[(self.company_id, self.category)]


def trusted_fy(path: Path = CARBON_PATH, year: int = FISCAL_YEAR) -> pd.DataFrame:
    """Silver FY rows indexed by company_id: scope1_t, scope2_market_t, scope2_location_t, revenue, intensity."""
    df = pd.read_csv(path)
    return df[df["fiscal_year"] == year].set_index("company_id").sort_index()


def load_naive_rows(trusted: pd.DataFrame, path: Path = NAIVE_PATH, year: int = FISCAL_YEAR) -> list[NaiveRow]:
    """FY rows in file order. Raises if a trusted value in the naive file differs from the silver table, or if a row
    has no documented raw_basis (or a basis entry has no row)."""
    df = pd.read_csv(path)
    df = df[df["fiscal_year"] == year]
    for _, r in df.iterrows():
        t = trusted.loc[r["company_id"]]
        for col, silver in (("trusted_scope1", "scope1_t"), ("trusted_scope2_market", "scope2_market_t"),
                            ("trusted_scope2_location", "scope2_location_t")):
            if not np.isclose(float(r[col]), float(t[silver])):
                raise ValueError(f"{r['company_id']} {col} {r[col]} != silver {silver} {t[silver]}")
    keys = set(zip(df["company_id"], df["error_category"]))
    if keys != {k for k in RAW_BASIS}:
        raise ValueError(f"raw_basis entries and FY{year} rows differ: {sorted(keys ^ set(RAW_BASIS))}")
    return [NaiveRow(r["company_id"], r["error_category"], float(r["raw_scope1"]), float(r["raw_scope2_market"]),
                     float(r["raw_combined_footprint"]), r["verification_status"]) for _, r in df.iterrows()]


def cases(rows: list[NaiveRow]) -> dict[str, list[NaiveRow]]:
    """Each row on its own, then all_naive (every row) and all_vintage (pre_restatement and unit_error rows only)."""
    out = {r.key: [r] for r in rows}
    out["all_naive"] = list(rows)
    out["all_vintage"] = [r for r in rows if r.category in VINTAGE_CATEGORIES]
    return out


def naive_intensity(trusted: pd.DataFrame, rows: list[NaiveRow]) -> tuple[pd.Series, list[NaiveRow], list[NaiveRow]]:
    """(naive market-based intensity for all companies, rows applied, rows superseded by a financed row)."""
    recomputed = (trusted["scope1_t"] + trusted["scope2_market_t"]) / trusted["revenue_eur_m"]
    if not np.allclose(recomputed, trusted["intensity_market_tco2e_per_eurm"], rtol=1e-12):
        raise ValueError("silver intensity is not (scope1 + scope2 market) / revenue")
    intensity = trusted["intensity_market_tco2e_per_eurm"].astype(float).copy()   # unaffected rows stay bit-identical
    applied, superseded = [], []
    for company in dict.fromkeys(r.company_id for r in rows):
        mine = [r for r in rows if r.company_id == company]
        t = trusted.loc[company]
        financed = [r for r in mine if r.category == "financed_emissions"]
        other = [r for r in mine if r.category != "financed_emissions"]
        if len(financed) > 1 or len(other) > 1:
            raise ValueError(f"{company}: more than one row of one kind in a case")
        if financed:
            intensity[company] = financed[0].raw_combined / t["revenue_eur_m"]
            applied += financed
            superseded += other
        else:
            r = other[0]
            s1 = t["scope1_t"] if np.isnan(r.raw_scope1) else r.raw_scope1
            s2 = t["scope2_market_t"] if np.isnan(r.raw_scope2_market) else r.raw_scope2_market
            intensity[company] = (s1 + s2) / t["revenue_eur_m"]
            applied.append(r)
    return intensity, applied, superseded


# ---------------------------------------------------------------- QUBO inputs per condition

def trusted_inputs(gold: GoldInputs, carbon: str, trust: str):
    """Trusted main-window inputs with the given carbon method and trust score, and their (frozen) fitted scales."""
    base = gold.inputs("main")
    inp = replace(base, c=np.array(gold.raw["carbon"][carbon]), u=np.array(gold.raw["trust"][trust]))
    return inp, fit_scales(inp, gold.raw["k"])


def naive_inputs(gold: GoldInputs, naive: pd.Series, condition: str, trust: str):
    """(trusted inputs, trusted scales, naive inputs, scales to score the naive inputs with) for one condition."""
    a = list(gold.assets)
    trusted_int = pd.Series(gold.raw["intensity_market_tco2e_per_eurm"], index=a)
    naive = naive.loc[a]
    if condition == "rank_z":
        t_inp, t_scales = trusted_inputs(gold, "rank_z", trust)
        r_t, r_n = trusted_int.rank(method="average"), naive.rank(method="average")
        c = ((r_n - r_t.mean()) / r_t.std(ddof=0)).to_numpy()
        return t_inp, t_scales, replace(t_inp, c=c, intensity=naive.to_numpy()), t_scales
    t_inp, t_scales = trusted_inputs(gold, "log_z", trust)
    if condition == "frozen_trusted_z":
        lt = np.log(trusted_int)
        c = ((np.log(naive) - lt.mean()) / lt.std(ddof=0)).to_numpy()
        return t_inp, t_scales, replace(t_inp, c=c, intensity=naive.to_numpy()), t_scales
    if condition == "refit_naive":
        n_inp = replace(t_inp, c=carbon_scores(naive, "log_z").to_numpy(), intensity=naive.to_numpy())
        return t_inp, t_scales, n_inp, fit_scales(n_inp, gold.raw["k"])
    raise ValueError(f"condition must be one of {CONDITIONS}, got {condition!r}")


# ---------------------------------------------------------------- rows

def _names(assets, x) -> list[str]:
    return [a for a, b in zip(assets, x) if b]


def _heavy(assets, x, intensity) -> str:
    return ";".join(a for a, b, i in zip(assets, x, intensity) if b and i >= HEAVY_EMITTER_MIN)


def _pct(a: float, b: float) -> float:
    return 100 * (a - b) / b


def compare(gold: GoldInputs, naive: pd.Series, cfg: QuboConfig, trust: str, condition: str) -> dict:
    """Exact optimum on trusted vs naive inputs for one setting, and the equal-weight WACI of each portfolio."""
    t_inp, t_scales, n_inp, n_scales = naive_inputs(gold, naive, condition, trust)
    q_t, q_n = build_qubo(t_inp, cfg, t_scales), build_qubo(n_inp, cfg, n_scales)
    r_t, r_n = exact_optimum(q_t), exact_optimum(q_n)
    assert r_t.separated and r_n.separated and r_t.global_min_feasible and r_n.global_min_feasible
    assets, true_int = t_inp.assets, t_inp.intensity
    xt, xn = r_t.x, r_n.x
    # both portfolios scored on trusted data by the same formula, so an unchanged selection has regret exactly 0
    f_true_naive, f_true_opt = (objective_direct(x, t_inp, t_scales, cfg) for x in (xn, xt))
    entered, left = sorted(set(r_n.selected) - set(r_t.selected)), sorted(set(r_t.selected) - set(r_n.selected))
    reported, true = float(n_inp.intensity[xn == 1].mean()), float(true_int[xn == 1].mean())
    return {
        "trusted_selected": ";".join(r_t.selected), "naive_selected": ";".join(r_n.selected),
        "selection_changed": r_t.selected != r_n.selected, "entered": ";".join(entered), "left": ";".join(left),
        "n_swapped": len(entered),
        "waci_eq_weight_true_trusted_optimum": float(true_int[xt == 1].mean()),
        "waci_eq_weight_naive_reported": reported,
        "waci_eq_weight_true_naive_portfolio": true,
        "waci_eq_weight_error_pct": _pct(reported, true),
        "heavy_emitters_trusted_optimum": _heavy(assets, xt, true_int),
        "heavy_emitters_naive_portfolio": _heavy(assets, xn, true_int),
        "true_regret_pct_of_range": 100 * (f_true_naive - f_true_opt) / r_t.feasible_range,
        "naive_p_star": q_n.p_star, "naive_separated": r_n.separated,
    }


def raw_vs_trusted_rows(gold: GoldInputs, trusted: pd.DataFrame | None = None,
                        naive_path: Path = NAIVE_PATH) -> pd.DataFrame:
    trusted = trusted_fy() if trusted is None else trusted
    a = list(gold.assets)
    if not np.allclose(trusted.loc[a, "intensity_market_tco2e_per_eurm"], gold.raw["intensity_market_tco2e_per_eurm"],
                       rtol=1e-12):
        raise ValueError("gold JSON intensity differs from the silver table: rerun scripts/report_qubo.py")
    true_int = trusted.loc[a, "intensity_market_tco2e_per_eurm"].astype(float)
    rows = []
    for case_id, case_rows in cases(load_naive_rows(trusted, naive_path)).items():
        naive, applied, superseded = naive_intensity(trusted, case_rows)
        naive = naive.loc[a]
        changed = naive[~np.isclose(naive, true_int, rtol=1e-12, atol=0)]
        meta = {
            "case_id": case_id,
            "companies": ";".join(dict.fromkeys(r.company_id for r in case_rows)),
            "applied_rows": ";".join(r.key for r in applied),
            "superseded_rows": ";".join(r.key for r in superseded),
            "verification_status": ";".join(sorted({r.verification_status for r in applied})),
            "raw_basis": " | ".join(f"{r.key}: {r.raw_basis}" if len(applied) > 1 else r.raw_basis for r in applied),
            "intensity_changes": ";".join(f"{c} {true_int[c]:.4g}->{naive[c]:.4g}" for c in changed.index),
            "waci_eq_weight_benchmark_trusted": float(true_int.mean()),
            "waci_eq_weight_benchmark_naive": float(naive.mean()),
            "waci_eq_weight_benchmark_error_pct": _pct(float(naive.mean()), float(true_int.mean())),
        }
        for condition in CONDITIONS:
            for label, (cfg, trust) in HEADLINES.items():
                rows.append({**meta, "condition": condition, "headline": label, "trust_score": trust,
                             **compare(gold, naive, cfg, trust, condition)})
    return pd.DataFrame(rows)
