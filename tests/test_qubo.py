import itertools
import json
import re
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verigreen.qubo import (BUDGET_MARGIN, GOLD_EXACT_PATH, GOLD_SUMMARY_PATH, GOLD_TOP10_PATH,  # noqa: E402
                            INPUT_CONFIGS, K, LAMBDA_CARBON_GRID, LAMBDA_UNCERTAINTY_GRID, LOW_PRESSURE_CONFIG,
                            MAIN_CONFIG, RETURN_WEIGHTS, RISK_WEIGHT, TRUST_CONFIG, QuboConfig, QuboInputs,
                            apply_scales, assemble, build_qubo, carbon_scores, enumerate_states, exact_optimum,
                            fit_scales, fy_intensity, load_gold_inputs, market_inputs, near_optimal_count,
                            objective_direct, qubo_energy, qubo_with_penalty, ranked_feasible, raw_terms,
                            trust_scores)

ROOT = Path(__file__).resolve().parents[1]
PRICES = ROOT / "data/bronze/prices_cleaned.parquet"
MIN_VAR = replace(MAIN_CONFIG, return_weight=0.0)
CONFIGS = [MAIN_CONFIG, TRUST_CONFIG, MIN_VAR, replace(TRUST_CONFIG, return_weight=0.0),
           QuboConfig(1.0, 0.0, 0.0), QuboConfig(1.0, 4.0, 2.0), QuboConfig(0.0, 0.25, 0.5)]


def synthetic(n=15, seed=0) -> QuboInputs:
    rng = np.random.default_rng(seed)
    a = rng.normal(0, 0.2, (n, n))
    sigma = a @ a.T / n + np.diag(rng.uniform(0.01, 0.05, n))
    return QuboInputs(tuple(f"A{i:02d}" for i in range(n)), sigma, rng.normal(0.05, 0.15, n),
                      rng.normal(0, 1, n), rng.choice([0.0, 0.25, 0.5, 0.75], n), np.exp(rng.normal(2, 1, n)))


def gold_main() -> QuboInputs:
    return load_gold_inputs().inputs("main")


def all_inputs():
    return [synthetic(seed=s) for s in range(3)] + [gold_main()]


def separated(q) -> tuple[float, float]:
    X = enumerate_states(len(q.assets))
    E = qubo_energy(q, X)
    feasible = X.sum(axis=1) == q.k
    return float(E[feasible].max()), float(E[~feasible].min())


def test_each_term_has_the_right_sign_and_scale():
    inp, cfg = synthetic(), QuboConfig(return_weight=0.8, lambda_carbon=0.7, lambda_uncertainty=1.3)
    scales = fit_scales(inp)
    base = build_qubo(inp, cfg, scales, penalty=5.0)
    i, delta = 3, 0.1
    x = np.zeros(15)
    x[[0, 1, 2, 3, 4, 5]] = 1                       # contains asset 3
    y = np.zeros(15)
    y[[0, 1, 2, 4, 5, 6]] = 1                       # does not
    e = np.eye(15)[i]
    cases = {
        "mu": (replace(inp, mu=inp.mu + delta * e), -cfg.return_weight * delta / scales.ret),
        "sigma_ii": (replace(inp, sigma=inp.sigma + delta * np.outer(e, e)), cfg.risk_weight * delta / scales.risk),
        "c": (replace(inp, c=inp.c + delta * e), cfg.lambda_carbon * delta / scales.carbon),
        "u": (replace(inp, u=inp.u + delta * e), cfg.lambda_uncertainty * delta / scales.uncertainty),
    }
    for name, (changed, expected) in cases.items():
        q = build_qubo(changed, cfg, scales, penalty=5.0)
        dx = qubo_energy(q, x)[0] - qubo_energy(base, x)[0]
        dy = qubo_energy(q, y)[0] - qubo_energy(base, y)[0]
        assert np.isclose(dx, expected), (name, dx, expected)
        assert np.isclose(dy, 0.0), (name, dy)
        assert (dx < 0) == (name == "mu"), name      # return is the only term that lowers the energy


