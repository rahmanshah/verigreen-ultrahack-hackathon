"""Stages F (and later F2): QAOA on the Aer simulator for the FY2024 MAIN QUBO, plus classical baselines.

Simulator only. Every number is scored against the exact brute-force optimum; no claim of quantum advantage.
Settings were fixed before any run (docs/decisions_log.md, "Stages F / F2" entry); definitions in verigreen/qaoa.py.

Outputs (data/gold/):
- qaoa_runs_fy2024.csv: one row per optimiser restart, failed ones included; `selected` marks the restart with the
  lowest final optimised expected energy per (stage, variant, penalty, p).
- qaoa_summary_fy2024.csv: the selected rows plus the random baselines per penalty.
- qaoa_classical_baselines_fy2024.csv: one row per seeded run of greedy swap search and simulated annealing.

Run: uv run python scripts/report_qaoa.py --stage F | baselines
"""
import argparse
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verigreen.classical_baselines import (BUDGET, N_RUNS, calibrate_temperature, greedy_swap,  # noqa: E402
                                           simulated_annealing)
from verigreen.qaoa import (N_RANDOM_RESTARTS, PENALTIES, READOUT_SHOTS, REPS, WARM_EPSILONS,  # noqa: E402
                            bound_circuit, distribution_metrics, extend_point, ground_state_threshold,
                            penalty_variants, product_probs, random_baselines, random_initial_point, reference,
                            regularise, restart_seed, rounded_relaxation, run_qaoa, sample_metrics, sample_probs,
                            selection, solve_relaxation, statevector_probs, to_ising, warm_initial_state, warm_mixer)
from verigreen.qubo import MAIN_CONFIG, build_qubo, enumerate_states, load_gold_inputs  # noqa: E402

GOLD = ROOT / "data" / "gold"
RUNS_PATH = GOLD / "qaoa_runs_fy2024.csv"
SUMMARY_PATH = GOLD / "qaoa_summary_fy2024.csv"
CLASSICAL_PATH = GOLD / "qaoa_classical_baselines_fy2024.csv"
RELIABILITY_PATH = GOLD / "qaoa_reliability_fy2024.csv"
RELAXATION_PATH = GOLD / "qaoa_relaxation_fy2024.csv"
# Additional reliability run, requested after stage F results were seen; NOT part of the pre-registered set.
RELIABILITY_ROWS = (("practical", 1), ("practical", 2), ("practical", 3), ("exact", 3))
RELIABILITY_RESTARTS = range(10, 30)      # 20 new seeds, disjoint from the pre-registered restarts 0-5


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def save(df: pd.DataFrame, path: Path, stage: str) -> None:
    """Replace this stage's rows in `path`, keep the other stages' rows."""
    if path.exists():
        old = pd.read_csv(path)
        df = pd.concat([old[old["stage"] != stage], df], ignore_index=True)
    df.to_csv(path, index=False, float_format="%.10g", lineterminator="\n")


def main_qubos() -> dict:
    q = build_qubo(load_gold_inputs().inputs("main"), MAIN_CONFIG)
    return penalty_variants(q)


def penalty_info(name: str, q) -> dict:
    return {"n_assets": len(q.assets), "k": q.k, "penalty_name": name, "penalty": q.penalty, "p_star": q.p_star,
            "p_gs": ground_state_threshold(q), "ising_norm": to_ising(q).norm}


def one_restart(stage, variant, name, q, ref, p, restart, init, point, seed, initial_state=None, mixer=None) -> dict:
    model = to_ising(q)
    op = model.operator()
    row = {"stage": stage, "variant": variant, **penalty_info(name, q), "p": p, "restart": restart, "init": init,
           "seed": seed, "initial_point": " ".join(f"{v:.6f}" for v in point)}
    try:
        r = run_qaoa(op, p, point, seed, initial_state=initial_state, mixer=mixer)
        t0 = time.perf_counter()
        circuit = bound_circuit(op, p, r["optimal_point"], initial_state, mixer)
        shots = sample_probs(circuit, READOUT_SHOTS, seed + 1)
        sv = statevector_probs(circuit)
        row.update(status="ok", error="", n_evals=r["n_evals"], runtime_s=r["runtime_s"],
                   readout_runtime_s=time.perf_counter() - t0,
                   final_expected_energy=float(model.to_qubo_units(r["optimal_value"])),
                   sv_expected_energy=float(sv @ ref.energy),
                   optimal_point=" ".join(f"{v:.6f}" for v in r["optimal_point"]),
                   **{f"shot_{k}": v for k, v in sample_metrics(shots, ref).items()},
                   **{f"sv_{k}": v for k, v in distribution_metrics(sv, ref).items()})
    except Exception as e:  # a failed restart is recorded, not dropped
        row.update(status="error", error=f"{type(e).__name__}: {e}")
        traceback.print_exc()
    return row


