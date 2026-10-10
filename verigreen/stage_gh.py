"""Stages G (reduced) and H on the Aer simulator. Simulator only; no hardware, no qiskit-iqm.

Stage G: does warm-start QAOA reproduce the raw-vs-trusted result of stage G0? The result itself (which portfolio is
optimal on naive vs trusted inputs) comes from exact enumeration (`data/gold/raw_vs_trusted_exact_fy2024.csv`) and the
classical relaxation; QAOA is only shown reproducing it. Cases (all FY2024, frozen_trusted_z, practical penalty):
MAIN trusted, MAIN with the Nordea financed-emissions error, MAIN with the Sampo financed-emissions error, and TRUST (u)
trusted. Warm start eps 0.1, p = 1 and 3, restarts 0-9 (`restart_seed`), the restart with the lowest final expected
energy is "selected" (the F2 rule).

Stage H: sizing of a hardware-sized instance. The instance is the assets with nonzero weight in the MAIN relaxation, a
classical pre-screen, with the 15-asset coefficients (scales frozen). Transpiled depth and two-qubit gates for
stand-in coupling maps, exact and simulated P(opt), and an illustrative depolarising-noise preview.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from verigreen.qaoa import (READOUT_SHOTS, Reference, bound_circuit, distribution_metrics, penalty_variants,
                            product_probs, random_initial_point, reference, regularise, relaxed_objective, restart_seed,
                            rounded_relaxation, run_qaoa, sample_metrics, sample_probs, selection, solve_relaxation,
                            statevector_probs, to_ising, warm_initial_state, warm_mixer)
from verigreen.qubo import (MAIN_CONFIG, ROOT, TRUST_CONFIG, GoldInputs, Qubo, QuboInputs, budget_threshold, build_qubo,
                            enumerate_states, exact_optimum, exact_penalty, load_gold_inputs, qubo_energy)
from verigreen.raw_vs_trusted import (GOLD_RAW_VS_TRUSTED_PATH, cases, load_naive_rows, naive_inputs,
                                      naive_intensity, trusted_fy, trusted_inputs)

GOLD = ROOT / "data" / "gold"
G_RUNS_PATH = GOLD / "qaoa_stage_g_runs_fy2024.csv"
G_SUMMARY_PATH = GOLD / "qaoa_stage_g_summary_fy2024.csv"
H_INSTANCE_PATH = GOLD / "qaoa_stage_h_instance_fy2024.csv"
H_SIZING_PATH = GOLD / "qaoa_stage_h_sizing_fy2024.csv"
H_SIMULATION_PATH = GOLD / "qaoa_stage_h_simulation_fy2024.csv"
H2_NOISE_PATH = GOLD / "qaoa_stage_h2_noise_fy2024.csv"
H3_INSTANCE_PATH = GOLD / "qaoa_stage_h3_instance_fy2024.csv"
H3_SIZING_PATH = GOLD / "qaoa_stage_h3_sizing_fy2024.csv"
H3_SIMULATION_PATH = GOLD / "qaoa_stage_h3_simulation_fy2024.csv"
H3_SUMMARY_PATH = GOLD / "qaoa_stage_h3_summary_fy2024.csv"
H3_NOISE_PATH = GOLD / "qaoa_stage_h3_noise_fy2024.csv"

EPS = 0.1
G_REPS = (1, 3)
G_RESTARTS = tuple(range(10))
CONDITION = "frozen_trusted_z"
RELAXATION_ZERO = 1e-6                # c* below this = "zero relaxation weight"
CASE_ORDER = ("MAIN_trusted", "MAIN_nordea_financed", "MAIN_sampo_financed", "TRUST_u_trusted")
FINANCED_KEY = {"MAIN_nordea_financed": "NDA-FI.HE:financed_emissions", "MAIN_sampo_financed": "SAMPO.HE:financed_emissions"}


# ---------------------------------------------------------------- stage G: cases

@dataclass(frozen=True)
class Case:
    case_id: str
    inputs: QuboInputs
    qubo: Qubo                 # exact-penalty QUBO; the practical one comes from `penalty_variants`
    headline: str              # column `headline` of the G0 CSV that holds this case's exact optimum
    exact_column: str          # which G0 column: trusted_selected (trusted inputs) or naive_selected
    g0_case_id: str


def build_cases(gold: GoldInputs | None = None) -> dict[str, Case]:
    gold = gold or load_gold_inputs()
    out = {}
    t_inp, t_scales = trusted_inputs(gold, "log_z", "u")
    out["MAIN_trusted"] = Case("MAIN_trusted", t_inp, build_qubo(t_inp, MAIN_CONFIG, t_scales), "MAIN_CONFIG",
                               "trusted_selected", "SAMPO.HE:financed_emissions")
    trusted = trusted_fy()
    all_cases = cases(load_naive_rows(trusted))
    for case_id, key in FINANCED_KEY.items():
        naive, _, _ = naive_intensity(trusted, all_cases[key])
        _, _, n_inp, n_scales = naive_inputs(gold, naive.loc[list(gold.assets)], CONDITION, "u")
        out[case_id] = Case(case_id, n_inp, build_qubo(n_inp, MAIN_CONFIG, n_scales), "MAIN_CONFIG", "naive_selected", key)
    out["TRUST_u_trusted"] = Case("TRUST_u_trusted", t_inp, build_qubo(t_inp, TRUST_CONFIG, t_scales), "TRUST_CONFIG",
                                  "trusted_selected", "SAMPO.HE:financed_emissions")
    return {k: out[k] for k in CASE_ORDER}


def g0_exact_selection(case: Case, path=GOLD_RAW_VS_TRUSTED_PATH) -> str:
    """The exact optimum for this case, read from the stage G0 CSV (frozen_trusted_z)."""
    df = pd.read_csv(path)
    row = df[(df["case_id"] == case.g0_case_id) & (df["condition"] == CONDITION) & (df["headline"] == case.headline)]
    if len(row) != 1:
        raise ValueError(f"{case.case_id}: expected one G0 row, got {len(row)}")
    return str(row.iloc[0][case.exact_column])


def selection_of(qubo: Qubo, x) -> str:
    return ";".join(a for a, b in zip(qubo.assets, x) if b)


# ---------------------------------------------------------------- one restart, scored against its own exact reference

def top_feasible(probs: np.ndarray, ref: Reference) -> tuple[str, float]:
    """The most likely feasible portfolio (and its probability)."""
    idx = int(np.argmax(np.where(ref.feasible, probs, -1.0)))
    return selection(ref, idx), float(probs[idx])


def warm_restart(qubo: Qubo, ref: Reference, c_eps: np.ndarray, p: int, restart: int) -> dict:
    """One COBYLA restart of warm-start QAOA, exact statevector and 16,384-shot read-out, as in stage F2."""
    model = to_ising(qubo)
    op = model.operator()
    seed = restart_seed(p, restart)
    init, mixer = warm_initial_state(c_eps), warm_mixer(c_eps)
    point = random_initial_point(p, seed)
    r = run_qaoa(op, p, point, seed, initial_state=init, mixer=mixer)
    circuit = bound_circuit(op, p, r["optimal_point"], init, mixer)
    sv = statevector_probs(circuit)
    shots = sample_probs(circuit, READOUT_SHOTS, seed + 1)
    top_sv, top_sv_p = top_feasible(sv, ref)
    top_shot, top_shot_p = top_feasible(shots, ref)
    return {"p": p, "restart": restart, "seed": seed, "status": "ok", "n_evals": r["n_evals"], "runtime_s": r["runtime_s"],
            "final_expected_energy": float(model.to_qubo_units(r["optimal_value"])),
            "optimal_point": " ".join(f"{v:.6f}" for v in r["optimal_point"]),
            **{f"sv_{k}": v for k, v in distribution_metrics(sv, ref).items()},
            **{f"shot_{k}": v for k, v in sample_metrics(shots, ref).items()},
            "top_feasible_sv": top_sv, "top_feasible_sv_prob": top_sv_p, "top_feasible_shot": top_shot,
            "top_feasible_shot_prob": top_shot_p, "top_is_exact_optimum": top_sv == selection(ref, ref.opt_index)}


def baseline_row(ref: Reference, probs: np.ndarray) -> dict:
    top, top_p = top_feasible(probs, ref)
    return {**{f"sv_{k}": v for k, v in distribution_metrics(probs, ref).items()}, "top_feasible_sv": top,
            "top_feasible_sv_prob": top_p, "top_is_exact_optimum": top == selection(ref, ref.opt_index)}


def summarise_runs(runs: pd.DataFrame, p0: dict) -> dict:
    """Selected restart (lowest final expected energy), median over restarts, and how many beat the p = 0 warm state."""
    ok = runs[runs["status"] == "ok"]
    sel = ok.loc[ok["final_expected_energy"].idxmin()]
    return {
        "n_restarts": len(ok), "selected_restart": int(sel["restart"]),
        "selected_top_feasible": sel["top_feasible_sv"], "selected_top_feasible_prob": sel["top_feasible_sv_prob"],
        "selected_top_feasible_shot": sel["top_feasible_shot"],
        "selected_p_opt": sel["sv_p_opt"], "selected_shot_p_opt": sel["shot_p_opt"],
        "selected_near_mass": sel["sv_near_mass"], "selected_near_given_feasible": sel["sv_near_mass_given_feasible"],
        "selected_feasible_share": sel["sv_feasible_share"], "selected_mean_r": sel["sv_mean_ratio_feasible"],
        "median_p_opt": ok["sv_p_opt"].median(), "median_near_mass": ok["sv_near_mass"].median(),
        "median_near_given_feasible": ok["sv_near_mass_given_feasible"].median(),
        "median_feasible_share": ok["sv_feasible_share"].median(),
        "median_mean_r": ok["sv_mean_ratio_feasible"].median(),
        "n_beat_p0_p_opt": int((ok["sv_p_opt"] > p0["sv_p_opt"]).sum()),
        "n_beat_p0_near_given_feasible": int((ok["sv_near_mass_given_feasible"] > p0["sv_near_mass_given_feasible"]).sum()),
        "n_beat_p0_mean_r": int((ok["sv_mean_ratio_feasible"] < p0["sv_mean_ratio_feasible"]).sum()),
        "n_top_is_exact_optimum": int(ok["top_is_exact_optimum"].sum()),
    }


def run_case(case: Case, log=print) -> tuple[list[dict], list[dict]]:
    """(restart rows, summary rows: one per p) for one case."""
    q = penalty_variants(case.qubo)["practical"]
    ref = reference(q)
    exact = exact_optimum(case.qubo)
    exact_sel = ";".join(exact.selected)
    g0_sel = g0_exact_selection(case)
    if exact_sel != g0_sel or selection(ref, ref.opt_index) != g0_sel:
        raise AssertionError(f"{case.case_id}: fresh brute force {exact_sel} != G0 CSV {g0_sel}")
    relax = solve_relaxation(case.inputs, q)
    x_round = rounded_relaxation(relax.c, q.k)
    round_sel = selection_of(q, x_round)
    idx = int(np.flatnonzero((enumerate_states(len(q.assets)) == x_round).all(axis=1))[0])
    round_rank = int((ref.energy[ref.feasible] < ref.energy[idx]).sum()) + 1
    c_eps = regularise(relax.c, EPS)
    p0 = baseline_row(ref, product_probs(c_eps))
    base = {"case_id": case.case_id, "g0_case_id": case.g0_case_id, "g0_headline": case.headline,
            "penalty": q.penalty, "p_star": case.qubo.p_star, "exact_selection": exact_sel,
            "exact_gap_best_second_pct_of_range": 100 * exact.gap_best_second / exact.feasible_range,
            "rounded_relaxation": round_sel, "rounded_is_exact_optimum": round_sel == exact_sel,
            "rounded_rank_of_5005": round_rank,
            "c_star": " ".join(f"{a}={v:.3f}" for a, v in zip(q.assets, relax.c) if v > RELAXATION_ZERO),
            "p0_top_feasible": p0["top_feasible_sv"], "p0_p_opt": p0["sv_p_opt"], "p0_near_mass": p0["sv_near_mass"],
            "p0_near_given_feasible": p0["sv_near_mass_given_feasible"], "p0_feasible_share": p0["sv_feasible_share"],
            "p0_mean_r": p0["sv_mean_ratio_feasible"]}
    runs, summary = [], []
    for p in G_REPS:
        block = []
        for r in G_RESTARTS:
            row = {"case_id": case.case_id, **warm_restart(q, ref, c_eps, p, r)}
            block.append(row)
            runs.append(row)
            log(f"  {case.case_id} p={p} restart {r}: P(opt) {row['sv_p_opt']:.3f}, top {row['top_feasible_sv_prob']:.3f}, "
                f"{row['runtime_s']:.0f}s")
        s = summarise_runs(pd.DataFrame(block), p0)
        for row in block:
            row["selected"] = row["restart"] == s["selected_restart"]
        summary.append({**base, "p": p, **s})
    return runs, summary


def add_main_comparison(summary: pd.DataFrame) -> pd.DataFrame:
    """Does the selected QAOA portfolio equal the case's exact optimum, and how does it compare with MAIN trusted?"""
    s = summary.copy()
    main_exact = s.loc[s["case_id"] == "MAIN_trusted", "exact_selection"].iloc[0]
    s["exact_vs_main_exact"] = np.where(s["exact_selection"] == main_exact, "same", "changed")
    s["qaoa_selected_equals_exact"] = s["selected_top_feasible"] == s["exact_selection"]
    s["qaoa_selected_vs_main_exact"] = np.where(s["selected_top_feasible"] == main_exact, "same", "changed")
    s["selection_result_reproduced"] = s["qaoa_selected_equals_exact"]
    return s


