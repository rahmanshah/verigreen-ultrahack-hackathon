import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verigreen.classical_baselines import (Objective, calibrate_temperature, greedy_swap,  # noqa: E402
                                           simulated_annealing)
from verigreen.qaoa import (bound_circuit, counts_to_probs, distribution_metrics, ground_state_threshold,  # noqa: E402
                            ising_diagonal, penalty_variants, product_probs, random_baselines, random_initial_point,
                            reference, regularise, relaxed_objective, rounded_relaxation, run_qaoa, sample_metrics,
                            sample_probs, solve_relaxation, statevector_probs, to_ising, warm_initial_state,
                            warm_mixer)
from verigreen.qubo import (MAIN_CONFIG, QuboInputs, build_qubo, enumerate_states, load_gold_inputs,  # noqa: E402
                            qubo_energy, qubo_with_penalty)


def small_qubo(n=6, k=3, seed=0):
    rng = np.random.default_rng(seed)
    a = rng.normal(0, 0.2, (n, n))
    inp = QuboInputs(tuple(f"A{i}" for i in range(n)), a @ a.T / n + np.diag(rng.uniform(0.01, 0.05, n)),
                     rng.normal(0.05, 0.15, n), rng.normal(0, 1, n), np.zeros(n))
    return build_qubo(inp, replace(MAIN_CONFIG, k=k))


def gold_qubo():
    return build_qubo(load_gold_inputs().inputs("main"), MAIN_CONFIG)


def test_ising_reproduces_qubo_energy_on_every_state():
    for q in [small_qubo(), *penalty_variants(gold_qubo()).values()]:
        X = enumerate_states(len(q.assets))
        model = to_ising(q)
        assert np.allclose(ising_diagonal(model), qubo_energy(q, X), atol=1e-9)
        diag = np.real(model.operator().to_matrix(sparse=True).diagonal())
        assert np.allclose(model.to_qubo_units(diag), qubo_energy(q, X), atol=1e-8)
        assert np.isclose(np.abs(model.operator().coeffs).max(), 1.0)


def test_qubit_i_is_asset_i_in_sampling_and_statevector():
    from qiskit import QuantumCircuit
    n = 5
    for i in range(n):
        qc = QuantumCircuit(n)
        qc.x(i)
        for probs in (statevector_probs(qc), sample_probs(qc, 64, seed=1)):
            assert np.isclose(probs[2 ** i], 1.0)
        assert enumerate_states(n)[2 ** i].tolist() == [float(j == i) for j in range(n)]
    assert np.isclose(counts_to_probs({"00110": 3, "00001": 1}, 5)[6], 0.75)


def test_ground_state_threshold_is_tight():
    for q in (small_qubo(), gold_qubo()):
        p_gs = ground_state_threshold(q)
        assert 0 < p_gs <= q.p_star
        ref = reference(q)
        X = enumerate_states(len(q.assets))
        assert int(np.argmin(qubo_energy(qubo_with_penalty(q, 1.01 * p_gs), X))) == ref.opt_index
        assert int(np.argmin(qubo_energy(qubo_with_penalty(q, 0.99 * p_gs), X))) != ref.opt_index
    v = penalty_variants(gold_qubo())
    assert np.isclose(v["practical"].penalty, 1.1 * ground_state_threshold(v["exact"]))
    assert np.allclose(v["practical"].obj_h, v["exact"].obj_h)


def test_metrics_on_a_hand_made_distribution():
    q = small_qubo()
    ref = reference(q)
    order = np.argsort(np.where(ref.feasible, ref.energy, np.inf))
    worst = int(order[ref.feasible.sum() - 1])
    infeasible = int(np.flatnonzero(~ref.feasible)[0])
    probs = np.zeros(len(ref.energy))
    probs[[ref.opt_index, worst, infeasible]] = [0.25, 0.25, 0.5]
    m = sample_metrics(probs, ref)
    assert m["p_opt"] == 0.25 and m["feasible_share"] == 0.5
    assert np.isclose(m["mean_ratio_feasible"], 0.5)                  # (0 + 1) / 2
    assert m["best_is_optimum"] and m["best_ratio"] == 0 and m["best_gap"] == 0
    assert np.isclose(m["near_mass_given_feasible"], m["near_mass"] / 0.5)
    uniform_feasible = ref.feasible / ref.feasible.sum()
    b = random_baselines(ref)
    d = distribution_metrics(uniform_feasible, ref)
    assert np.isclose(d["p_opt"], b["p_opt_random_feasible"])
    assert np.isclose(d["near_mass"], b["near_share_of_feasible"])
    assert np.isclose(d["mean_ratio_feasible"], b["mean_ratio_random_feasible"])


