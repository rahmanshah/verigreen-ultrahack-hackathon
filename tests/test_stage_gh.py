import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verigreen.qaoa import (bound_circuit, penalty_variants, product_probs, reference, regularise,  # noqa: E402
                            statevector_probs, to_ising)
from verigreen.qubo import MAIN_CONFIG, enumerate_states, exact_optimum, objective_direct, qubo_energy  # noqa: E402
from verigreen.stage_gh import (EPS, G_RESTARTS, RELAXATION_ZERO, add_main_comparison, build_cases,  # noqa: E402
                                build_instance, build_residual, coupling_maps, g0_exact_selection, noisy_probs,
                                selection_of, sizing_circuit, sizing_stats, summarise_runs, transpile_once, warm_restart)

ROOT = Path(__file__).resolve().parents[1]


def test_case_optima_equal_the_g0_csv_and_the_expected_changes():
    cases = build_cases()
    sel = {k: ";".join(exact_optimum(c.qubo).selected) for k, c in cases.items()}
    for k, c in cases.items():
        assert sel[k] == g0_exact_selection(c), k
    main = sel["MAIN_trusted"]
    assert sel["MAIN_sampo_financed"] == main                           # financed Sampo does not move MAIN
    assert "NOKIA.HE" in sel["MAIN_nordea_financed"] and "NDA-FI.HE" not in sel["MAIN_nordea_financed"]
    assert sel["TRUST_u_trusted"] != main
    for c in cases.values():                                          # every naive QUBO is separated by its exact penalty
        assert c.qubo.penalty > c.qubo.p_star


def test_main_trusted_case_is_the_gold_main_qubo():
    case = build_cases()["MAIN_trusted"]
    from verigreen.qubo import build_qubo, load_gold_inputs
    gold_q = build_qubo(load_gold_inputs().inputs("main"), MAIN_CONFIG)
    assert np.allclose(case.qubo.obj_h, gold_q.obj_h) and np.allclose(case.qubo.obj_J, gold_q.obj_J)
    assert np.isclose(case.qubo.penalty, gold_q.penalty)


def test_warm_restart_reproduces_the_f2_row_for_the_same_seed():
    case = build_cases()["MAIN_trusted"]
    q = penalty_variants(case.qubo)["practical"]
    from verigreen.qaoa import solve_relaxation
    c = regularise(solve_relaxation(case.inputs, q).c, EPS)
    row = warm_restart(q, reference(q), c, 1, 0)
    f2 = pd.read_csv(ROOT / "data" / "gold" / "qaoa_runs_fy2024.csv")
    f2 = f2[(f2["stage"] == "F2") & (f2["variant"] == "warm_eps0.1") & (f2["penalty_name"] == "practical")
            & (f2["p"] == 1) & (f2["restart"] == 0)].iloc[0]
    assert np.isclose(row["sv_p_opt"], f2["sv_p_opt"], atol=1e-9)
    assert np.isclose(row["final_expected_energy"], f2["final_expected_energy"], atol=1e-9)


def test_summarise_runs_selects_by_energy_and_counts_against_p0():
    runs = pd.DataFrame({
        "restart": [0, 1, 2], "status": "ok", "final_expected_energy": [-1.0, -3.0, -2.0],
        "sv_p_opt": [0.30, 0.10, 0.20], "sv_near_mass": [0.4, 0.2, 0.3], "sv_near_mass_given_feasible": [0.8, 0.5, 0.6],
        "sv_feasible_share": [0.5, 0.4, 0.5], "sv_mean_ratio_feasible": [0.01, 0.2, 0.05], "shot_p_opt": [0.3, 0.1, 0.2],
        "top_feasible_sv": ["A", "B", "A"], "top_feasible_sv_prob": [0.3, 0.1, 0.2], "top_feasible_shot": ["A", "B", "A"],
        "top_is_exact_optimum": [True, False, True]})
    p0 = {"sv_p_opt": 0.15, "sv_near_mass_given_feasible": 0.55, "sv_mean_ratio_feasible": 0.1}
    s = summarise_runs(runs, p0)
    assert s["selected_restart"] == 1 and s["selected_top_feasible"] == "B"     # lowest energy, not best P(opt)
    assert s["median_p_opt"] == 0.2 and s["n_beat_p0_p_opt"] == 2
    assert s["n_beat_p0_near_given_feasible"] == 2 and s["n_beat_p0_mean_r"] == 2 and s["n_top_is_exact_optimum"] == 2


