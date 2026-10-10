import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verigreen.qubo import load_gold_inputs  # noqa: E402
from verigreen.raw_vs_trusted import (CONDITIONS, FINANCED_BASIS, GOLD_RAW_VS_TRUSTED_PATH, HEADLINES,  # noqa: E402
                                      NAIVE_PATH, cases, compare, load_naive_rows, naive_inputs, naive_intensity,
                                      raw_vs_trusted_rows, trusted_fy, trusted_inputs)

TRUSTED = trusted_fy()
GOLD = load_gold_inputs()
CASES = cases(load_naive_rows(TRUSTED))


def naive(case_id: str) -> pd.Series:
    return naive_intensity(TRUSTED, CASES[case_id])[0]


def test_naive_intensities_reproduce_the_optimisation_year_table():
    # hand-computed from the raw values and FY2024 revenue; matches decisions_log 2026-10-05 ("Effect on market-based
    # Scope 1+2 carbon intensity": 1,640 / 31.1 / 0.3 / 8.2 / 7.1 / 0.5 / 198.7 / 228.1). Blank raw fields keep trusted.
    expected = {"NDA-FI.HE:financed_emissions": ("NDA-FI.HE", 19846338 / 12100),
                "SAMPO.HE:financed_emissions": ("SAMPO.HE", 293860 / 9450),
                "NDA-FI.HE:pre_restatement": ("NDA-FI.HE", (1025 + 3037) / 12100),
                "METSO.HE:unit_error": ("METSO.HE", (37670 + 3308) / 5026),
                "KESKOB.HE:pre_restatement": ("KESKOB.HE", (56637 + 27939) / 11920.1),
                "SAMPO.HE:pre_restatement": ("SAMPO.HE", (882 + 3657) / 9450),
                "KEMIRA.HE:pre_restatement": ("KEMIRA.HE", (118364 + 467561) / 2948.1),
                "OUT1V.HE:pre_restatement": ("OUT1V.HE", (990643 + 364704) / 5942)}
    assert set(expected) | {"all_naive", "all_vintage"} == set(CASES)
    for case_id, (company, value) in expected.items():
        n = naive(case_id)
        assert np.isclose(n[company], value, rtol=1e-12), (case_id, n[company])
        others = n.drop(company)
        assert np.array_equal(others, TRUSTED["intensity_market_tco2e_per_eurm"].drop(company)), case_id


def test_outokumpu_location_only_restatement_leaves_market_intensity_unchanged():
    assert np.array_equal(naive("OUT1V.HE:pre_restatement"), TRUSTED["intensity_market_tco2e_per_eurm"])


def test_combined_cases_financed_row_supersedes_and_vintage_excludes_financed():
    _, applied, superseded = naive_intensity(TRUSTED, CASES["all_naive"])
    assert sorted(r.key for r in superseded) == ["NDA-FI.HE:pre_restatement", "SAMPO.HE:pre_restatement"]
    assert len(applied) + len(superseded) == 8
    n = naive("all_naive")
    assert np.isclose(n["NDA-FI.HE"], naive("NDA-FI.HE:financed_emissions")["NDA-FI.HE"])
    assert {r.category for r in CASES["all_vintage"]} == {"pre_restatement", "unit_error"}
    assert len(CASES["all_vintage"]) == 6


def test_raw_basis_and_verification_status():
    rows = {r.key: r for r in CASES["all_naive"]}
    for k in ("NDA-FI.HE:financed_emissions", "SAMPO.HE:financed_emissions"):
        assert rows[k].raw_basis == FINANCED_BASIS
    assert FINANCED_BASIS == ("AR2025 comparative, recalculated: a definition illustration, not what the 2024 "
                              "reports printed")
    assert rows["SAMPO.HE:pre_restatement"].verification_status == "from_notes"
    assert all(r.verification_status == "verified_pdf" for k, r in rows.items() if k != "SAMPO.HE:pre_restatement")


