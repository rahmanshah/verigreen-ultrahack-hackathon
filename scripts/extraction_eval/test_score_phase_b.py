"""Self-tests for score_phase_b.py. Made-up inputs only: no verified data row, no API call.

    <side env python> -X utf8 scripts/extraction_eval/test_score_phase_b.py
"""
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import score_phase_b as s  # noqa: E402

D = Decimal


def vrow(year=2024, s1="", s2l="", s2m="", unit="tCO2e", st="primary", cid="AA", name="Alpha Oy", url="http://x", page="9",
         notes=""):
    return {"company_id": cid, "company_name": name, "fiscal_year": str(year), "scope1": s1, "scope2_location": s2l,
            "scope2_market": s2m, "unit": unit, "boundary": "", "source_type": st, "source_url": url, "source_page": page,
            "retrieved_date": "", "notes": notes}


def rec(scope="1", year=2024, printed="1000", unit="tCO2e", status="pass", flags=None, failed=None, mapped="same", i=0,
        quote="q", page=3, num="auto"):
    my = year if mapped == "same" else mapped
    if num == "auto":
        try:
            num = float(printed.replace(",", "")) if printed else None
        except ValueError:
            num = None
    d = {"record_index": i, "scope": scope, "year_label_as_printed": str(year), "mapped_year": my,
         "value_as_printed": printed, "unit_as_printed": unit, "pdf_page": page, "quote": quote, "note": None,
         "null_reason": "not reported" if printed is None else None, "value_numeric": num,
         "harness_flags": flags or []}
    v = {"status": "not_stated" if printed is None else status, "failed": failed or [], "ambiguous": [], "flags": [],
         "record_index": i, "scope": scope, "mapped_year": my}
    return s.Rec(d, v)


def run(file, fy, records, spike=False, status="completed", company="Alpha", cid="AA"):
    for i, r in enumerate(records):
        r.d["record_index"] = r.v["record_index"] = i
    return s.Run(file, company, fy, status, records, cid=cid, spike=spike)


def go(vrows, runs):
    cells, stats = s.build_verified(vrows)
    names = {r["company_id"]: r["company_name"] for r in vrows}
    return s.score(runs, cells, names)


def pair(res, year, scope="1", file=None):
    ps = [p for p in res["pairs"] if p["year"] == year and p["scope"] == scope and (file is None or p["report_file"] == file)]
    assert len(ps) == 1, [(p["report_file"], p["category"]) for p in ps]
    return ps[0]


def count(rows, section, category, detail="", group_type="all", group="all"):
    r = [x for x in rows if x["section"] == section and x["category"] == category and x["detail"] == detail
         and x["group_type"] == group_type and x["group"] == group]
    assert len(r) == 1, (section, category, detail, r)
    return r[0]["count"], r[0]["denominator"]


def test_exact_near_other():
    v = [vrow(s1="1000")]
    p = pair(go(v, [run("a.pdf", 2024, [rec(printed="1000")])]), 2024)
    assert (p["category"], p["tier"]) == ("verified_match", "exact")
    p = pair(go(v, [run("a.pdf", 2024, [rec(printed="1", unit="kt")])]), 2024)
    assert (p["category"], p["tier"]) == ("verified_match", "exact"), "kt converted on the extracted side"
    p = pair(go(v, [run("a.pdf", 2024, [rec(printed="1005")])]), 2024)
    assert (p["category"], p["tier"]) == ("verified_match", "near")
    p = pair(go(v, [run("a.pdf", 2024, [rec(printed="1020")])]), 2024)
    assert (p["category"], p["tier"]) == ("verified_mismatch", "other")
    p = pair(go([vrow(s1="1", unit="kt")], [run("a.pdf", 2024, [rec(printed="1000")])]), 2024)
    assert p["category"] == "verified_match", "kt converted on the verified side"
    print("exact / near / other tiers, unit conversion on both sides: ok")