def test_add_main_comparison_flags_change_and_no_change():
    base = {"p": 1, "selected_top_feasible": "X"}
    s = pd.DataFrame([{**base, "case_id": "MAIN_trusted", "exact_selection": "X"},
                      {**base, "case_id": "MAIN_sampo_financed", "exact_selection": "X"},
                      {**base, "case_id": "MAIN_nordea_financed", "exact_selection": "Y", "selected_top_feasible": "Y"}])
    out = add_main_comparison(s).set_index("case_id")
    assert out.loc["MAIN_sampo_financed", "exact_vs_main_exact"] == "same" and out.loc["MAIN_sampo_financed", "selection_result_reproduced"]
    assert out.loc["MAIN_nordea_financed", "exact_vs_main_exact"] == "changed"
    assert out.loc["MAIN_nordea_financed", "qaoa_selected_vs_main_exact"] == "changed"
    assert out.loc["MAIN_nordea_financed", "selection_result_reproduced"]


def test_seeds_zero_to_four_are_the_f2_seeds():
    from verigreen.qaoa import restart_seed
    assert G_RESTARTS == tuple(range(10)) and restart_seed(1, 0) == 20261006 + 100


def test_hardware_instance_is_the_relaxation_support_and_contains_the_15_asset_optimum():
    inst = build_instance()
    cases = build_cases()
    full = cases["MAIN_trusted"]
    opt15 = exact_optimum(full.qubo)
    assert len(inst.assets) == 8 and inst.qubo.k == 6
    assert set(opt15.selected) <= set(inst.assets)
    assert (inst.c_full > RELAXATION_ZERO).all()
    others = [i for i in range(15) if i not in inst.indices]
    from verigreen.qaoa import solve_relaxation
    c15 = solve_relaxation(full.inputs, penalty_variants(full.qubo)["practical"]).c
    assert (c15[others] <= RELAXATION_ZERO).all()
    assert np.allclose(inst.c_sub, inst.c_full, atol=1e-5)               # re-solving on the subset gives the same c*
    opt8 = exact_optimum(inst.qubo)
    assert opt8.selected == opt15.selected
    assert np.isclose(opt8.objective, opt15.objective, atol=1e-9)         # same coefficients, scales frozen
    assert inst.qubo.scales == full.qubo.scales
    x15 = np.zeros(15)
    x15[[inst.indices[inst.assets.index(a)] for a in opt15.selected]] = 1
    assert np.isclose(objective_direct(x15, full.inputs, full.qubo.scales, MAIN_CONFIG), opt15.objective)
    assert 28 == int(reference(inst.qubo).feasible.sum())


def test_sizing_p0_has_no_entangling_gates_and_p1_matches_the_dense_cost_layer():
    inst = build_instance()
    c0, c1 = sizing_circuit(inst, 0), sizing_circuit(inst, 1)
    maps = coupling_maps(8)
    for cm in maps.values():
        t = transpile_once(c0, cm, 0)
        assert t.count_ops().get("cz", 0) == 0 and set(t.count_ops()) <= {"r"}
    op = to_ising(penalty_variants(inst.qubo)["practical"]).operator()
    n_pairs = sum(1 for lbl in op.paulis if str(lbl).count("Z") == 2)
    assert n_pairs == 28                                                   # the budget term makes every pair interact
    all_to_all = sizing_stats(c1, maps["all_to_all"], range(3))
    assert all_to_all["cz_min"] == all_to_all["cz_max"] == 2 * n_pairs     # one RZZ = two CZ, no routing
    for name in ("line", "grid_2x4"):
        routed = sizing_stats(c1, maps[name], range(5))
        assert routed["cz_min"] >= 2 * n_pairs and routed["depth_min"] >= all_to_all["depth_min"]


