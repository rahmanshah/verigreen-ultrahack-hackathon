"""QUBO for choosing K of the 15 assets, FY2024. Pure numpy; no qiskit, no QAOA here.

Selection model: x_i in {0, 1}, the chosen assets are held at equal weight 1/K. Weights are not optimised.

Inputs (one entry per asset, assets in sorted company_id order):
- Sigma, mu: annualised covariance and mean of winsorised daily simple returns (`verigreen.returns`). Main window =
  3 years ending DECISION_DATE; the full sample is a sensitivity only (it looks past the decision date).
- c: FY2024 market-based carbon intensity, every company must have boundary_match true.
  "log_z": z-score (population std) of ln(intensity). "rank_z": z-score of rank(intensity), average ties.
- u: data-trust score (`verigreen.data_trust`), "u" (main) or "u_high" (sensitivity).

Raw terms: R(x) = x'Sigma x (= K^2 x variance of the equal-weight portfolio), M(x) = mu'x, C(x) = c'x, U(x) = u'x.

Scaling: each term is divided by s_T, the population std of T(x) over the C(N, K) states with sum(x) = K, so every
scaled term has std 1 across feasible portfolios and lambda = 1 means "one portfolio-std of this term weighs as much
as one portfolio-std of risk". A term that is constant on the feasible set gets s_T = 1 (it cannot move the argmin).
Scales are fitted on one set of inputs and can be frozen and applied to another (`apply_scales`), so a naive-data
condition can be scored in the units of the trusted data.

Objective and QUBO (return is the only minus sign):
    f(x) = w_R R/s_R - w_M M/s_M + lambda_c C/s_C + lambda_u U/s_U
    E(x) = f(x) + P (sum(x) - K)^2 = sum_i h_i x_i + sum_{i<j} J_ij x_i x_j + P K^2      (x_i^2 = x_i)
    h_i  = w_R Sigma_ii/s_R - w_M mu_i/s_M + lambda_c c_i/s_C + lambda_u u_i/s_U + P (1 - 2K)
    J_ij = 2 w_R Sigma_ij/s_R + 2P

Budget penalty, exact, from enumerating all 2^N states: F_max = max f over feasible states, m_d = min f over states
with sum(x) - K = d. P* = max_{d != 0} (F_max - m_d) / d^2 is the smallest P for which no infeasible state is below
any feasible one (for sum(x) - K = d: E >= m_d + P d^2 > m_d + P* d^2 >= F_max). Default P = BUDGET_MARGIN * P*
(floor BUDGET_FLOOR if P* <= 0). `qubo_with_penalty` swaps in any other P without touching the objective.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from verigreen.data_trust import compute_data_trust, load_data_trust_inputs
from verigreen.returns import (TRADING_DAYS, annualised_covariance, daily_returns, estimation_window,
                               price_matrix, winsorise_returns)

ROOT = Path(__file__).resolve().parents[1]
CARBON_PATH = ROOT / "data" / "silver" / "carbon_intensity.csv"
GOLD_INPUTS_PATH = ROOT / "data" / "gold" / "qubo_inputs_fy2024.json"
GOLD_EXACT_PATH = ROOT / "data" / "gold" / "qubo_exact_fy2024.csv"
GOLD_TOP10_PATH = ROOT / "data" / "gold" / "exact_top10.csv"
GOLD_SUMMARY_PATH = ROOT / "data" / "gold" / "exact_summary_fy2024.json"

FISCAL_YEAR = 2024
K = 6
RISK_WEIGHT = 1.0
LAMBDA_CARBON_GRID = (0.0, 0.25, 0.5, 1.0, 2.0, 4.0)
LAMBDA_UNCERTAINTY_GRID = (0.0, 0.25, 0.5, 1.0, 2.0)
RETURN_WEIGHTS = (1.0, 0.0)          # 1 = mean-variance (main), 0 = minimum-variance (mu = 0) variant
BUDGET_MARGIN = 1.1
BUDGET_FLOOR = 0.1
NEAR_OPTIMAL_FRACTION = 0.05         # "within 5% of the optimum" = f - F_min <= 5% of (F_max - F_min)
MAX_ENUMERATED_ASSETS = 20

WINDOWS = ("main", "full")
CARBON_METHODS = ("log_z", "rank_z")
TRUST_SCORES = ("u", "u_high")
# input configurations: (window, carbon method, trust score). "main" is the headline; the rest are sensitivities.
INPUT_CONFIGS = {
    "main": ("main", "log_z", "u"),
    "full_sample": ("full", "log_z", "u"),
    "rank_carbon": ("main", "rank_z", "u"),
    "u_high": ("main", "log_z", "u_high"),
}


@dataclass(frozen=True)
class QuboConfig:
    return_weight: float = 1.0
    lambda_carbon: float = 1.0
    lambda_uncertainty: float = 0.0
    k: int = K
    risk_weight: float = RISK_WEIGHT


# Headline settings, fixed before any results were looked at; the full lambda grid is a sensitivity only.
MAIN_CONFIG = QuboConfig(return_weight=1.0, lambda_carbon=1.0, lambda_uncertainty=0.0, k=K)
TRUST_CONFIG = QuboConfig(return_weight=1.0, lambda_carbon=1.0, lambda_uncertainty=1.0, k=K)
# Added for stage G (2026-10-06), fixed before its results were looked at: weak carbon pressure, so heavy emitters can
# stay in the portfolio and their data errors can show up in its reported footprint.
LOW_PRESSURE_CONFIG = QuboConfig(return_weight=1.0, lambda_carbon=0.25, lambda_uncertainty=0.0, k=K)


@dataclass(frozen=True)
class QuboInputs:
    assets: tuple[str, ...]
    sigma: np.ndarray
    mu: np.ndarray
    c: np.ndarray
    u: np.ndarray
    intensity: np.ndarray | None = None   # tCO2e/EURm, reporting only (WACI); not used by the QUBO


@dataclass(frozen=True)
class Scales:
    risk: float
    ret: float
    carbon: float
    uncertainty: float
    k: int


@dataclass(frozen=True)
class ScaledInputs:
    assets: tuple[str, ...]
    sigma: np.ndarray
    mu: np.ndarray
    c: np.ndarray
    u: np.ndarray


@dataclass(frozen=True)
class Qubo:
    """f(x) = obj_h.x + x' obj_J x (obj_J strictly upper triangular), plus penalty * (sum(x) - k)^2."""
    assets: tuple[str, ...]
    obj_h: np.ndarray
    obj_J: np.ndarray
    k: int
    penalty: float
    p_star: float
    scales: Scales
    config: QuboConfig

    @property
    def h(self) -> np.ndarray:
        return self.obj_h + self.penalty * (1 - 2 * self.k)

    @property
    def J(self) -> np.ndarray:
        n = len(self.assets)
        return self.obj_J + 2 * self.penalty * np.triu(np.ones((n, n)), 1)

    @property
    def const(self) -> float:
        return float(self.penalty * self.k ** 2)