def run_reliability(stage: str, variant: str, qubos: dict, rows: list, initial_state=None, mixer=None) -> list:
    """Additional reliability run (not pre-registered): RELIABILITY_RESTARTS more seeded random restarts for each row
    in RELIABILITY_ROWS. Never `selected`; the pre-registered headline rows are unchanged."""
    for name, p in RELIABILITY_ROWS:
        q = qubos[name]
        ref = reference(q)
        for r in RELIABILITY_RESTARTS:
            seed = restart_seed(p, r)
            row = one_restart(stage, variant, name, q, ref, p, r, "random", random_initial_point(p, seed), seed,
                              initial_state, mixer)
            row["selected"] = False
            rows.append(row)
            log(f"[reliability] {variant} {name} p={p} restart {r}: {row['status']}, evals {row.get('n_evals')}, "
                f"{row.get('runtime_s', 0):.0f}s")
            save(pd.DataFrame(rows), RUNS_PATH, stage)
    return rows


def reliability_table(base_stage: str, rel_stage: str) -> pd.DataFrame:
    """Per (variant, penalty, p) in RELIABILITY_ROWS: pre-registered + reliability restarts together."""
    runs = pd.read_csv(RUNS_PATH)
    runs = runs[runs["stage"].isin([base_stage, rel_stage]) & (runs["status"] == "ok")]
    b_popt, b_near = 1 / 5005, 14 / 5005
    out = []
    for (variant, name, p), g in runs.groupby(["variant", "penalty_name", "p"], sort=False):
        if (name, p) not in RELIABILITY_ROWS:
            continue
        rule = g.loc[g["final_expected_energy"].idxmin()]
        oracle = g.loc[g["sv_p_opt"].idxmax()]
        headline = g[g["selected"] == True].iloc[0]  # noqa: E712
        out.append({"base_stage": base_stage, "variant": variant, "penalty_name": name, "p": p,
                    "n_restarts": len(g), "n_preregistered": int((g["stage"] == base_stage).sum()),
                    "n_beat_p_opt": int((g["sv_p_opt"] > b_popt).sum()),
                    "n_beat_near_given_feasible": int((g["sv_near_mass_given_feasible"] > b_near).sum()),
                    "median_p_opt": g["sv_p_opt"].median(),
                    "median_near_given_feasible": g["sv_near_mass_given_feasible"].median(),
                    "median_mean_ratio_feasible": g["sv_mean_ratio_feasible"].median(),
                    "headline_restart": int(headline["restart"]), "headline_p_opt": headline["sv_p_opt"],
                    "rule_over_all_restart": int(rule["restart"]), "rule_over_all_p_opt": rule["sv_p_opt"],
                    "rule_over_all_near_given_feasible": rule["sv_near_mass_given_feasible"],
                    "best_restart_by_p_opt": int(oracle["restart"]), "best_p_opt": oracle["sv_p_opt"],
                    "best_near_given_feasible": oracle["sv_near_mass_given_feasible"]})
    return pd.DataFrame(out)


def save_reliability(base_stage: str, rel_stage: str) -> None:
    t = reliability_table(base_stage, rel_stage)
    if RELIABILITY_PATH.exists():
        old = pd.read_csv(RELIABILITY_PATH)
        t = pd.concat([old[old["base_stage"] != base_stage], t], ignore_index=True)
    t.to_csv(RELIABILITY_PATH, index=False, float_format="%.10g", lineterminator="\n")
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(t[t["base_stage"] == base_stage].to_string(index=False, float_format=lambda v: f"{v:.4g}"))


