"""Exact (brute-force) optimum of the FY2024 QUBO over the lambda grid, plus the frozen gold inputs.

1. Builds the inputs from the source files (prices_cleaned.parquet, git-ignored; carbon_intensity.csv;
   data_trust_inputs.csv) and writes data/gold/qubo_inputs_fy2024.json.
2. Reloads that JSON and computes every result from it, so data/gold/qubo_exact_fy2024.csv is reproducible from
   committed files alone.
Input configurations: main, full_sample, rank_carbon, u_high (see verigreen.qubo.INPUT_CONFIGS); each is scaled on its
own inputs. Every grid point uses the exact budget penalty and asserts that all 2^15 states are separated.
Exact classical solver only: no QAOA, no claim of quantum advantage.

Run: uv run python scripts/report_qubo.py
"""
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verigreen.qubo import (CARBON_METHODS, GOLD_EXACT_PATH, GOLD_INPUTS_PATH, GOLD_SUMMARY_PATH,  # noqa: E402
                            GOLD_TOP10_PATH, INPUT_CONFIGS, K, LAMBDA_CARBON_GRID, LAMBDA_UNCERTAINTY_GRID,
                            MAIN_CONFIG, NEAR_OPTIMAL_FRACTION, RETURN_WEIGHTS, TRUST_CONFIG, TRUST_SCORES, WINDOWS,
                            QuboConfig, assemble, build_qubo, carbon_scores, enumerate_states, exact_optimum,
                            fit_scales, fy_intensity, gold_payload, load_gold_inputs, market_inputs,
                            near_optimal_count, ranked_feasible, trust_scores)

PRICES = ROOT / "data/bronze/prices_cleaned.parquet"
TOP_N = 10
NEAR_FRACTIONS = (0.01, 0.05)
# (headline, input configuration) blocks for the top-N table and the random-sampling baseline
TOP_BLOCKS = (("MAIN_CONFIG", "main"), ("TRUST_CONFIG", "main"), ("TRUST_CONFIG", "u_high"))
HEADLINES = {
    "MAIN_CONFIG": MAIN_CONFIG,
    "TRUST_CONFIG": TRUST_CONFIG,
    "MAIN_CONFIG_min_variance": replace(MAIN_CONFIG, return_weight=0.0),
    "TRUST_CONFIG_min_variance": replace(TRUST_CONFIG, return_weight=0.0),
}


def source_payload() -> dict:
    prices = pd.read_parquet(PRICES)
    intensity = fy_intensity()
    carbon = {m: carbon_scores(intensity, m) for m in CARBON_METHODS}
    trust = {t: trust_scores(t) for t in TRUST_SCORES}
    windows = {}
    for w in WINDOWS:
        sigma, mu, rets = market_inputs(prices, w)
        windows[w] = {"sigma": sigma, "mu": mu, "start": str(rets.index.min().date()),
                      "end": str(rets.index.max().date()), "n_days": len(rets)}
    configs, assets = {}, None
    for name, (w, cm, t) in INPUT_CONFIGS.items():
        inp = assemble(windows[w]["sigma"], windows[w]["mu"], carbon[cm], trust[t], intensity)
        assets = inp.assets
        scales = fit_scales(inp, K)
        configs[name] = {"window": w, "carbon": cm, "trust": t, "scales": asdict(scales),
                         "p_star": {label: build_qubo(inp, cfg, scales).p_star for label, cfg in HEADLINES.items()}}
    return gold_payload(assets, windows, intensity, carbon, trust, configs)


def headline_label(cfg: QuboConfig) -> str:
    return next((label for label, h in HEADLINES.items() if h == cfg), "")


def tier_counts(u: np.ndarray, x: np.ndarray) -> str:
    """Selected assets per trust tier, e.g. '0.00:1; 0.25:2; 0.50:2; 0.75:1' (all four tiers always listed)."""
    return "; ".join(f"{t:.2f}:{int(((u == t) & (x == 1)).sum())}" for t in (0.0, 0.25, 0.5, 0.75))