def test_objective_direct_is_the_sum_of_the_four_signed_scaled_terms():
    inp = synthetic()
    s = fit_scales(inp)
    x = np.array([1, 0, 1, 1, 0, 0, 1, 0, 1, 0, 0, 1, 0, 0, 0])
    one = {"risk": QuboConfig(0, 0, 0, risk_weight=1), "ret": QuboConfig(1, 0, 0, risk_weight=0),
           "carbon": QuboConfig(0, 1, 0, risk_weight=0), "uncertainty": QuboConfig(0, 0, 1, risk_weight=0)}
    raw = {k: float(v[0]) for k, v in raw_terms(x[None, :].astype(float), inp).items()}
    for term, cfg in one.items():
        sign = -1 if term == "ret" else 1
        assert np.isclose(objective_direct(x, inp, s, cfg), sign * raw[term] / getattr(s, term)), term


def test_scaled_terms_have_unit_std_over_feasible_portfolios():
    for inp in all_inputs():
        X = enumerate_states(15)
        feasible = X[X.sum(axis=1) == K]
        assert len(feasible) == 5005
        for name, t in raw_terms(feasible, apply_scales(fit_scales(inp), inp)).items():
            assert np.isclose(t.std(), 1.0), (name, t.std())


def test_linear_scale_matches_the_closed_form_for_sampling_without_replacement():
    inp = synthetic()
    s = fit_scales(inp)
    factor = np.sqrt(K * (15 - K) / (15 - 1))
    assert np.isclose(s.carbon, inp.c.std() * factor) and np.isclose(s.ret, inp.mu.std() * factor)
    assert np.isclose(fit_scales(gold_main()).carbon, factor)       # z-scored c: population std 1


def test_qubo_is_invariant_to_rescaling_any_input():
    inp = synthetic()
    base = build_qubo(inp, TRUST_CONFIG)
    for field in ("sigma", "mu", "c", "u"):
        q = build_qubo(replace(inp, **{field: getattr(inp, field) * 10}), TRUST_CONFIG)
        assert np.allclose(q.h, base.h) and np.allclose(q.J, base.J) and np.isclose(q.const, base.const), field


def test_term_that_is_constant_on_the_feasible_set_gets_scale_one():
    inp = replace(synthetic(), u=np.full(15, 0.25))
    assert fit_scales(inp).uncertainty == 1.0


def test_budget_penalty_separates_all_2_15_states_and_p_star_is_tight():
    for inp in all_inputs():
        for cfg in CONFIGS:
            q = build_qubo(inp, cfg)
            assert q.p_star > 0 and np.isclose(q.penalty, BUDGET_MARGIN * q.p_star)
            max_feasible, min_infeasible = separated(q)
            assert max_feasible < min_infeasible, (cfg, max_feasible, min_infeasible)
            mf, mi = separated(qubo_with_penalty(q, 0.99 * q.p_star))
            assert mf >= mi, cfg                     # just below P* some infeasible state undercuts a feasible one
            r = exact_optimum(q)
            assert r.separated and r.global_min_feasible


def test_p_star_and_readiness_stats_on_a_hand_worked_example():
    # 4 assets, k = 2, carbon only, c = 0, 1, 2, 3. Feasible sums 1, 2, 3, 3, 4, 5: s_C = sqrt(10/6).
    inp = QuboInputs(("a", "b", "c", "d"), np.zeros((4, 4)), np.zeros(4), np.arange(4.0), np.zeros(4))
    cfg = QuboConfig(return_weight=0, lambda_carbon=1, lambda_uncertainty=0, k=2, risk_weight=0)
    q = build_qubo(inp, cfg)
    s = np.sqrt(10 / 6)
    assert np.isclose(q.scales.carbon, s)
    # m_d: d=-2 -> 0, d=-1 -> 0, d=+1 -> 3/s, d=+2 -> 6/s; F_max = 5/s; P* = max(5/4, 5, 2, -1/4) / s
    assert np.isclose(q.p_star, 5 / s)
    r = exact_optimum(q)
    assert r.selected == ("a", "b")
    assert np.isclose(r.feasible_range, 4 / s) and np.isclose(r.gap_best_second, 1 / s)
    assert r.n_within_near_optimal == 1