def run_variant(stage: str, variant: str, qubos: dict, initial_state=None, mixer=None,
                rows: list | None = None) -> list:
    """All penalties x REPS x pre-registered restarts for one circuit variant (warm-start pieces or None = standard)."""
    rows = [] if rows is None else rows
    for name in PENALTIES:
        q = qubos[name]
        ref = reference(q)
        init_state = initial_state
        prev_best = None
        for p in REPS:
            starts = [(r, "random", random_initial_point(p, restart_seed(p, r))) for r in range(N_RANDOM_RESTARTS)]
            if prev_best is not None:
                starts.append((N_RANDOM_RESTARTS, "extend_p_minus_1", extend_point(prev_best)))
            block = []
            for r, init, point in starts:
                row = one_restart(stage, variant, name, q, ref, p, r, init, point, restart_seed(p, r), init_state,
                                  mixer)
                block.append(row)
                rows.append(row)
                log(f"{variant} {name} p={p} restart {r} ({init}): {row['status']}, evals {row.get('n_evals')}, "
                    f"{row.get('runtime_s', 0):.0f}s")
                save(pd.DataFrame(rows), RUNS_PATH, stage)
            ok = [b for b in block if b["status"] == "ok"]
            if ok:
                best = min(ok, key=lambda b: b["final_expected_energy"])
                best["selected"] = True
                prev_best = np.array([float(v) for v in best["optimal_point"].split()])
            for b in block:
                b.setdefault("selected", False)
            save(pd.DataFrame(rows), RUNS_PATH, stage)
    return rows


def baseline_rows(stage: str, qubos: dict) -> list:
    out = []
    for name, q in qubos.items():
        ref = reference(q)
        b = random_baselines(ref)
        uniform_feasible = ref.feasible / ref.feasible.sum()
        uniform_all = np.full(len(ref.energy), 1 / len(ref.energy))
        for variant, probs in (("random_feasible", uniform_feasible), ("uniform_superposition", uniform_all)):
            out.append({"stage": stage, "variant": variant, **penalty_info(name, q), "p": 0, "status": "ok",
                        **{f"sv_{k}": v for k, v in distribution_metrics(probs, ref).items()},
                        "n_near": b["n_near"], "n_feasible": b["n_feasible"]})
    return out


def write_summary(stage: str, rows: list, extra: list) -> pd.DataFrame:
    runs = pd.DataFrame(rows)
    sel = runs[runs["selected"] == True]  # noqa: E712
    df = pd.concat([pd.DataFrame(extra), sel], ignore_index=True)
    save(df, SUMMARY_PATH, stage)
    return df


def print_summary(df: pd.DataFrame) -> None:
    cols = ["variant", "penalty_name", "p", "sv_p_opt", "shot_p_opt", "sv_near_mass", "sv_near_mass_given_feasible",
            "sv_feasible_share", "sv_mean_ratio_feasible", "shot_best_ratio", "shot_best_selection", "n_evals",
            "runtime_s"]
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(df[[c for c in cols if c in df]].to_string(index=False, float_format=lambda v: f"{v:.4g}"))


def stage_f() -> None:
    qubos = main_qubos()
    for name, q in qubos.items():
        i = penalty_info(name, q)
        log(f"penalty {name}: P = {i['penalty']:.4f}, P* = {i['p_star']:.4f}, P_gs = {i['p_gs']:.4f}, "
            f"P_gs/P* = {i['p_gs'] / i['p_star']:.4f}, Ising norm = {i['ising_norm']:.4f}")
    rows = run_variant("F", "standard", qubos)
    df = write_summary("F", rows, baseline_rows("F", qubos))
    log(f"wrote {RUNS_PATH.name} ({len(rows)} restarts) and {SUMMARY_PATH.name}")
    print_summary(df)


def stage_baselines() -> None:
    q = main_qubos()["exact"]          # feasible-only search: the penalty never enters
    ref = reference(q)
    x_opt = enumerate_states(len(q.assets))[ref.opt_index]
    t0 = calibrate_temperature(q)
    log(f"SA T0 = {t0:.4f} (feasible range {ref.f_max - ref.f_min:.4f})")
    rows = []
    for method, fn in (("greedy_swap", lambda s: greedy_swap(q, x_opt, s)),
                       ("simulated_annealing", lambda s: simulated_annealing(q, x_opt, s, t0))):
        t = time.perf_counter()
        for seed in range(N_RUNS):
            r = fn(seed)
            rows.append({"stage": "classical", "method": method, "seed": seed, "budget": BUDGET,
                         "hit": r["first_hit_eval"] is not None, "first_hit_eval": r["first_hit_eval"],
                         "best_ratio": (r["best_f"] - ref.f_min) / (ref.f_max - ref.f_min), "restarts": r["restarts"],
                         "sa_t0": t0 if method == "simulated_annealing" else np.nan})
        log(f"{method}: {N_RUNS} runs in {time.perf_counter() - t:.1f}s")
    df = pd.DataFrame(rows)
    df.to_csv(CLASSICAL_PATH, index=False, float_format="%.10g", lineterminator="\n")
    for method, g in df.groupby("method", sort=False):
        hits = g.loc[g.hit, "first_hit_eval"]
        log(f"{method}: success {g.hit.mean():.0%}, evaluations to first hit median {hits.median():.0f}, "
            f"p90 {hits.quantile(0.9):.0f}, max {hits.max():.0f}; restarts median {g.restarts.median():.0f}")