@dataclass(frozen=True)
class ExactResult:
    selected: tuple[str, ...]
    x: np.ndarray
    objective: float                 # f at the best feasible state (= its QUBO energy)
    feasible_min: float
    feasible_max: float
    gap_best_second: float           # f(second-best feasible) - f(best feasible)
    n_within_near_optimal: int       # feasible states with f - F_min <= NEAR_OPTIMAL_FRACTION * (F_max - F_min)
    global_min_feasible: bool
    max_feasible_energy: float
    min_infeasible_energy: float

    @property
    def feasible_range(self) -> float:
        return self.feasible_max - self.feasible_min

    @property
    def separated(self) -> bool:
        """Every feasible state has lower energy than every infeasible state."""
        return self.max_feasible_energy < self.min_infeasible_energy


# ---------------------------------------------------------------- inputs

def market_inputs(prices: pd.DataFrame, window: str = "main") -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """(Sigma, mu, winsorised returns) from long prices. Winsorisation quantiles come from inside the window."""
    rets = daily_returns(price_matrix(prices))
    if window == "main":
        rets = estimation_window(rets)
    elif window != "full":
        raise ValueError(f"window must be one of {WINDOWS}, got {window!r}")
    w = winsorise_returns(rets)
    return annualised_covariance(w), w.mean() * TRADING_DAYS, w