def test_qubo_energy_equals_the_directly_computed_objective_on_random_bitstrings():
    rng = np.random.default_rng(42)
    for inp in all_inputs():
        for cfg in (MAIN_CONFIG, TRUST_CONFIG, MIN_VAR):
            q = build_qubo(inp, cfg)
            X = np.vstack([rng.integers(0, 2, (20, 15)), np.zeros(15), np.ones(15)])
            for penalty in (q.penalty, 3.7):
                qp = qubo_with_penalty(q, penalty)
                E = qubo_energy(qp, X)
                direct = [objective_direct(x, inp, q.scales, cfg) + penalty * (x.sum() - K) ** 2 for x in X]
                assert np.allclose(E, direct, rtol=0, atol=1e-9)


def test_exact_optimum_agrees_with_an_independent_search_over_combinations():
    for inp in all_inputs():
        for cfg in (MAIN_CONFIG, TRUST_CONFIG, MIN_VAR):
            s = fit_scales(inp)
            best = min(itertools.combinations(range(15), K),
                       key=lambda idx: objective_direct(np.isin(np.arange(15), idx), inp, s, cfg))
            assert exact_optimum(build_qubo(inp, cfg)).selected == tuple(inp.assets[i] for i in best)


def test_frozen_trusted_scales_reproduce_the_refitted_qubo_exactly():
    gold = load_gold_inputs()
    for name in INPUT_CONFIGS:
        inp, frozen = gold.inputs(name), gold.scales(name)    # scales fitted at export time, stored in the JSON
        for cfg in (MAIN_CONFIG, TRUST_CONFIG):
            refit, fixed = build_qubo(inp, cfg), build_qubo(inp, cfg, scales=frozen)
            assert refit.scales == frozen
            assert np.array_equal(refit.h, fixed.h) and np.array_equal(refit.J, fixed.J)
            assert refit.p_star == fixed.p_star
            assert exact_optimum(refit).selected == exact_optimum(fixed).selected


def test_frozen_scales_keep_an_outlier_from_changing_lambda_meaning():
    inp = gold_main()
    trusted = fit_scales(inp)
    i = inp.assets.index("NDA-FI.HE")
    naive = replace(inp, c=inp.c + 6.0 * np.eye(15)[i])       # one asset jumps to a far outlier
    assert fit_scales(naive).carbon > trusted.carbon * 1.2     # re-fitting would shrink every carbon coefficient
    q_trusted = build_qubo(inp, TRUST_CONFIG, scales=trusted, penalty=10.0)
    q_naive = build_qubo(naive, TRUST_CONFIG, scales=trusted, penalty=10.0)
    diff = np.flatnonzero(~np.isclose(q_naive.h, q_trusted.h))
    assert diff.tolist() == [i] and np.isclose(q_naive.h[i] - q_trusted.h[i], 6.0 / trusted.carbon)
    assert np.array_equal(q_naive.J, q_trusted.J)


def test_qubo_with_penalty_changes_only_the_penalty():
    q = build_qubo(synthetic(), MAIN_CONFIG)
    small = qubo_with_penalty(q, 0.5)
    assert small.penalty == 0.5 and small.p_star == q.p_star
    assert np.array_equal(small.obj_h, q.obj_h) and np.array_equal(small.obj_J, q.obj_J)
    assert np.isclose(build_qubo(synthetic(), MAIN_CONFIG).penalty, BUDGET_MARGIN * q.p_star)   # default unchanged
    try:
        qubo_with_penalty(q, -1.0)
    except ValueError:
        return
    raise AssertionError("negative penalty accepted")


def test_headline_configs_are_the_preregistered_settings():
    assert MAIN_CONFIG == QuboConfig(return_weight=1.0, lambda_carbon=1.0, lambda_uncertainty=0.0, k=6)
    assert TRUST_CONFIG == QuboConfig(return_weight=1.0, lambda_carbon=1.0, lambda_uncertainty=1.0, k=6)
    assert LOW_PRESSURE_CONFIG == QuboConfig(return_weight=1.0, lambda_carbon=0.25, lambda_uncertainty=0.0, k=6)
    assert RISK_WEIGHT == 1.0 and K == 6


def _log_value(text: str, name: str) -> str:
    found = re.findall(rf"^{name} = (.+)$", text, flags=re.M)
    assert len(found) == 1, (name, found)
    return found[0].strip()


