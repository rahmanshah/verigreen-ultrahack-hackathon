import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verigreen.data_trust import (FLAGS, WEIGHTS, ambiguous_flags, check_citation,  # noqa: E402
                                  compute_data_trust, load_data_trust_inputs, parse_evidence,
                                  validate_data_trust_inputs)

ROOT = Path(__file__).resolve().parents[1]
SCORED = [f for f in FLAGS if WEIGHTS[f] > 0]


def real_companies():
    raw = pd.read_csv(ROOT / "data/bronze/emissions_raw.csv")
    return set(raw[raw.fiscal_year == 2024]["company_id"])


def row(**kw):
    base = dict(company_id="AAA.HE", fiscal_year=2024, restated=False, boundary_or_methodology_break=False,
                partly_estimated=False, revenue_boundary_mismatch=False, single_source=False, evidence="")
    base.update(kw)
    return base


def test_inputs_file_is_valid_and_complete_for_fy2024():
    df = load_data_trust_inputs()
    assert len(df) == 15
    assert validate_data_trust_inputs(df, real_companies()) == []


def test_every_true_flag_has_non_empty_evidence():
    df = load_data_trust_inputs()
    for _, r in df.iterrows():
        segs = parse_evidence(r["evidence"])
        for flag in FLAGS:
            if bool(r[flag]):
                cites = [s for s in segs if s.flag == flag and not s.is_ambiguous]
                assert cites and all(s.text.strip() for s in cites), (r["company_id"], flag)


def test_every_quoted_snippet_still_appears_in_its_cited_file_and_section():
    df = load_data_trust_inputs()
    n = 0
    for _, r in df.iterrows():
        for seg in parse_evidence(r["evidence"]):
            if not seg.is_ambiguous:
                assert check_citation(seg, ROOT) is None, (r["company_id"], seg)
                n += 1
    assert n >= 15


def test_ambiguous_flags_are_false_and_documented():
    df = load_data_trust_inputs()
    n = 0
    for _, r in df.iterrows():
        for flag in ambiguous_flags(r["evidence"]):
            assert not bool(r[flag]), (r["company_id"], flag)
            n += 1
    assert n >= 1


def test_validator_rejects_true_flag_without_evidence():
    df = pd.DataFrame([row(restated=True)])
    assert any("restated is true but has no evidence" in p for p in validate_data_trust_inputs(df))


def test_validator_rejects_quote_that_is_not_in_the_cited_section():
    ev = "restated::docs/verification_log.md::Unit error::this sentence is not in the log"
    problems = validate_data_trust_inputs(pd.DataFrame([row(restated=True, evidence=ev)]))
    assert any("quote not found" in p for p in problems)
    # real quote, wrong section: also rejected
    ev = "restated::docs/verification_log.md::Portfolio changes::Metso: 2024 Scope 1 restated because one site"
    problems = validate_data_trust_inputs(pd.DataFrame([row(restated=True, evidence=ev)]))
    assert any("quote not found" in p for p in problems)


def test_validator_rejects_ambiguous_flag_set_true_and_empty_evidence_text():
    ev = "restated::ambiguous::unclear"
    assert any("ambiguous but set true" in p
               for p in validate_data_trust_inputs(pd.DataFrame([row(restated=True, evidence=ev)])))
    ev = "restated::docs/verification_log.md::Unit error::"
    assert any("empty evidence text" in p
               for p in validate_data_trust_inputs(pd.DataFrame([row(evidence=ev)])))


def test_weights_are_equal_over_scored_flags_and_single_source_is_informational():
    assert WEIGHTS["single_source"] == 0.0
    assert len({WEIGHTS[f] for f in SCORED}) == 1
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-12


def test_u_and_u_high_computed_from_flags_and_ambiguity():
    df = pd.DataFrame([
        row(company_id="A", restated=True, boundary_or_methodology_break=True),
        row(company_id="B", evidence="partly_estimated::ambiguous::unclear ;; restated::ambiguous::unclear"),
        row(company_id="C", single_source=True),
        row(company_id="D", restated=True, boundary_or_methodology_break=True, partly_estimated=True,
            revenue_boundary_mismatch=True,
            evidence=" ;; ".join(f"{f}::docs/verification_log.md::Unit error::wrong energy unit"
                                 for f in SCORED)),
    ])
    out = compute_data_trust(df).set_index("company_id")
    assert out.loc["A", ["u", "u_high"]].tolist() == [0.5, 0.5]
    assert out.loc["B", ["u", "u_high"]].tolist() == [0.0, 0.5]
    assert out.loc["C", ["u", "u_high"]].tolist() == [0.0, 0.0]   # single_source is not scored
    assert out.loc["D", ["u", "u_high"]].tolist() == [1.0, 1.0]
    assert out.loc["B", "n_ambiguous"] == 2


def test_scores_in_unit_interval_and_u_high_never_below_u_on_real_data():
    out = compute_data_trust(load_data_trust_inputs())
    assert out["u"].between(0, 1).all() and out["u_high"].between(0, 1).all()
    assert (out["u_high"] >= out["u"]).all()


def test_single_source_matches_emissions_raw_third_party_rows():
    df = load_data_trust_inputs().set_index("company_id")
    raw = pd.read_csv(ROOT / "data/bronze/emissions_raw.csv")
    r24 = raw[raw.fiscal_year == 2024]
    for cid in df.index:
        has_third_party = (r24[r24.company_id == cid].source_type == "third_party").any()
        assert bool(df.loc[cid, "single_source"]) == (not has_third_party), cid


def test_revenue_boundary_mismatch_matches_carbon_intensity_boundary_match():
    df = load_data_trust_inputs().set_index("company_id")
    ci = pd.read_csv(ROOT / "data/silver/carbon_intensity.csv")
    ci = ci[ci.fiscal_year == 2024].set_index("company_id")
    for cid in df.index:
        assert bool(df.loc[cid, "revenue_boundary_mismatch"]) == (str(ci.loc[cid, "boundary_match"]).lower() != "true"), cid


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(tests)} passed")