# ---------------------------------------------------------------- stage H: the hardware-sized instance

@dataclass(frozen=True)
class Instance:
    assets: tuple[str, ...]
    indices: tuple[int, ...]
    qubo: Qubo                 # exact penalty, 15-asset coefficients (scales frozen), P* re-computed on the subset
    inputs: QuboInputs
    c_full: np.ndarray         # the 15-asset relaxation c*
    c_sub: np.ndarray          # the relaxation re-solved on the subset


def build_instance(gold: GoldInputs | None = None) -> Instance:
    gold = gold or load_gold_inputs()
    case = build_cases(gold)["MAIN_trusted"]
    full_q = penalty_variants(case.qubo)["practical"]
    relax = solve_relaxation(case.inputs, full_q)
    idx = tuple(int(i) for i in np.flatnonzero(relax.c > RELAXATION_ZERO))
    inp = case.inputs
    sub = QuboInputs(tuple(inp.assets[i] for i in idx), inp.sigma[np.ix_(idx, idx)], inp.mu[list(idx)], inp.c[list(idx)],
                     inp.u[list(idx)], None if inp.intensity is None else inp.intensity[list(idx)])
    q = build_qubo(sub, MAIN_CONFIG, case.qubo.scales)          # trusted 15-asset scales, frozen
    relax_sub = solve_relaxation(sub, q)
    return Instance(sub.assets, idx, q, sub, relax.c[list(idx)], relax_sub.c)