def compact_tiers(s: str) -> str:
    return "/".join(part.split(":")[1] for part in s.split("; "))


def grid_rows(gold) -> pd.DataFrame:
    """Tier counts are reported under BOTH u and u_high for every row, so selections from the u and u_high
    configurations can be compared on one common scale (tiers, not fine rank order)."""
    u_all = {t: np.array(gold.raw["trust"][t]) for t in TRUST_SCORES}
    assert all(set(np.unique(v)) <= {0.0, 0.25, 0.5, 0.75} for v in u_all.values())
    rows = []
    for name, (window, carbon, trust) in INPUT_CONFIGS.items():
        inp, scales = gold.inputs(name), gold.scales(name)
        for rw in RETURN_WEIGHTS:
            for lc in LAMBDA_CARBON_GRID:
                for lu in LAMBDA_UNCERTAINTY_GRID:
                    cfg = QuboConfig(return_weight=rw, lambda_carbon=lc, lambda_uncertainty=lu, k=K)
                    q = build_qubo(inp, cfg, scales)
                    r = exact_optimum(q)
                    assert r.separated and r.global_min_feasible, (name, cfg)
                    x = r.x
                    risk = float(x @ inp.sigma @ x)
                    rows.append({
                        "input_config": name, "window": window, "carbon_method": carbon, "trust_score": trust,
                        "return_weight": rw, "lambda_carbon": lc, "lambda_uncertainty": lu,
                        "headline": headline_label(cfg),
                        "selected": ";".join(r.selected), "n_selected": int(x.sum()),
                        "tiers_u": tier_counts(u_all["u"], x), "tiers_u_high": tier_counts(u_all["u_high"], x),
                        "risk_xSx": risk, "eq_weight_vol": np.sqrt(risk) / K,
                        "return_mu_x": float(inp.mu @ x), "eq_weight_return": float(inp.mu @ x) / K,
                        "carbon_c_x": float(inp.c @ x), "uncertainty_u_x": float(inp.u @ x),
                        "waci_eq_weight_tco2e_per_eurm": float(inp.intensity[x == 1].mean()),
                        "objective": r.objective, "p_star": q.p_star, "penalty": q.penalty,
                        "feasible_range": r.feasible_range, "penalty_over_range": q.penalty / r.feasible_range,
                        "gap_best_second": r.gap_best_second, "n_within_5pct": r.n_within_near_optimal,
                        "separated": r.separated,
                    })
    return pd.DataFrame(rows)


def short(sel: str) -> str:
    return " ".join(s.split(".")[0][:5] for s in sel.split(";"))


def top_rows(gold, n: int = TOP_N) -> pd.DataFrame:
    """The n best feasible portfolios per TOP_BLOCKS entry. gap_pct_of_range = (f - F_min) / (F_max - F_min) x 100."""
    u_all = {t: np.array(gold.raw["trust"][t]) for t in TRUST_SCORES}
    rows = []
    for label, name in TOP_BLOCKS:
        inp = gold.inputs(name)
        Xr, Ef = ranked_feasible(build_qubo(inp, HEADLINES[label], gold.scales(name)))
        f_range = Ef[-1] - Ef[0]
        for rank, (x, e) in enumerate(zip(Xr[:n], Ef[:n]), start=1):
            rows.append({
                "headline": label, "input_config": name, "trust_score": INPUT_CONFIGS[name][2], "rank": rank,
                "selected": ";".join(a for a, b in zip(inp.assets, x) if b), "energy": float(e),
                "gap_to_optimum": float(e - Ef[0]), "gap_pct_of_range": float(100 * (e - Ef[0]) / f_range),
                "waci_eq_weight_tco2e_per_eurm": float(inp.intensity[x == 1].mean()),
                "tiers_u": tier_counts(u_all["u"], x), "tiers_u_high": tier_counts(u_all["u_high"], x),
            })
    return pd.DataFrame(rows)