def test_grids_and_headline_configs_match_decisions_log():
    text = (ROOT / "docs/decisions_log.md").read_text(encoding="utf-8")
    for name, grid in [("LAMBDA_CARBON_GRID", LAMBDA_CARBON_GRID), ("LAMBDA_UNCERTAINTY_GRID", LAMBDA_UNCERTAINTY_GRID),
                       ("RETURN_WEIGHTS", RETURN_WEIGHTS)]:
        assert tuple(float(v) for v in _log_value(text, name).split(",")) == grid, name
    for name, cfg in [("MAIN_CONFIG", MAIN_CONFIG), ("TRUST_CONFIG", TRUST_CONFIG),
                      ("LOW_PRESSURE_CONFIG", LOW_PRESSURE_CONFIG)]:
        fields = dict(part.strip().split(" ") for part in _log_value(text, name).split(","))
        assert QuboConfig(float(fields["return_weight"]), float(fields["lambda_carbon"]),
                          float(fields["lambda_uncertainty"]), int(fields["k"])) == cfg, name


def test_carbon_scores_log_z_and_rank_z():
    s = pd.Series([0.5, 1.5, 7.0, 7.0, 130.0, 327.0], index=list("abcdef"))
    z = carbon_scores(s, "log_z")
    assert np.isclose(z.mean(), 0) and np.isclose(z.std(ddof=0), 1)
    assert np.allclose(z, (np.log(s) - np.log(s).mean()) / np.log(s).std(ddof=0))
    r = carbon_scores(s, "rank_z")
    assert np.isclose(r["c"], r["d"])                         # ties share the average rank
    assert np.allclose(np.diff(r[["a", "b", "c", "e", "f"]]), [r["b"] - r["a"], 1.5 * (r["b"] - r["a"]),
                                                               1.5 * (r["b"] - r["a"]), r["b"] - r["a"]])
    for bad in (lambda: carbon_scores(s, "minmax"), lambda: carbon_scores(s.replace(0.5, 0.0))):
        try:
            bad()
        except ValueError:
            continue
        raise AssertionError("accepted bad carbon input")


def test_fy_intensity_requires_boundary_match_true_for_every_company():
    assert len(fy_intensity()) == 15
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "ci.csv"
        pd.DataFrame({"company_id": ["A", "B", "C"], "fiscal_year": [2024, 2024, 2023],
                      "boundary_match": ["true", "unknown", "unknown"],
                      "intensity_market_tco2e_per_eurm": [1.0, 2.0, 3.0]}).to_csv(p, index=False)
        try:
            fy_intensity(p)
        except ValueError as e:
            assert "B" in str(e) and "C" not in str(e)
        else:
            raise AssertionError("accepted boundary_match unknown")


def test_assemble_aligns_on_company_id_and_rejects_a_mismatch():
    ids = ["B", "A"]
    sigma = pd.DataFrame([[2.0, 0.1], [0.1, 1.0]], index=ids, columns=ids)
    mu, c, u = pd.Series([0.2, 0.1], ids), pd.Series([1.0, -1.0], ids), pd.Series([0.5, 0.0], ids)
    inp = assemble(sigma, mu, c, u)
    assert inp.assets == ("A", "B") and inp.sigma[0, 0] == 1.0 and inp.mu.tolist() == [0.1, 0.2]
    try:
        assemble(sigma, mu, c, pd.Series([0.5, 0.0], ["B", "Z"]))
    except ValueError:
        return
    raise AssertionError("accepted mismatched assets")


def test_gold_json_reproduces_the_exported_exact_optima():
    gold = load_gold_inputs()
    exact = pd.read_csv(GOLD_EXACT_PATH)
    assert gold.assets == tuple(sorted(gold.assets)) and len(gold.assets) == 15 and gold.raw["k"] == K
    assert len(exact) == len(INPUT_CONFIGS) * len(RETURN_WEIGHTS) * len(LAMBDA_CARBON_GRID) * len(
        LAMBDA_UNCERTAINTY_GRID) and exact["separated"].all()
    for name in INPUT_CONFIGS:
        inp = gold.inputs(name)
        assert fit_scales(inp) == gold.scales(name)
        for label, cfg in [("MAIN_CONFIG", MAIN_CONFIG), ("TRUST_CONFIG", TRUST_CONFIG),
                           ("MAIN_CONFIG_min_variance", MIN_VAR)]:
            q = build_qubo(inp, cfg)
            row = exact[(exact.input_config == name) & (exact.headline == label)]
            assert len(row) == 1, (name, label)
            assert ";".join(exact_optimum(q).selected) == row.iloc[0]["selected"], (name, label)
            assert np.isclose(q.p_star, gold.p_star(name, label), rtol=1e-12)
            assert np.isclose(q.p_star, row.iloc[0]["p_star"], rtol=1e-9)