def warm_circuit_parts(instance: Instance, eps: float = EPS):
    c = regularise(instance.c_sub, eps)
    return c, warm_initial_state(c), warm_mixer(c)


def sizing_circuit(instance: Instance, p: int, point=None):
    """Warm-start circuit of depth p (p = 0: the initial state only). Parameter values do not change the gate count."""
    c, init, mixer = warm_circuit_parts(instance)
    if p == 0:
        return init.copy()
    op = to_ising(penalty_variants(instance.qubo)["practical"]).operator()
    point = np.full(2 * p, 0.37) if point is None else point
    return bound_circuit(op, p, point, init, mixer)


NATIVE_BASIS = ["r", "cz"]            # IQM native gates: PRX = r, and CZ


def coupling_maps(n: int) -> dict:
    from qiskit.transpiler import CouplingMap
    grids = {8: ("grid_2x4", (2, 4)), 4: ("grid_2x2", (2, 2))}
    if n not in grids:
        raise ValueError("stand-in grids exist for 8 qubits (2 x 4) and 4 qubits (2 x 2)")
    name, shape = grids[n]
    return {"all_to_all": None, "line": CouplingMap.from_line(n), name: CouplingMap.from_grid(*shape)}


def transpile_once(circuit, coupling, seed: int, level: int = 3):
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
    pm = generate_preset_pass_manager(optimization_level=level, basis_gates=NATIVE_BASIS, coupling_map=coupling,
                                      seed_transpiler=seed)
    return pm.run(circuit)