def sampling_baseline(gold) -> dict:
    """Share of portfolios within each NEAR_FRACTIONS of the optimum: of the C(15, 6) feasible states (uniform random
    feasible portfolio) and of all 2^15 bitstrings (uniform random bitstring; infeasible ones are never near-optimal,
    since every one is above every feasible state)."""
    n_all = len(enumerate_states(len(gold.assets)))
    out = {}
    for label, name in TOP_BLOCKS:
        q = build_qubo(gold.inputs(name), HEADLINES[label], gold.scales(name))
        assert exact_optimum(q).separated
        _, Ef = ranked_feasible(q)
        near = {}
        for frac in NEAR_FRACTIONS:
            c = near_optimal_count(Ef, frac)
            near[f"{frac:g}"] = {"count": c, "share_of_feasible": c / len(Ef), "share_of_all_states": c / n_all}
        out[f"{label}|{name}"] = {"headline": label, "input_config": name, "n_feasible": len(Ef), "n_states": n_all,
                                  "feasible_range": float(Ef[-1] - Ef[0]), "near_optimal": near,
                                  "p_optimum_random_feasible": 1 / len(Ef), "p_optimum_random_bitstring": 1 / n_all}
    return out


def stability(df: pd.DataFrame, assets: tuple[str, ...]) -> dict:
    """Over the grid rows of qubo_exact_fy2024.csv: assets in every optimum, in none, and how many assets each optimum
    swaps relative to the main-inputs MAIN_CONFIG optimum (count of grid points per number of swaps)."""
    ref = set(df[(df.input_config == "main") & (df.headline == "MAIN_CONFIG")].iloc[0]["selected"].split(";"))
    out ={"reference": "main inputs, MAIN_CONFIG", "reference_selection": sorted(ref)}
    groups = [(name, df[df.input_config == name]) for name in INPUT_CONFIGS] + [("all", df)]
    for name, g in groups:
        sels = [set(s.split(";")) for s in g["selected"]]
        swaps = pd.Series([len(s - ref) for s in sels]).value_counts().sort_index()
        out[name] = {"n_grid_points": len(g),
                     "in_every_optimum": sorted(set.intersection(*sels)),
                     "in_no_optimum": sorted(set(assets) - set.union(*sels)),
                     "swaps_vs_reference": {int(k): int(v) for k, v in swaps.items()}}
    return out