def test_multiple_candidates():
    v = [vrow(s1="1000")]
    p = pair(go(v, [run("a.pdf", 2024, [rec(printed="1000"), rec(printed="1,000", page=4)])]), 2024)
    assert p["category"] == "verified_match", "equal candidates agree"
    p = pair(go(v, [run("a.pdf", 2024, [rec(printed="1000"), rec(printed="900")])]), 2024)
    assert p["category"] == "ambiguous_extracted" and p["tier"] == "exact"
    p = pair(go(v, [run("a.pdf", 2024, [rec(printed="900"), rec(printed="800")])]), 2024)
    assert p["category"] == "verified_mismatch" and p["multi_candidate"]
    v2 = [vrow(s1="1000"), vrow(s1="1200", url="http://y")]
    p = pair(go(v2, [run("a.pdf", 2024, [rec(printed="1200")])]), 2024)
    assert p["category"] == "ambiguous_verified" and len(p["verified_t"]) == 2
    p = pair(go(v2, [run("a.pdf", 2024, [rec(printed="1100")])]), 2024)
    assert p["category"] == "verified_mismatch"
    v3 = [vrow(s1="1000"), vrow(s1="1000", url="http://z")]
    p = pair(go(v3, [run("a.pdf", 2024, [rec(printed="1000")])]), 2024)
    assert p["category"] == "verified_match" and p["n_primary_rows"] == 2, "two identical primary rows are one value"
    print("several candidates / several verified values -> separate ambiguous categories: ok")


def test_null_mapped_year_and_not_extracted_reasons():
    v = [vrow(s1="1000", s2l="500", s2m="400")]
    r = run("a.pdf", 2024, [rec(printed="1000", mapped=None),                      # s1: unmapped only
                            rec(scope="2_location", printed=None),                 # scope_null
                            rec(scope="2_market", printed="n/a", status="fail", failed=["value_parse"])])
    res = go(v, [r])
    assert pair(res, 2024, "1")["detail"] == "only_unmapped_labels" and pair(res, 2024, "1")["category"] == "not_extracted"
    assert pair(res, 2024, "2_location")["detail"] == "scope_null"
    assert pair(res, 2024, "2_market")["detail"] == "placeholder_value", "placeholder is not a verifier failure"
    assert res["buckets"]["main"][("unmapped", "valued")] == 1
    res = go(v, [run("a.pdf", 2024, [rec(printed="-", status="fail", failed=["value_parse"])])])
    assert pair(res, 2024)["detail"] == "placeholder_value" and not res["failed"]["main"]
    res = go(v, [run("a.pdf", 2024, [rec(scope="2_market", printed="400")])])
    assert pair(res, 2024, "1")["detail"] == "no_record_for_key"
    res = go(v, [run("a.pdf", 2024, [], status="no_pages_found")])
    assert pair(res, 2024)["detail"] == "finder_no_pages"
    print("not_extracted sub-reasons, null mapped_year never guessed, placeholders: ok")


def test_unit_ambiguity_and_sensitivity():
    v = [vrow(s1="1000")]
    for u in ("m t", "tCO2-eq or as indicated", None, "widgets"):
        p = pair(go(v, [run("a.pdf", 2024, [rec(printed="1000", unit=u)])]), 2024)
        assert p["category"] == "unit_ambiguous" and not p["tons_only"], u
    p = pair(go(v, [run("a.pdf", 2024, [rec(printed="1", unit="Thousand metric tons CO2e")])]), 2024)
    assert p["category"] == "verified_match", "metric tons are documented, not ambiguous"
    p = pair(go(v, [run("a.pdf", 2024, [rec(printed="1000", unit="tons CO2e")])]), 2024)
    assert p["category"] == "unit_ambiguous" and p["tons_only"] and p["sens_category"] == "verified_match"
    vv = [vrow(s1="1000", s2l="500")]
    res = go(vv, [run("a.pdf", 2024, [rec(printed="1000", unit="tons"), rec(scope="2_location", printed="5", unit="tons")])])
    rows = s.summary_rows(res)
    assert count(rows, "main_sensitivity_tons", "unit_ambiguous_tons_only", "would_be_verified_match") == (1, 2)
    assert count(rows, "main_pairs", "unit_ambiguous") == (2, 2) and count(rows, "main_pairs", "verified_match")[0] == 0
    p = pair(go([vrow(s1="1000", unit="m t")], [run("a.pdf", 2024, [rec(printed="1000")])]), 2024)
    assert p["category"] == "unit_ambiguous" and "verified_unit" in p["detail"] and not p["tons_only"]
    print("unit_ambiguous (m t, 'as indicated', tons) not scored; tonnes sensitivity '1 of 2' separate: ok")