def test_noise_free_sampling_matches_the_statevector_and_noise_flattens_p1():
    inst = build_instance()
    q = penalty_variants(inst.qubo)["practical"]
    ref = reference(q)
    c = regularise(inst.c_sub, EPS)
    point = np.array([0.7, 1.1])
    from verigreen.qaoa import warm_initial_state, warm_mixer
    circuit = bound_circuit(to_ising(q).operator(), 1, point, warm_initial_state(c), warm_mixer(c))
    sv = statevector_probs(circuit)
    shots = 65536
    for name in ("all_to_all", "grid_2x4"):
        cm = coupling_maps(8)[name]
        clean, _ = noisy_probs(circuit, cm, 0.0, 0.0, shots, 3, 0)
        assert abs(clean[ref.opt_index] - sv[ref.opt_index]) < 5 * np.sqrt(sv[ref.opt_index] * (1 - sv[ref.opt_index]) / shots)
        assert abs(clean[ref.feasible].sum() - sv[ref.feasible].sum()) < 0.01
        noisy, g = noisy_probs(circuit, cm, 0.02, 0.002, shots, 3, 0)
        assert g["cz"] >= 56
        assert noisy[ref.opt_index] < clean[ref.opt_index] - 0.05          # heavy noise costs P(opt)
    # p = 0 has no two-qubit gates, so two-qubit noise cannot change it
    p0 = sizing_circuit(inst, 0)
    a, _ = noisy_probs(p0, coupling_maps(8)["grid_2x4"], 0.0, 0.0, shots, 3, 0)
    b, _ = noisy_probs(p0, coupling_maps(8)["grid_2x4"], 0.02, 0.0, shots, 3, 0)
    assert np.allclose(a, b)
    assert np.allclose(product_probs(c).sum(), 1.0)


def test_residual_problem_fixes_the_relaxation_support_and_keeps_the_15_asset_optimum():
    res = build_residual()
    inst = res.instance
    full = build_cases()["MAIN_trusted"]
    opt15 = exact_optimum(full.qubo)
    assert res.fixed_one == ("ELISA.HE", "NDA-FI.HE", "ORNBV.HE", "SAMPO.HE") and len(res.fixed_zero) == 7
    assert inst.assets == ("KESKOB.HE", "KNEBV.HE", "NOKIA.HE", "WRT1V.HE") and res.k_res == 2
    assert int(reference(inst.qubo).feasible.sum()) == 6
    opt = exact_optimum(inst.qubo)
    assert tuple(sorted(opt.selected + res.fixed_one)) == tuple(sorted(opt15.selected))
    assert np.allclose(inst.c_sub, inst.c_full, atol=1e-5)               # residual relaxation = the 15-asset c* on those assets
    # folded coefficients: residual energy + offset = the 15-asset objective for the same portfolio, on all 6 feasible states
    X = enumerate_states(4)
    E = qubo_energy(inst.qubo, X)
    for x, e in zip(X, E):
        if x.sum() != res.k_res:
            continue
        x15 = np.zeros(15)
        x15[list(res.instance.indices)] = x
        x15[[full.qubo.assets.index(a) for a in res.fixed_one]] = 1
        assert np.isclose(e + res.offset, objective_direct(x15, full.inputs, full.qubo.scales, MAIN_CONFIG), atol=1e-9)
    assert inst.qubo.penalty > inst.qubo.p_star and penalty_variants(inst.qubo)["practical"].penalty < inst.qubo.penalty


def test_residual_p0_is_a_product_state_equal_to_independent_biased_coins_and_sizing_matches_the_pairs():
    from verigreen.qaoa import warm_initial_state
    inst = build_residual().instance
    c = regularise(inst.c_sub, EPS)
    probs = product_probs(c)
    assert np.allclose(statevector_probs(warm_initial_state(c)), probs)
    rng = np.random.default_rng(0)
    n = 200000
    flips = (rng.random((n, 4)) < c).astype(int)
    idx = flips @ (2 ** np.arange(4))                                     # qubit i = bit i, as in `enumerate_states`
    emp = np.bincount(idx, minlength=16) / n
    assert (np.abs(emp - probs) < 5 * np.sqrt(probs * (1 - probs) / n) + 1e-4).all()
    maps = coupling_maps(4)
    assert set(maps) == {"all_to_all", "line", "grid_2x2"}
    assert transpile_once(sizing_circuit(inst, 0), maps["line"], 0).count_ops().get("cz", 0) == 0
    assert sizing_stats(sizing_circuit(inst, 1), maps["all_to_all"], range(3))["cz_max"] == 2 * 6   # 6 pairs, 2 cz each


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(tests)} passed")