def fy_intensity(path: Path = CARBON_PATH, year: int = FISCAL_YEAR) -> pd.Series:
    """Market-based intensity per company for `year`. Raises unless every company has boundary_match true and a
    positive intensity: dropping a company would silently change the universe."""
    df = pd.read_csv(path)
    df = df[df["fiscal_year"] == year]
    bad = df[df["boundary_match"].astype(str).str.lower() != "true"]
    if len(bad):
        raise ValueError(f"boundary_match is not true for {sorted(bad['company_id'])} in {year}")
    s = df.set_index("company_id")["intensity_market_tco2e_per_eurm"].astype(float).sort_index()
    if s.isna().any() or (s <= 0).any():
        raise ValueError(f"missing or non-positive intensity: {sorted(s[~(s > 0)].index)}")
    return s


def _zscore(s: pd.Series) -> pd.Series:
    return (s - s.mean()) / s.std(ddof=0)


def carbon_scores(intensity: pd.Series, method: str = "log_z") -> pd.Series:
    if (intensity <= 0).any() or intensity.isna().any():
        raise ValueError("intensity must be positive")
    if method == "log_z":
        return _zscore(np.log(intensity))
    if method == "rank_z":
        return _zscore(intensity.rank(method="average"))
    raise ValueError(f"carbon method must be one of {CARBON_METHODS}, got {method!r}")


def trust_scores(column: str = "u") -> pd.Series:
    if column not in TRUST_SCORES:
        raise ValueError(f"trust score must be one of {TRUST_SCORES}, got {column!r}")
    return compute_data_trust(load_data_trust_inputs()).set_index("company_id")[column].astype(float).sort_index()


def assemble(sigma: pd.DataFrame, mu: pd.Series, c: pd.Series, u: pd.Series,
             intensity: pd.Series | None = None) -> QuboInputs:
    """Aligns everything on sorted company_id; raises if the asset sets differ."""
    assets = sorted(sigma.index)
    sets = {"sigma rows": set(sigma.index), "sigma cols": set(sigma.columns), "mu": set(mu.index),
            "c": set(c.index), "u": set(u.index)}
    if intensity is not None:
        sets["intensity"] = set(intensity.index)
    for name, s in sets.items():
        if s != set(assets):
            raise ValueError(f"asset set of {name} differs: {sorted(s ^ set(assets))}")
    return QuboInputs(
        assets=tuple(assets),
        sigma=sigma.loc[assets, assets].to_numpy(float),
        mu=mu.loc[assets].to_numpy(float),
        c=c.loc[assets].to_numpy(float),
        u=u.loc[assets].to_numpy(float),
        intensity=None if intensity is None else intensity.loc[assets].to_numpy(float),
    )


# ---------------------------------------------------------------- enumeration, scales, objective

@lru_cache(maxsize=4)
def enumerate_states(n: int) -> np.ndarray:
    """All 2^n bitstrings as a read-only (2^n, n) float array; column i is asset i."""
    if n > MAX_ENUMERATED_ASSETS:
        raise ValueError(f"refusing to enumerate 2^{n} states")
    X = ((np.arange(2 ** n)[:, None] >> np.arange(n)) & 1).astype(float)
    X.setflags(write=False)
    return X


def raw_terms(X: np.ndarray, inputs: QuboInputs) -> dict[str, np.ndarray]:
    """Unscaled R, M, C, U for each row of X."""
    return {"risk": np.einsum("si,ij,sj->s", X, inputs.sigma, X), "ret": X @ inputs.mu,
            "carbon": X @ inputs.c, "uncertainty": X @ inputs.u}