def main() -> None:
    payload = source_payload()
    GOLD_INPUTS_PATH.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    gold = load_gold_inputs()
    df = grid_rows(gold)
    df.to_csv(GOLD_EXACT_PATH, index=False, float_format="%.10g", lineterminator="\n")
    print(f"wrote {GOLD_INPUTS_PATH.relative_to(ROOT)} and {GOLD_EXACT_PATH.relative_to(ROOT)} ({len(df)} rows); "
          "all 2^15 states separated at every grid point")
    top = top_rows(gold)
    top.to_csv(GOLD_TOP10_PATH, index=False, float_format="%.10g", lineterminator="\n")
    summary = {"description": "Random-sampling baseline and grid stability for the FY2024 exact optimum "
                              "(scripts/report_qubo.py). 'Within x' = f - F_min <= x * (F_max - F_min).",
               "sampling_baseline": sampling_baseline(gold), "stability": stability(df, gold.assets)}
    GOLD_SUMMARY_PATH.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {GOLD_TOP10_PATH.relative_to(ROOT)} ({len(top)} rows) and {GOLD_SUMMARY_PATH.relative_to(ROOT)}\n")

    for w, v in payload["windows"].items():
        print(f"window {w}: {v['start']} .. {v['end']} ({v['n_days']} days)")
    print("\nfitted scales (population std over the 5,005 feasible states):")
    print(pd.DataFrame({n: c["scales"] for n, c in payload["input_configs"].items()}).T.round(4).to_string())

    print("\n=== headline settings (exact optimum) ===")
    h = df[df.headline != ""]
    cols = ["input_config", "headline", "selected", "tiers_u", "tiers_u_high", "eq_weight_vol", "eq_weight_return",
            "waci_eq_weight_tco2e_per_eurm", "p_star"]
    out = h[cols].copy()
    out["selected"] = out["selected"].map(short)
    for c in ("tiers_u", "tiers_u_high"):
        out[c] = out[c].map(compact_tiers)
    print("tiers = number selected with trust score 0 / 0.25 / 0.5 / 0.75")
    print(out.round(4).to_string(index=False))

    print(f"\n=== QAOA readiness, main inputs (report only; 'within 5%' = f - F_min <= "
          f"{NEAR_OPTIMAL_FRACTION:.0%} of F_max - F_min) ===")
    m = df[(df.input_config == "main") & (df.headline != "")]
    print(m[["headline", "feasible_range", "p_star", "penalty", "penalty_over_range", "gap_best_second",
             "n_within_5pct"]].round(4).to_string(index=False))

    print("\n=== selection over the grid, main inputs ===")
    for rw in RETURN_WEIGHTS:
        g = df[(df.input_config == "main") & (df.return_weight == rw)]
        tab = g.pivot(index="lambda_carbon", columns="lambda_uncertainty", values="selected").map(short)
        print(f"return_weight = {rw:g}; rows lambda_carbon, columns lambda_uncertainty")
        print(tab.to_string(), "\n")

    print("=== sensitivities vs main (same return_weight and lambdas) ===")
    key = ["return_weight", "lambda_carbon", "lambda_uncertainty"]
    base = df[df.input_config == "main"].set_index(key)
    for name in INPUT_CONFIGS:
        if name == "main":
            continue
        alt = df[df.input_config == name].set_index(key)
        same = (alt["selected"] == base["selected"])
        line = f"{name}: identical selection at {int(same.sum())} of {len(same)} grid points"
        if name == "u_high":
            lu = alt.index.get_level_values("lambda_uncertainty") > 0
            sel = same[lu]
            t_u = (alt["tiers_u"] == base["tiers_u"])[lu]
            t_h = (alt["tiers_u_high"] == base["tiers_u_high"])[lu]
            line += (f"; with lambda_uncertainty > 0: identical names at {int(sel.sum())} of {len(sel)}, "
                     f"identical tier composition measured in u at {int(t_u.sum())}, in u_high at {int(t_h.sum())}")
        print(line)
        for label in HEADLINES:
            a, b = alt[alt.headline == label].iloc[0], base[base.headline == label].iloc[0]
            print(f"  {label}: {short(b.selected)}  ->  {short(a.selected)}"
                  + ("" if a.selected == b.selected else "   (differs)"))

    print(f"\n=== top {TOP_N} feasible portfolios (gap = % of feasible range) ===")
    t = top.copy()
    t["selected"] = t["selected"].map(short)
    for c in ("tiers_u", "tiers_u_high"):
        t[c] = t[c].map(compact_tiers)
    for (label, name), g in t.groupby(["headline", "input_config"], sort=False):
        print(f"{label}, {name} inputs")
        print(g[["rank", "selected", "gap_pct_of_range", "waci_eq_weight_tco2e_per_eurm", "tiers_u",
                 "tiers_u_high"]].round(3).to_string(index=False), "\n")

    print("=== random-sampling baseline (share of portfolios within x of the optimum) ===")
    for key, b in summary["sampling_baseline"].items():
        parts = [f"within {float(f):.0%}: {v['count']} = {v['share_of_feasible']:.4%} of feasible, "
                 f"{v['share_of_all_states']:.4%} of all 2^15" for f, v in b["near_optimal"].items()]
        print(f"{key}: " + "; ".join(parts))

    print("\n=== grid stability (vs main-inputs MAIN_CONFIG optimum) ===")
    st = summary["stability"]
    print("reference:", short(";".join(st["reference_selection"])))
    for name in [*INPUT_CONFIGS, "all"]:
        s = st[name]
        print(f"{name} ({s['n_grid_points']} points): in every optimum {short(';'.join(s['in_every_optimum']))}; "
              f"in none {short(';'.join(s['in_no_optimum'])) if s['in_no_optimum'] else '-'}; "
              f"swaps vs reference {s['swaps_vs_reference']}")


if __name__ == "__main__":
    main()
