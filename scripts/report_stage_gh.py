"""Stages G (reduced), H (sizing and simulation of the 8-asset instance) and H2 (illustrative noise preview).

Simulator only. Settings were agreed before any run (docs/decisions_log.md, 2026-10-06 "Stages G / H / H2" entry).
The raw-vs-trusted result itself comes from exact enumeration (stage G0) and the classical relaxation; QAOA is shown
reproducing it.

Run: uv run python scripts/report_stage_gh.py --stage G | H | H2 | H3
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verigreen.qaoa import (distribution_metrics, penalty_variants, product_probs, random_baselines,  # noqa: E402
                            reference, regularise, selection)
from verigreen.qubo import enumerate_states, exact_optimum  # noqa: E402
from verigreen.stage_gh import (EPS, G_RUNS_PATH, G_SUMMARY_PATH, H2_NOISE_PATH, H3_INSTANCE_PATH,  # noqa: E402
                                H3_NOISE_PATH, H3_SIMULATION_PATH, H3_SIZING_PATH, H3_SUMMARY_PATH, H_INSTANCE_PATH,
                                H_SIMULATION_PATH, H_SIZING_PATH, add_main_comparison, baseline_row, build_cases,
                                build_instance, build_residual, coupling_maps, noisy_probs, run_case, sizing_circuit,
                                sizing_stats, summarise_runs, top_feasible, warm_restart)

H_RESTARTS = tuple(range(10))
H_SEEDS = range(20)
NOISE_2Q = (0.0, 0.005, 0.01, 0.02)
NOISE_SHOTS = 65536
NOISE_SEED = 20261006


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def write(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False, float_format="%.10g", lineterminator="\n")


def stage_g() -> None:
    runs, summary = [], []
    for case_id, case in build_cases().items():
        log(f"case {case_id}")
        r, s = run_case(case, log)
        runs += r
        summary += s
        write(pd.DataFrame(runs), G_RUNS_PATH)
    df = add_main_comparison(pd.DataFrame(summary))
    write(df, G_SUMMARY_PATH)
    cols = ["case_id", "p", "exact_selection", "rounded_is_exact_optimum", "selected_top_feasible",
            "selection_result_reproduced", "selected_p_opt", "selected_near_given_feasible", "median_p_opt",
            "median_near_given_feasible", "n_beat_p0_p_opt", "n_top_is_exact_optimum"]
    with pd.option_context("display.width", 250, "display.max_columns", 40, "display.max_colwidth", 70):
        print(df[cols].to_string(index=False, float_format=lambda v: f"{v:.4g}"))


def stage_h() -> None:
    inst = build_instance()
    q = penalty_variants(inst.qubo)["practical"]
    ref = reference(q)
    exact = exact_optimum(inst.qubo)
    n = len(inst.assets)
    log(f"instance: {n} assets {inst.assets}, K = {q.k}, P* = {inst.qubo.p_star:.4f}, practical P = {q.penalty:.4f}")
    base = random_baselines(ref)
    inst_df = pd.DataFrame({"asset": inst.assets, "index_in_15": inst.indices, "c_star_15_asset": inst.c_full,
                            "c_star_8_asset": inst.c_sub, "in_exact_optimum": [a in exact.selected for a in inst.assets]})
    write(inst_df, H_INSTANCE_PATH)

    # sizing: p = 0 baseline and p = 1, stand-in coupling maps
    sizing = []
    for p in (0, 1):
        circuit = sizing_circuit(inst, p)
        for name, cm in coupling_maps(n).items():
            row = {"p": p, "coupling": name, **sizing_stats(circuit, cm, H_SEEDS)}
            sizing.append(row)
            log(f"sizing p={p} {name}: depth {row['depth_median']:.0f} ({row['depth_min']}-{row['depth_max']}), "
                f"cz {row['cz_median']:.0f} ({row['cz_min']}-{row['cz_max']})")
    write(pd.DataFrame(sizing), H_SIZING_PATH)

    # simulated P(opt): random baselines, warm initial state (p = 0), warm-start QAOA p = 1, 10 restarts
    c_eps = regularise(inst.c_sub, EPS)
    p0 = baseline_row(ref, product_probs(c_eps))
    feas = ref.feasible / ref.feasible.sum()
    uniform = np.full(len(ref.energy), 1 / len(ref.energy))
    rows = [{"row": "random_feasible", **baseline_row(ref, feas)}, {"row": "uniform_superposition", **baseline_row(ref, uniform)},
            {"row": "warm_p0", **p0}]
    runs = []
    for r in H_RESTARTS:
        runs.append({"row": "warm_p1_restart", **warm_restart(q, ref, c_eps, 1, r)})
        log(f"H restart {r}: P(opt) {runs[-1]['sv_p_opt']:.3f}, shot {runs[-1]['shot_p_opt']:.3f}")
    s = summarise_runs(pd.DataFrame(runs), p0)
    for r in runs:
        r["selected"] = r["restart"] == s["selected_restart"]
    sim = pd.concat([pd.DataFrame(rows), pd.DataFrame(runs)], ignore_index=True)
    sim["n_assets"], sim["k"], sim["n_feasible"], sim["n_near"] = n, q.k, base["n_feasible"], base["n_near"]
    sim["exact_selection"] = ";".join(exact.selected)
    sim["exact_gap_best_second_pct_of_range"] = 100 * exact.gap_best_second / exact.feasible_range
    write(sim, H_SIMULATION_PATH)
    write(pd.DataFrame([{**s, "n_feasible": base["n_feasible"], "n_near": base["n_near"]}]),
          H_SIMULATION_PATH.with_name("qaoa_stage_h_summary_fy2024.csv"))
    log(f"exact optimum {exact.selected}; random feasible P(opt) {1 / base['n_feasible']:.3%}; warm p=0 "
        f"{p0['sv_p_opt']:.3%}; selected p=1 {s['selected_p_opt']:.3%} (shots {s['selected_shot_p_opt']:.3%}), median "
        f"{s['median_p_opt']:.3%}, {s['n_beat_p0_p_opt']}/10 beat p=0")


def stage_h2() -> None:
    inst = build_instance()
    q = penalty_variants(inst.qubo)["practical"]
    ref = reference(q)
    n = len(inst.assets)
    sim = pd.read_csv(H_SIMULATION_PATH)
    sel = sim[(sim["row"] == "warm_p1_restart") & (sim["selected"] == True)].iloc[0]  # noqa: E712
    point = np.array([float(v) for v in sel["optimal_point"].split()])
    maps = coupling_maps(n)
    sizing = pd.read_csv(H_SIZING_PATH)
    rows = []
    for p in (0, 1):
        circuit = sizing_circuit(inst, p, point if p else None)
        for cname in ("all_to_all", "grid_2x4"):
            best = int(sizing[(sizing["p"] == p) & (sizing["coupling"] == cname)].iloc[0]["best_seed"])
            for p2 in NOISE_2Q:
                p1 = p2 / 10
                probs, g = noisy_probs(circuit, maps[cname], p2, p1, NOISE_SHOTS, NOISE_SEED, best)
                m = distribution_metrics(probs, ref)
                top, top_p = top_feasible(probs, ref)
                rows.append({"p": p, "coupling": cname, "p_2q": p2, "p_1q": p1, "shots": NOISE_SHOTS, "seed": NOISE_SEED,
                             "transpile_seed": best, **g, **m, "p_opt_stderr": float(np.sqrt(m["p_opt"] * (1 - m["p_opt"]) / NOISE_SHOTS)),
                             "top_feasible": top, "top_feasible_prob": top_p,
                             "top_is_exact_optimum": top == selection(ref, ref.opt_index)})
                log(f"p={p} {cname} p2={p2:.3f}: P(opt) {m['p_opt']:.3%}, near {m['near_mass']:.3%}, "
                    f"feasible {m['feasible_share']:.1%}, cz {g['cz']}")
    df = pd.DataFrame(rows)
    write(df, H2_NOISE_PATH)


def stage_h3() -> None:
    """Residual subproblem: variable fixing from the MAIN relaxation, then sizing, simulation and the noise sweep."""
    res = build_residual()
    inst = res.instance
    q = penalty_variants(inst.qubo)["practical"]
    ref = reference(q)
    n = len(inst.assets)
    from verigreen.qubo import exact_optimum as _exact
    exact = _exact(inst.qubo)
    opt15 = _exact(res.full_qubo)
    assert tuple(sorted(exact.selected + res.fixed_one)) == tuple(sorted(opt15.selected)), "residual optimum != 15-asset optimum"
    log(f"fixed to 1: {res.fixed_one}; fixed to 0: {len(res.fixed_zero)} assets; undecided {inst.assets}, K_res = {res.k_res}")
    log(f"P* = {inst.qubo.p_star:.4f}, practical P = {q.penalty:.4f}; residual optimum {exact.selected} "
        f"(+ fixed = the 15-asset optimum); best-to-second gap {100 * exact.gap_best_second / exact.feasible_range:.1f}% of range")
    base = random_baselines(ref)
    rows = ([{"asset": a, "role": "fixed_to_1", "c_star_15_asset": np.nan, "c_star_residual": np.nan}
             for a in res.fixed_one]
            + [{"asset": a, "role": "fixed_to_0", "c_star_15_asset": 0.0, "c_star_residual": np.nan} for a in res.fixed_zero]
            + [{"asset": a, "role": "undecided", "c_star_15_asset": c15, "c_star_residual": cr}
               for a, c15, cr in zip(inst.assets, inst.c_full, inst.c_sub)])
    df = pd.DataFrame(rows)
    df["in_exact_optimum"] = df["asset"].isin(opt15.selected)
    df["k_res"], df["offset"], df["p_star"], df["practical_penalty"] = res.k_res, res.offset, inst.qubo.p_star, q.penalty
    write(df, H3_INSTANCE_PATH)

    sizing = []
    for p in (0, 1):
        circuit = sizing_circuit(inst, p)
        for name, cm in coupling_maps(n).items():
            row = {"p": p, "coupling": name, **sizing_stats(circuit, cm, H_SEEDS)}
            sizing.append(row)
            log(f"sizing p={p} {name}: depth {row['depth_median']:.0f} ({row['depth_min']}-{row['depth_max']}), "
                f"cz {row['cz_median']:.0f} ({row['cz_min']}-{row['cz_max']})")
    sizing = pd.DataFrame(sizing)
    write(sizing, H3_SIZING_PATH)

    c_eps = regularise(inst.c_sub, EPS)
    p0 = baseline_row(ref, product_probs(c_eps))
    feas = ref.feasible / ref.feasible.sum()
    uniform = np.full(len(ref.energy), 1 / len(ref.energy))
    out = [{"row": "random_feasible", **baseline_row(ref, feas)}, {"row": "uniform_superposition", **baseline_row(ref, uniform)},
           {"row": "warm_p0", **p0}]
    runs = []
    for r in H_RESTARTS:
        runs.append({"row": "warm_p1_restart", **warm_restart(q, ref, c_eps, 1, r)})
        log(f"H3 restart {r}: P(opt) {runs[-1]['sv_p_opt']:.3f}, shot {runs[-1]['shot_p_opt']:.3f}")
    s = summarise_runs(pd.DataFrame(runs), p0)
    for r in runs:
        r["selected"] = r["restart"] == s["selected_restart"]
    sim = pd.concat([pd.DataFrame(out), pd.DataFrame(runs)], ignore_index=True)
    sim["n_assets"], sim["k"], sim["n_feasible"], sim["n_near"] = n, q.k, base["n_feasible"], base["n_near"]
    sim["exact_selection"] = ";".join(exact.selected)
    sim["exact_gap_best_second_pct_of_range"] = 100 * exact.gap_best_second / exact.feasible_range
    write(sim, H3_SIMULATION_PATH)
    write(pd.DataFrame([{**s, "n_feasible": base["n_feasible"], "n_near": base["n_near"]}]), H3_SUMMARY_PATH)
    log(f"random feasible P(opt) {1 / base['n_feasible']:.2%}; warm p=0 {p0['sv_p_opt']:.2%}; selected p=1 "
        f"{s['selected_p_opt']:.2%} (shots {s['selected_shot_p_opt']:.2%}), median {s['median_p_opt']:.2%}, "
        f"{s['n_beat_p0_p_opt']}/10 beat p=0")

    sel = next(r for r in runs if r["selected"])
    point = np.array([float(v) for v in sel["optimal_point"].split()])
    maps = coupling_maps(n)
    noise = []
    for p in (0, 1):
        circuit = sizing_circuit(inst, p, point if p else None)
        for cname, cm in maps.items():
            best = int(sizing[(sizing["p"] == p) & (sizing["coupling"] == cname)].iloc[0]["best_seed"])
            for p2 in NOISE_2Q:
                probs, g = noisy_probs(circuit, cm, p2, p2 / 10, NOISE_SHOTS, NOISE_SEED, best)
                m = distribution_metrics(probs, ref)
                top, top_p = top_feasible(probs, ref)
                noise.append({"p": p, "coupling": cname, "p_2q": p2, "p_1q": p2 / 10, "shots": NOISE_SHOTS,
                              "seed": NOISE_SEED, "transpile_seed": best, **g, **m,
                              "p_opt_stderr": float(np.sqrt(m["p_opt"] * (1 - m["p_opt"]) / NOISE_SHOTS)),
                              "top_feasible": top, "top_feasible_prob": top_p,
                              "top_is_exact_optimum": top == selection(ref, ref.opt_index)})
                log(f"noise p={p} {cname} p2={p2:.3f}: P(opt) {m['p_opt']:.2%}, feasible {m['feasible_share']:.1%}, cz {g['cz']}")
    write(pd.DataFrame(noise), H3_NOISE_PATH)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["G", "H", "H2", "H3"], required=True)
    {"G": stage_g, "H": stage_h, "H2": stage_h2, "H3": stage_h3}[ap.parse_args().stage]()