def fit_scales(inputs: QuboInputs, k: int = K) -> Scales:
    """Population std of each raw term over the states with exactly k assets (1.0 where that std is 0)."""
    X = enumerate_states(len(inputs.assets))
    feasible = X[X.sum(axis=1) == k]
    stds = {name: float(t.std()) for name, t in raw_terms(feasible, inputs).items()}
    return Scales(**{name: (s if s > 1e-12 else 1.0) for name, s in stds.items()}, k=k)


def apply_scales(scales: Scales, inputs: QuboInputs) -> ScaledInputs:
    """Divides each input by its (possibly frozen) scale."""
    return ScaledInputs(inputs.assets, inputs.sigma / scales.risk, inputs.mu / scales.ret,
                        inputs.c / scales.carbon, inputs.u / scales.uncertainty)


def objective_direct(x, inputs: QuboInputs, scales: Scales, config: QuboConfig) -> float:
    """f(x) straight from the formula, independent of the QUBO coefficients (used to test them)."""
    x = np.asarray(x, dtype=float)
    return float(config.risk_weight * (x @ inputs.sigma @ x) / scales.risk
                 - config.return_weight * (inputs.mu @ x) / scales.ret
                 + config.lambda_carbon * (inputs.c @ x) / scales.carbon
                 + config.lambda_uncertainty * (inputs.u @ x) / scales.uncertainty)


# ---------------------------------------------------------------- QUBO

def _quadratic_form(X: np.ndarray, h: np.ndarray, J: np.ndarray, const: float = 0.0) -> np.ndarray:
    return X @ h + np.einsum("si,ij,sj->s", X, J, X) + const


def budget_threshold(f: np.ndarray, weights: np.ndarray, k: int) -> float:
    """P* = max_{d != 0} (F_max - m_d) / d^2 (see module docstring)."""
    d = weights - k
    f_max = f[d == 0].max()
    return float(max((f_max - f[d == dd].min()) / dd ** 2 for dd in np.unique(d) if dd != 0))


def exact_penalty(p_star: float) -> float:
    return BUDGET_MARGIN * p_star if p_star > 0 else BUDGET_FLOOR


def build_qubo(inputs: QuboInputs, config: QuboConfig = MAIN_CONFIG, scales: Scales | None = None,
               penalty: float | None = None) -> Qubo:
    """QUBO with re-fitted scales (default) or frozen ones, and the exact budget penalty unless `penalty` is given."""
    scales = scales if scales is not None else fit_scales(inputs, config.k)
    if scales.k != config.k:
        raise ValueError(f"scales were fitted for k={scales.k}, config has k={config.k}")
    s = apply_scales(scales, inputs)
    obj_h = (config.risk_weight * np.diag(s.sigma) - config.return_weight * s.mu
             + config.lambda_carbon * s.c + config.lambda_uncertainty * s.u)
    obj_J = 2 * config.risk_weight * np.triu(s.sigma, 1)
    X = enumerate_states(len(inputs.assets))
    p_star = budget_threshold(_quadratic_form(X, obj_h, obj_J), X.sum(axis=1), config.k)
    q = Qubo(inputs.assets, obj_h, obj_J, config.k, exact_penalty(p_star), p_star, scales, config)
    return q if penalty is None else qubo_with_penalty(q, penalty)


def qubo_with_penalty(qubo: Qubo, penalty: float) -> Qubo:
    """Same objective, different budget penalty (e.g. a smaller practical one for QAOA). p_star is kept."""
    if penalty < 0:
        raise ValueError("penalty must be non-negative")
    return replace(qubo, penalty=float(penalty))


def qubo_energy(qubo: Qubo, X) -> np.ndarray:
    X = np.atleast_2d(np.asarray(X, dtype=float))
    return _quadratic_form(X, qubo.h, qubo.J, qubo.const)


def ranked_feasible(qubo: Qubo) -> tuple[np.ndarray, np.ndarray]:
    """(states, energies) of the C(N, k) feasible states, best first (stable sort, so ties keep enumeration order)."""
    X = enumerate_states(len(qubo.assets))
    feasible = X.sum(axis=1) == qubo.k
    Xf, Ef = X[feasible], qubo_energy(qubo, X)[feasible]
    order = np.argsort(Ef, kind="stable")
    return Xf[order].astype(int), Ef[order]