def test_gold_baselines_match_stage_e_summary():
    import json
    from verigreen.qubo import GOLD_SUMMARY_PATH
    s = json.loads(GOLD_SUMMARY_PATH.read_text(encoding="utf-8"))["sampling_baseline"]["MAIN_CONFIG|main"]
    for q in penalty_variants(gold_qubo()).values():
        b = random_baselines(reference(q))
        assert b["n_feasible"] == s["n_feasible"] and b["n_near"] == s["near_optimal"]["0.05"]["count"]
        assert np.isclose(b["near_share_of_all_states"], s["near_optimal"]["0.05"]["share_of_all_states"])


def test_seeded_qaoa_is_reproducible_and_readout_matches_training_energy():
    q = small_qubo()
    model = to_ising(q)
    op = model.operator()
    point = random_initial_point(1, seed=3)
    a = run_qaoa(op, 1, point, seed=3, maxiter=15, shots=2048)
    b = run_qaoa(op, 1, point, seed=3, maxiter=15, shots=2048)
    assert np.array_equal(a["optimal_point"], b["optimal_point"]) and a["n_evals"] == b["n_evals"] <= 15
    probs = statevector_probs(bound_circuit(op, 1, a["optimal_point"]))
    exact_mean = float(probs @ ising_diagonal(model))
    assert abs(model.to_qubo_units(a["optimal_value"]) - exact_mean) < 0.1 * model.norm


def test_classical_baselines_count_evaluations_and_find_small_optimum():
    q = small_qubo(n=8, k=4)
    x_opt = enumerate_states(8)[reference(q).opt_index]
    assert np.isclose(Objective(q)(x_opt)[0], reference(q).f_min)
    t0 = calibrate_temperature(q)
    for run in (lambda s: greedy_swap(q, x_opt, s, budget=500),
                lambda s: simulated_annealing(q, x_opt, s, t0, budget=500)):
        r1, r2 = run(1), run(1)
        assert r1 == r2 and r1["evals"] == 500
        assert r1["first_hit_eval"] is not None and 1 <= r1["first_hit_eval"] <= 500
        assert np.isclose(r1["best_f"], reference(q).f_min)


def marginals(probs: np.ndarray, n: int) -> np.ndarray:
    return probs @ enumerate_states(n)


def test_relaxation_is_convex_feasible_and_agrees_with_the_qubo_on_binaries():
    inp = load_gold_inputs().inputs("main")
    q = gold_qubo()
    relax = solve_relaxation(inp, q)
    assert relax.min_eig_risk > 0
    assert np.isclose(relax.c.sum(), q.k) and (relax.c >= 0).all() and (relax.c <= 1).all()
    assert relax.objective <= reference(q).f_min + 1e-9            # a relaxation bounds the optimum from below
    f, _, _ = relaxed_objective(inp, q)
    X = enumerate_states(15)[np.random.default_rng(0).choice(2 ** 15, 200, replace=False)]
    assert np.allclose([f(x) for x in X], qubo_energy(qubo_with_penalty(q, 0.0), X))
    x = rounded_relaxation(relax.c, q.k)
    assert x.sum() == q.k and set(np.flatnonzero(x)) == set(np.argsort(-relax.c)[:q.k])
    assert np.array_equal(solve_relaxation(inp, penalty_variants(q)["practical"]).c, relax.c)   # penalty-free


def test_warm_start_at_beta_zero_keeps_the_marginals_c():
    q = small_qubo(n=5, k=2)
    op = to_ising(q).operator()
    c = regularise(np.array([0.02, 0.3, 0.55, 0.8, 0.97]), 0.1)      # distinct per qubit, so ordering is checked
    assert np.allclose(c, [0.1, 0.3, 0.55, 0.8, 0.9])
    init, mixer = warm_initial_state(c), warm_mixer(c)
    assert np.allclose(marginals(statevector_probs(init), 5), c)
    assert np.allclose(statevector_probs(init), product_probs(c))
    rng = np.random.default_rng(4)
    for p in (1, 2):
        point = np.concatenate([np.zeros(p), rng.uniform(0, np.pi, p)])        # beta = 0, random gamma
        circuit = bound_circuit(op, p, point, init, mixer)
        assert np.allclose(marginals(statevector_probs(circuit), 5), c, atol=1e-9)
        shots = 20000
        sampled = marginals(sample_probs(circuit, shots, seed=5), 5)
        assert (np.abs(sampled - c) < 5 * np.sqrt(c * (1 - c) / shots)).all()
        moved = bound_circuit(op, p, np.concatenate([np.full(p, 0.4), point[p:]]), init, mixer)
        assert not np.allclose(marginals(statevector_probs(moved), 5), c, atol=1e-3)   # beta != 0 does mix


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(tests)} passed")