def test_observed_run_001_units():
    ok = {"tCO2e": 1, "[tCO2e]": 1, "tCO2eq": 1, "KT CO2E": 1000, "Thousand metric tons CO2e": 1000, "tonnes CO2e": 1,
          "tCO2": 1, "(tCO2e)": 1, "tonnes": 1, "Tonnes": 1, "CO2-eq, million tonnes": 10 ** 6,
          "Fossil CO2 equivalent (million tonnes)": 10 ** 6, "million tonnes of CO2 equivalents": 10 ** 6,
          "Fossil CO2 equivalent, million tonnes": 10 ** 6, "tCO₂e": 1}
    for u, f in ok.items():
        kind, _, factor = s.classify_unit(u)
        assert kind == "ok" and factor == f, (u, kind, factor)
    for u in ("tons", "tons CO2e"):
        assert s.classify_unit(u)[0] == "tons"
    for u in ("m t", "tCO2-eq or as indicated", None, ""):
        assert s.classify_unit(u)[0] == "ambiguous", u
    print("every unit string seen in run_001 outputs classified as documented: ok")


def test_spike_exclusion():
    v = [vrow(year=2024, s1="1000"), vrow(year=2025, s1="1000")]
    spike = run("Elisa_AnnualReport_2025.pdf", 2025, [rec(year=2024, printed="1000"), rec(year=2025, printed="1000")], spike=True)
    res = go(v, [spike])
    assert {k["state"] for k in res["key_states"]} == {"spike_only"} and all(p["group"] == "spike" for p in res["pairs"])
    rows = s.summary_rows(res)
    assert not [r for r in rows if r["section"] == "main_pairs"], "no main pair rows"
    assert count(rows, "spike_pairs", "verified_match") == (2, 2)
    assert count(rows, "key_states", "spike_only") == (2, 2)
    both = go(v, [spike, run("b.pdf", 2025, [rec(year=2024, printed="900"), rec(year=2025, printed="1000")])])
    rows = s.summary_rows(both)
    assert count(rows, "main_pairs", "verified_match") == (1, 2) and count(rows, "main_pairs", "verified_mismatch") == (1, 2)
    assert count(rows, "spike_pairs", "verified_match") == (2, 2)
    mm = pair(both, 2024, file="b.pdf")
    assert "vintage_difference" not in mm["labels"], "a spike match never labels a main mismatch as vintage"
    print("spike PDFs: separate rows, excluded from main counts and from vintage comparisons: ok")


def test_vintage_and_year_mapping():
    v = [vrow(year=2023, s1="1000"), vrow(year=2024, s1="1500")]
    res = go(v, [run("fy23.pdf", 2023, [rec(year=2023, printed="1000")]), run("fy24.pdf", 2024, [rec(year=2023, printed="900")])])
    a, b = pair(res, 2023, file="fy23.pdf"), pair(res, 2023, file="fy24.pdf")
    assert a["category"] == "verified_match" and a["labels"] == []
    assert b["category"] == "verified_mismatch" and b["labels"] == ["vintage_difference"]
    res = go(v, [run("fy24.pdf", 2024, [rec(year=2024, printed="1000")])])
    p = pair(res, 2024)
    assert p["category"] == "verified_mismatch" and p["labels"] == ["year_mapping_suspect"], p["labels"]
    flat = go([vrow(year=2023, s1="1000"), vrow(year=2024, s1="1000")], [run("fy24.pdf", 2024, [rec(year=2024, printed="1000")])])
    p = pair(flat, 2024)
    assert p["category"] == "verified_match" and p["labels"] == [] and p["also_matches_other_year"]
    res = go(v + [vrow(year=2022, s1="700")], [run("fy23.pdf", 2023, [rec(year=2023, printed="700")])])
    assert pair(res, 2023)["labels"] == ["year_mapping_suspect"], "other year may lie outside 2023-2025"
    print("vintage_difference, year_mapping_suspect (never a match), flat series stays a match: ok")


def test_failed_verifier_and_table():
    v = [vrow(s1="1000", s2l="500")]
    res = go(v, [run("a.pdf", 2024, [rec(printed="1000", status="fail", failed=["a_quote_on_page", "c_page_index"]),
                                       rec(scope="2_location", printed="5", unit="tons", status="fail", failed=["b_number_matches"])])])
    assert pair(res, 2024)["category"] == "extracted_failed_verifier"
    f = res["failed"]["main"]
    assert sorted(x["tier"] for x in f) == ["exact", "not_comparable"]
    rows = s.summary_rows(res)
    assert count(rows, "main_failed_records_NOT_A_PIPELINE_RESULT", "tier", "exact") == (1, 2)
    assert count(rows, "main_pairs", "verified_match")[0] == 0, "failed records never enter the main result"
    print("verifier-failed records: own category and own table, never in the main result: ok")