def near_optimal_count(energies: np.ndarray, fraction: float) -> int:
    """Feasible states with f - F_min <= fraction x (F_max - F_min); `energies` are the feasible ones."""
    f_min, f_max = energies.min(), energies.max()
    return int((energies - f_min <= fraction * (f_max - f_min)).sum())


def exact_optimum(qubo: Qubo) -> ExactResult:
    """Brute force over all 2^N states. Reports the best feasible portfolio and QAOA-readiness statistics."""
    X = enumerate_states(len(qubo.assets))
    E = qubo_energy(qubo, X)
    feasible = X.sum(axis=1) == qubo.k
    Xr, Ef = ranked_feasible(qubo)
    best = Xr[0]
    f_min, f_max = float(Ef[0]), float(Ef[-1])
    return ExactResult(
        selected=tuple(a for a, b in zip(qubo.assets, best) if b),
        x=best,
        objective=f_min,
        feasible_min=f_min,
        feasible_max=f_max,
        gap_best_second=float(Ef[1] - Ef[0]),
        n_within_near_optimal=near_optimal_count(Ef, NEAR_OPTIMAL_FRACTION),
        global_min_feasible=bool(feasible[np.argmin(E)]),
        max_feasible_energy=f_max,
        min_infeasible_energy=float(E[~feasible].min()),
    )


# ---------------------------------------------------------------- gold export / loader

def _floats(a) -> list:
    return np.asarray(a, dtype=float).tolist()


def gold_payload(assets: tuple[str, ...], windows: dict[str, dict], intensity: pd.Series,
                 carbon: dict[str, pd.Series], trust: dict[str, pd.Series],
                 configs: dict[str, dict]) -> dict:
    """JSON-ready frozen inputs. `windows[name]` has sigma (DataFrame), mu (Series), start, end, n_days."""
    a = list(assets)
    return {
        "description": "Frozen FY2024 QUBO inputs (verigreen/qubo.py). Sigma and mu are annualised (x252) from "
                       "1/99 winsorised daily simple returns; no price is stored.",
        "fiscal_year": FISCAL_YEAR,
        "k": K,
        "assets": a,
        "windows": {name: {"start": w["start"], "end": w["end"], "n_days": int(w["n_days"]),
                           "sigma": _floats(w["sigma"].loc[a, a]), "mu": _floats(w["mu"].loc[a])}
                    for name, w in windows.items()},
        "intensity_market_tco2e_per_eurm": _floats(intensity.loc[a]),
        "carbon": {m: _floats(s.loc[a]) for m, s in carbon.items()},
        "trust": {t: _floats(s.loc[a]) for t, s in trust.items()},
        "qubo_configs": {"MAIN_CONFIG": asdict(MAIN_CONFIG), "TRUST_CONFIG": asdict(TRUST_CONFIG),
                         "LOW_PRESSURE_CONFIG": asdict(LOW_PRESSURE_CONFIG)},
        "input_configs": configs,
    }


@dataclass(frozen=True)
class GoldInputs:
    raw: dict

    @property
    def assets(self) -> tuple[str, ...]:
        return tuple(self.raw["assets"])

    def inputs(self, name: str = "main") -> QuboInputs:
        window, carbon, trust = INPUT_CONFIGS[name]
        w = self.raw["windows"][window]
        return QuboInputs(self.assets, np.array(w["sigma"]), np.array(w["mu"]),
                          np.array(self.raw["carbon"][carbon]), np.array(self.raw["trust"][trust]),
                          np.array(self.raw["intensity_market_tco2e_per_eurm"]))

    def scales(self, name: str = "main") -> Scales:
        return Scales(**self.raw["input_configs"][name]["scales"])

    def p_star(self, name: str, qubo_config: str) -> float:
        return float(self.raw["input_configs"][name]["p_star"][qubo_config])


def load_gold_inputs(path: Path = GOLD_INPUTS_PATH) -> GoldInputs:
    return GoldInputs(json.loads(Path(path).read_text(encoding="utf-8")))