def test_gold_json_matches_the_source_files():
    gold = load_gold_inputs()
    a = list(gold.assets)
    intensity = fy_intensity()
    assert np.allclose(gold.raw["intensity_market_tco2e_per_eurm"], intensity.loc[a], rtol=1e-12)
    for m, v in gold.raw["carbon"].items():
        assert np.allclose(v, carbon_scores(intensity, m).loc[a], rtol=1e-12), m
    for t, v in gold.raw["trust"].items():
        assert np.array_equal(v, trust_scores(t).loc[a].to_numpy()), t
    if not PRICES.exists():
        return                                    # git-ignored file: gold JSON is the only market source here
    prices = pd.read_parquet(PRICES)
    for w, v in gold.raw["windows"].items():
        sigma, mu, _ = market_inputs(prices, w)
        assert np.allclose(v["sigma"], sigma.loc[a, a], rtol=1e-12, atol=0), w
        assert np.allclose(v["mu"], mu.loc[a], rtol=1e-12, atol=0), w


def test_ranked_feasible_and_near_optimal_count():
    for inp in all_inputs():
        q = build_qubo(inp, TRUST_CONFIG)
        Xr, Ef = ranked_feasible(q)
        assert len(Ef) == 5005 and (Xr.sum(axis=1) == K).all() and (np.diff(Ef) >= 0).all()
        r = exact_optimum(q)
        assert np.array_equal(Xr[0], r.x) and Ef[0] == r.objective
        assert near_optimal_count(Ef, 0.05) == r.n_within_near_optimal
        assert near_optimal_count(Ef, 0.0) >= 1 and near_optimal_count(Ef, 1.0) == 5005
    # hand-worked: energies 0, 1, 2, 10 -> range 10; within 10% = {0, 1}; within 15% = {0, 1}; within 20% = 3
    e = np.array([0.0, 1.0, 2.0, 10.0])
    assert [near_optimal_count(e, f) for f in (0.0, 0.1, 0.15, 0.2)] == [1, 2, 2, 3]


def test_exact_top10_and_summary_exports_agree_with_the_grid():
    top, grid = pd.read_csv(GOLD_TOP10_PATH), pd.read_csv(GOLD_EXACT_PATH)
    summary = json.loads(GOLD_SUMMARY_PATH.read_text(encoding="utf-8"))
    blocks = list(top.groupby(["headline", "input_config"], sort=False))
    assert [k for k, _ in blocks] == [("MAIN_CONFIG", "main"), ("TRUST_CONFIG", "main"), ("TRUST_CONFIG", "u_high")]
    for (label, name), g in blocks:
        assert g["rank"].tolist() == list(range(1, 11)) and g["selected"].is_unique
        assert g["gap_pct_of_range"].iloc[0] == 0 and (np.diff(g["gap_pct_of_range"]) >= 0).all()
        row = grid[(grid.input_config == name) & (grid.headline == label)].iloc[0]
        assert g["selected"].iloc[0] == row["selected"]
        assert np.isclose(g["waci_eq_weight_tco2e_per_eurm"].iloc[0], row["waci_eq_weight_tco2e_per_eurm"])
        b = summary["sampling_baseline"][f"{label}|{name}"]
        assert b["near_optimal"]["0.05"]["count"] == row["n_within_5pct"]
        assert b["near_optimal"]["0.01"]["count"] == int((g["gap_pct_of_range"] <= 1).sum())
        assert np.isclose(b["near_optimal"]["0.05"]["share_of_all_states"] * 2 ** 15, row["n_within_5pct"])
    st = summary["stability"]
    for name in [*INPUT_CONFIGS, "all"]:
        g = grid if name == "all" else grid[grid.input_config == name]
        assert sum(st[name]["swaps_vs_reference"].values()) == len(g)
        for a in st[name]["in_every_optimum"]:
            assert g["selected"].str.split(";").map(lambda s, a=a: a in s).all()
        for a in st[name]["in_no_optimum"]:
            assert not g["selected"].str.contains(a, regex=False).any()


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(tests)} passed")