def test_key_states_and_r2_window():
    v = [vrow(year=2023, s1="1"), vrow(year=2024, s1="1"), vrow(year=2025, s1="1")]
    res = go(v, [run("fy25.pdf", 2025, [rec(year=2023, printed="1"), rec(year=2024, printed="1"), rec(year=2025, printed="1"),
                                          rec(year=2019, printed="9"), rec(year=2024, scope="2_market", printed="3")])])
    st = {k["year"]: k["state"] for k in res["key_states"]}
    assert st == {2023: "no_source_pdf", 2024: "has_main_pair", 2025: "has_main_pair"}
    b = res["buckets"]["main"]
    assert b[("outside_r2_window", "")] == 1 and b[("year_outside_2023_2025", "")] == 1 and b[("no_verified_key", "")] == 1
    assert b[("in_pair_scope", "")] == 2 and sum(b.values()) == res["n_records"] == 5
    rows = s.summary_rows(res)
    assert count(rows, "key_states", "no_source_pdf") == (1, 3)
    assert sum(count(rows, "key_states", c)[0] for c in ("no_source_pdf", "spike_only", "has_main_pair")) == 3
    print("no_source_pdf, R2 window, record buckets add up to the record count: ok")


def test_excluded_sources():
    v = [vrow(year=2024, s1="1000", st="primary"), vrow(year=2024, s1="2000", st="third_party"),
         vrow(year=2024, s2l="500", st="from_notes"), vrow(year=2024, s2m="400", st="third_party"),
         vrow(year=2023, s1="700", st="derived")]
    res = go(v, [run("a.pdf", 2024, [rec(printed="2000"), rec(scope="2_location", printed="500")])])
    p = pair(res, 2024, "1")
    assert p["category"] == "verified_mismatch" and p["n_third_party_ignored"] == 1 and p["verified_t"] == ["1000"]
    assert [k["scope"] for k in res["key_states"]] == ["1"], "only keys with a primary cell are in N"
    rows = s.summary_rows(res)
    assert count(rows, "excluded_keys", "derived_not_extractable")[0] == 2
    assert count(rows, "excluded_keys", "third_party_only")[0] == 1
    assert s.classify_source_type("weird") == "unclassified"
    print("third_party and derived rows excluded from ground truth and counted: ok")


def test_thousands_flag_and_sums():
    v = [vrow(s1="1000", s2l="500", s2m="400")]
    res = go(v, [run("a.pdf", 2024, [rec(printed="1,000", flags=["assumed_thousands_separator"]),
                                       rec(scope="2_location", printed="500"), rec(scope="2_market", printed="999")])])
    rows = s.summary_rows(res)
    assert count(rows, "main_pair_detail", "verified_match", "assumed_thousands_separator") == (1, 2)
    assert sum(count(rows, "main_pairs", c)[0] for c in s.CATEGORIES) == count(rows, "main_pairs", "verified_match")[1] == 3
    md = s.summary_md(rows, [])
    assert "%" not in md and " of " in md
    print("assumed_thousands_separator counted among matches; categories add up to P; no percentages: ok")


def test_adjudication_rows():
    v = [vrow(year=2023, s1="1000", url="http://src", page="12", notes="restated"), vrow(year=2024, s1="1500")]
    res = go(v, [run("fy23.pdf", 2023, [rec(year=2023, printed="1000")]),
                 run("fy24.pdf", 2024, [rec(year=2023, printed="900", quote="Q", page=7)])])
    adj = s.adjudication_rows(res)
    assert len(adj) == 1 and len(adj[0]) == len(s.ADJ_COLUMNS)
    row = dict(zip(s.ADJ_COLUMNS, adj[0]))
    assert row["report_file"] == "fy24.pdf" and row["labels"] == "vintage_difference" and row["quote"] == "Q"
    assert row["verified_source_url"] == "http://src" and row["verified_notes"] == "restated" and row["pdf_page"] == 7
    assert row["human_verdict"] == "" and row["human_notes"] == "", "verdict columns stay empty"
    print("adjudication list: mismatches and labels only, verified provenance copied, verdict columns empty: ok")