def sizing_stats(circuit, coupling, seeds=range(20), level: int = 3) -> dict:
    """Transpile with several seeds (routing is stochastic) and report depth / two-qubit gates (min, median, max)."""
    seeds = list(seeds)
    depth, cz, ops = [], [], []
    for s in seeds:
        t = transpile_once(circuit, coupling, s, level)
        depth.append(t.depth())
        cz.append(t.count_ops().get("cz", 0))
        ops.append(sum(t.count_ops().values()))
    d, c, o = np.array(depth), np.array(cz), np.array(ops)
    best = min(range(len(seeds)), key=lambda i: (c[i], d[i]))        # fewest two-qubit gates, then shallowest
    return {"depth_min": int(d.min()), "depth_median": float(np.median(d)), "depth_max": int(d.max()),
            "cz_min": int(c.min()), "cz_median": float(np.median(c)), "cz_max": int(c.max()),
            "gates_median": float(np.median(o)), "n_seeds": len(d), "optimization_level": level,
            "best_seed": int(seeds[best])}


# ---------------------------------------------------------------- stage H2: illustrative depolarising noise

def noise_model(p2: float, p1: float):
    from qiskit_aer.noise import NoiseModel, depolarizing_error
    nm = NoiseModel(basis_gates=NATIVE_BASIS)
    if p1 > 0:
        nm.add_all_qubit_quantum_error(depolarizing_error(p1, 1), ["r"])
    if p2 > 0:
        nm.add_all_qubit_quantum_error(depolarizing_error(p2, 2), ["cz"])
    return nm