def stage_f_reliability() -> None:
    rows = run_reliability("F_reliability", "standard", main_qubos(), [])
    log(f"wrote {len(rows)} reliability restarts")
    save_reliability("F", "F_reliability")


def warm_variant(eps: float) -> str:
    return f"warm_eps{eps:g}"


def classical_reference_rows(stage: str, qubos: dict, relax) -> list:
    """Pure classical rows shown next to every warm-start QAOA row: rounded relaxation, warm initial state (p = 0)."""
    out = []
    X = enumerate_states(len(relax.c))
    x = rounded_relaxation(relax.c, qubos["exact"].k)
    idx = int(np.flatnonzero((X == x).all(axis=1))[0])
    for name, q in qubos.items():
        ref = reference(q)
        rank = int((ref.energy[ref.feasible] < ref.energy[idx]).sum()) + 1
        out.append({"stage": stage, "variant": "rounded_relaxation", **penalty_info(name, q), "p": 0, "status": "ok",
                    "shot_best_selection": selection(ref, idx), "shot_best_ratio": ref.ratio[idx],
                    "shot_best_gap": ref.energy[idx] - ref.f_min, "shot_best_is_optimum": idx == ref.opt_index,
                    "rounded_rank_of_5005": rank, "relaxed_objective": relax.objective,
                    "relaxation_gap_to_f_min": ref.f_min - relax.objective})
        for eps in WARM_EPSILONS:
            probs = product_probs(regularise(relax.c, eps))
            out.append({"stage": stage, "variant": f"{warm_variant(eps)}_initial_state", **penalty_info(name, q),
                        "p": 0, "status": "ok", **{f"sv_{k}": v for k, v in distribution_metrics(probs, ref).items()},
                        "sv_expected_energy": float(probs @ ref.energy)})
    return out


def stage_f2() -> None:
    qubos = main_qubos()
    relax = solve_relaxation(load_gold_inputs().inputs("main"), qubos["exact"])
    assets = qubos["exact"].assets
    rel = pd.DataFrame({"asset": assets, "c_star": relax.c, "rounded_top_k": rounded_relaxation(relax.c, 6).astype(int),
                        **{f"c_eps{eps:g}": regularise(relax.c, eps) for eps in WARM_EPSILONS}})
    rel.to_csv(RELAXATION_PATH, index=False, float_format="%.10g", lineterminator="\n")
    log(f"relaxation: f(c*) = {relax.objective:.4f}, min eigenvalue of risk term {relax.min_eig_risk:.3g}, "
        f"c* = {dict(zip(assets, np.round(relax.c, 3)))}")
    rows = []
    for eps in WARM_EPSILONS:
        c = regularise(relax.c, eps)
        run_variant("F2", warm_variant(eps), qubos, warm_initial_state(c), warm_mixer(c), rows)
    df = write_summary("F2", rows, classical_reference_rows("F2", qubos, relax))
    log(f"wrote {len(rows)} pre-registered F2 restarts")
    print_summary(df)
    rel_rows = []
    for eps in WARM_EPSILONS:
        c = regularise(relax.c, eps)
        run_reliability("F2_reliability", warm_variant(eps), qubos, rel_rows, warm_initial_state(c), warm_mixer(c))
    save_reliability("F2", "F2_reliability")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["F", "baselines", "F_reliability", "F2"], required=True)
    stage = ap.parse_args().stage
    {"F": stage_f, "baselines": stage_baselines, "F_reliability": stage_f_reliability, "F2": stage_f2}[stage]()