def test_report_type_source_types_and_notes_tokens():
    assert s.classify_source_type("annual_report") == s.classify_source_type("sustainability_report") == "primary"
    for tok in ("from_notes", "DERIVED", "Calculated from delta", "was Computed"):
        assert s.classify_cell("annual_report", f"note: {tok}") == "derived", tok
    assert s.classify_cell("annual_report", "estimated, restated") == "primary", "token list is not widened"
    assert s.classify_cell("third_party", "derived") == "third_party", "third_party stays third_party"
    v = [vrow(year=2024, s1="1000", st="annual_report", notes="Scope 1 derived from stated delta"),
         vrow(year=2024, s2l="500", st="sustainability_report", notes="plain"),
         vrow(year=2024, s2l="900", st="sustainability_report", notes="computed", url="http://d")]
    cells, stats = s.build_verified(v)
    assert stats["rows_derived_by_notes_2023_2025"] == 2 and stats["cells_derived_by_notes_1"] == 1
    assert stats["cells_derived_by_notes_2_location"] == 1
    res = go(v, [run("a.pdf", 2024, [rec(printed="1000"), rec(scope="2_location", printed="500")])])
    assert [k["scope"] for k in res["key_states"]] == ["2_location"], "derived-only key is outside N"
    p = pair(res, 2024, "2_location")
    assert p["category"] == "verified_match" and p["n_derived_ignored"] == 1 and p["verified_t"] == ["500"]
    rows = s.summary_rows(res)
    assert count(rows, "excluded_keys", "derived_not_extractable", "", "scope", "1") == (1, 1)
    assert count(rows, "excluded_keys", "eligible_keys_with_derived_cells_ignored", "", "scope", "2_location") == (1, 1)
    print("annual_report / sustainability_report are primary; notes tokens make derived cells (excluded, counted): ok")


def test_company_map():
    rows = [vrow(cid="WRT1V.HE", name="Wärtsilä Oyj"), vrow(cid="KNEBV.HE", name="KONE Oyj"), vrow(cid="NDA-FI.HE", name="Nordea Bank Abp"),
            vrow(cid="NESTE.HE", name="Neste Oyj")]
    m, bad = s.build_company_map(["Wärtsilä", "KONE", "Nordea", "Neste", "Unknown Co"], rows)
    assert m == {"Wärtsilä": "WRT1V.HE", "KONE": "KNEBV.HE", "Nordea": "NDA-FI.HE", "Neste": "NESTE.HE"} and bad[0][0] == "Unknown Co"
    print("company join by normalised name: ok")


def test_run_once_guards():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        saved = (s.OUT_DIR, s.MANIFEST, s.RULES_MD)
        try:
            s.OUT_DIR, s.MANIFEST, s.RULES_MD = out, out / "scoring_manifest.json", out / "scoring_rules.md"
            s.RULES_MD.write_text("rules v1", encoding="utf-8")
            try:
                s.guard_run()
                raise AssertionError("no manifest must refuse")
            except SystemExit:
                pass
            s.write_manifest()
            s.guard_run()  # hashes match, no results yet
            s.RULES_MD.write_text("rules v2", encoding="utf-8")
            try:
                s.guard_run()
                raise AssertionError("changed rules must refuse")
            except SystemExit as e:
                assert "hash differs" in str(e)
            s.RULES_MD.write_text("rules v1", encoding="utf-8")
            (out / "results_by_key.csv").write_text("x", encoding="utf-8")
            try:
                s.guard_run()
                raise AssertionError("second run must refuse")
            except SystemExit as e:
                assert "ONCE" in str(e)
        finally:
            s.OUT_DIR, s.MANIFEST, s.RULES_MD = saved
    print("guards: missing manifest, changed rules hash, second run all refused: ok")


if __name__ == "__main__":
    test_exact_near_other()
    test_multiple_candidates()
    test_null_mapped_year_and_not_extracted_reasons()
    test_unit_ambiguity_and_sensitivity()
    test_observed_run_001_units()
    test_spike_exclusion()
    test_vintage_and_year_mapping()
    test_failed_verifier_and_table()
    test_key_states_and_r2_window()
    test_excluded_sources()
    test_thousands_flag_and_sums()
    test_adjudication_rows()
    test_report_type_source_types_and_notes_tokens()
    test_company_map()
    test_run_once_guards()
    print("all tests passed")