def noisy_probs(circuit, coupling, p2: float, p1: float, shots: int, sim_seed: int, transpile_seed: int,
                level: int = 3) -> tuple[np.ndarray, dict]:
    """(measured distribution over logical bitstrings, gate stats of the circuit that ran). The measurement is added
    before routing, so the final qubit permutation is handled by the classical register."""
    from qiskit_aer import AerSimulator
    from verigreen.qaoa import counts_to_probs
    qc = circuit.copy()
    qc.measure_all()
    t = transpile_once(qc, coupling, transpile_seed, level)
    sim = AerSimulator(noise_model=noise_model(p2, p1), seed_simulator=sim_seed)
    counts = sim.run(t, shots=shots).result().get_counts()
    ops = t.count_ops()
    return counts_to_probs(counts, circuit.num_qubits), {"cz": int(ops.get("cz", 0)), "depth_with_measure": t.depth()}


# ---------------------------------------------------------------- stage H3: residual subproblem after variable fixing
# Variable fixing from the classical relaxation: assets with c* >= FIX_ONE_MIN are fixed to 1, assets with c* <= RELAXATION_ZERO
# to 0, and the rest form a small QUBO with K_res = K - (number fixed to 1). Same frozen 15-asset coefficients.

FIX_ONE_MIN = 0.99