def test_trusted_values_must_match_silver():
    df = pd.read_csv(NAIVE_PATH)
    df.loc[(df.company_id == "KESKOB.HE") & (df.fiscal_year == 2024), "trusted_scope1"] += 1
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "naive.csv"
        df.to_csv(p, index=False)
        try:
            load_naive_rows(TRUSTED, p)
        except ValueError as e:
            assert "KESKOB.HE" in str(e)
        else:
            raise AssertionError("accepted a trusted value that differs from silver")


def test_trusted_inputs_reproduce_the_gold_scales():
    for carbon, trust, name in (("log_z", "u", "main"), ("log_z", "u_high", "u_high"), ("rank_z", "u", "rank_carbon")):
        inp, scales = trusted_inputs(GOLD, carbon, trust)
        assert scales == GOLD.scales(name), name
        assert np.array_equal(inp.c, GOLD.inputs(name).c) and np.array_equal(inp.u, GOLD.inputs(name).u)


def test_frozen_condition_changes_only_the_affected_assets_carbon():
    i = GOLD.assets.index("NDA-FI.HE")
    for condition in ("frozen_trusted_z", "rank_z"):
        t_inp, t_scales, n_inp, n_scales = naive_inputs(GOLD, naive("NDA-FI.HE:financed_emissions"), condition, "u")
        assert n_scales == t_scales
        diff = np.flatnonzero(n_inp.c != t_inp.c)
        assert diff.tolist() == [i] or condition == "rank_z", (condition, diff)
        assert n_inp.c[i] > t_inp.c[i]
        assert np.array_equal(n_inp.sigma, t_inp.sigma) and np.array_equal(n_inp.u, t_inp.u)
    # refit: the whole vector moves and the carbon scale is re-fitted
    t_inp, t_scales, n_inp, n_scales = naive_inputs(GOLD, naive("NDA-FI.HE:financed_emissions"), "refit_naive", "u")
    assert np.isclose(n_inp.c.std(), 1.0) and not np.allclose(n_inp.c, t_inp.c)


def test_unchanged_intensity_gives_the_trusted_optimum_and_zero_error():
    n = naive("OUT1V.HE:pre_restatement")
    for condition in CONDITIONS:
        for label, (cfg, trust) in HEADLINES.items():
            r = compare(GOLD, n, cfg, trust, condition)
            assert not r["selection_changed"] and r["n_swapped"] == 0, (condition, label)
            assert r["waci_eq_weight_error_pct"] == 0 and r["true_regret_pct_of_range"] == 0


def test_gold_csv_is_reproducible_and_waci_is_the_equal_weight_mean():
    saved = pd.read_csv(GOLD_RAW_VS_TRUSTED_PATH, keep_default_na=False)
    fresh = raw_vs_trusted_rows(GOLD)
    assert len(saved) == len(fresh) == len(CASES) * len(CONDITIONS) * len(HEADLINES)
    for col in fresh.columns:
        if pd.api.types.is_numeric_dtype(fresh[col]) and not pd.api.types.is_bool_dtype(fresh[col]):
            assert np.allclose(saved[col].astype(float), fresh[col].astype(float), rtol=1e-9, atol=1e-12), col
        else:
            assert (saved[col].astype(str) == fresh[col].astype(str)).all(), col
    true = TRUSTED["intensity_market_tco2e_per_eurm"]
    for _, r in fresh.iterrows():
        n = naive(r.case_id)
        names = r.naive_selected.split(";")
        assert len(names) == 6
        assert np.isclose(r.waci_eq_weight_naive_reported, n[names].mean())
        assert np.isclose(r.waci_eq_weight_true_naive_portfolio, true[names].mean())
        assert np.isclose(r.waci_eq_weight_benchmark_trusted, true.mean())
        assert np.isclose(r.waci_eq_weight_benchmark_naive, n.mean())
        assert r.selection_changed == (r.naive_selected != r.trusted_selected)


def test_vintage_cases_never_change_the_selection():
    df = pd.read_csv(GOLD_RAW_VS_TRUSTED_PATH, keep_default_na=False)
    vintage = df[~df.case_id.str.contains("financed") & (df.case_id != "all_naive")]
    assert not vintage["selection_changed"].any()


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(tests)} passed")