@dataclass(frozen=True)
class Residual:
    instance: Instance           # the undecided assets; `inputs` is None (the QUBO is built from folded coefficients)
    fixed_one: tuple[str, ...]
    fixed_zero: tuple[str, ...]
    offset: float                # residual energy + offset = 15-asset objective (without penalty) for the same portfolio
    k_res: int
    full_qubo: Qubo              # the 15-asset exact-penalty QUBO


def solve_residual_relaxation(inputs: QuboInputs, qubo: Qubo, fixed_one, undecided, k_res: int,
                              starts: int = 5, seed: int = 20261006) -> np.ndarray:
    """Convex relaxation over the undecided assets only, the fixed ones held at 1 (and the rest at 0). SLSQP, several
    starts that must agree."""
    from scipy.optimize import minimize
    f, grad, _ = relaxed_objective(inputs, qubo)
    n, u = len(qubo.assets), list(undecided)

    def embed(xu):
        x = np.zeros(n)
        x[list(fixed_one)] = 1.0
        x[u] = xu
        return x

    rng = np.random.default_rng(seed)
    x0s = [np.full(len(u), k_res / len(u))] + [rng.dirichlet(np.ones(len(u))) * k_res for _ in range(starts - 1)]
    sols = []
    for x0 in x0s:
        r = minimize(lambda xu: f(embed(xu)), np.clip(x0, 0, 1), jac=lambda xu: grad(embed(xu))[u], method="SLSQP",
                     bounds=[(0, 1)] * len(u),
                     constraints=[{"type": "eq", "fun": lambda x: x.sum() - k_res, "jac": lambda x: np.ones(len(u))}],
                     options={"ftol": 1e-12, "maxiter": 1000})
        if not r.success:
            raise RuntimeError(f"SLSQP failed: {r.message}")
        sols.append(r)
    best = min(sols, key=lambda r: r.fun)
    if max(r.fun for r in sols) - best.fun > 1e-7:
        raise RuntimeError("SLSQP starts disagree on a convex problem")
    return np.clip(best.x, 0, 1)


def build_residual(gold: GoldInputs | None = None) -> Residual:
    gold = gold or load_gold_inputs()
    case = build_cases(gold)["MAIN_trusted"]
    q15 = case.qubo
    c15 = solve_relaxation(case.inputs, penalty_variants(q15)["practical"]).c
    one = np.flatnonzero(c15 >= FIX_ONE_MIN)
    zero = np.flatnonzero(c15 <= RELAXATION_ZERO)
    und = np.array([i for i in range(len(c15)) if i not in set(one) | set(zero)])
    k_res = q15.k - len(one)
    sym = q15.obj_J + q15.obj_J.T
    h_res = q15.obj_h[und] + sym[np.ix_(und, one)].sum(axis=1)
    J_res = q15.obj_J[np.ix_(und, und)]                         # und is ascending, so J stays strictly upper triangular
    offset = float(q15.obj_h[one].sum() + q15.obj_J[np.ix_(one, one)].sum())
    assets = tuple(q15.assets[i] for i in und)
    q0 = Qubo(assets, h_res, J_res, k_res, 0.0, 0.0, q15.scales, replace(MAIN_CONFIG, k=k_res))
    X = enumerate_states(len(und))
    p_star = budget_threshold(qubo_energy(q0, X), X.sum(axis=1), k_res)
    q = replace(q0, penalty=exact_penalty(p_star), p_star=p_star)
    c_res = solve_residual_relaxation(case.inputs, q15, one, und, k_res)
    inst = Instance(assets, tuple(int(i) for i in und), q, None, c15[und], c_res)
    return Residual(inst, tuple(q15.assets[i] for i in one), tuple(q15.assets[i] for i in zero), offset, k_res, q15)
