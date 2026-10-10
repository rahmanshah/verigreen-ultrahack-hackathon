import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verigreen.quality_checks import (check_emissions, check_intensity,  # noqa: E402
                                      check_prices, check_ratings)
from verigreen.carbon_intensity import build_carbon_intensity  # noqa: E402
from verigreen.price_cleaning import build_cleaned_prices  # noqa: E402
from verigreen.naive_vs_trusted import validate_naive_vs_trusted  # noqa: E402
from scripts.verify_financials import classify  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
YEARS = [2022, 2023, 2024]


def em(**kw):
    base = dict(company_id="AAA", company_name="A Oyj", fiscal_year=2024, scope1=100.0,
                scope2_location=20.0, scope2_market=10.0, unit="ktCO2e",
                boundary="operational_control", source_type="sustainability_report",
                source_url="https://x", source_page=1)
    base.update(kw)
    return base


def ids(flags):
    return set(flags["check_id"])


def test_units_converted_to_tonnes_and_market_scope2_preferred():
    silver, _ = check_emissions(pd.DataFrame([em()]), [2024])
    row = silver.iloc[0]
    assert row["scope1_t"] == 100_000
    assert row["scope2_method"] == "market"
    assert row["scope12_t"] == 110_000


def test_example_rows_from_templates_never_reach_silver():
    silver, flags = check_emissions(pd.read_csv(TEMPLATES / "emissions_raw.csv"), YEARS)
    assert silver.empty and flags.empty


def test_bad_unit_and_negative_value_are_errors():
    _, flags = check_emissions(pd.DataFrame([em(unit="tonnes"), em(company_id="BBB", scope1=-5)]), [2024])
    assert {"E02", "E03"} <= ids(flags)


def test_gap_is_flagged_for_each_missing_year():
    _, flags = check_emissions(pd.DataFrame([em(fiscal_year=2024)]), YEARS)
    gaps = flags[flags["check_id"] == "E07"]
    assert sorted(gaps["fiscal_year"]) == [2022, 2023]


def test_yoy_jump_catches_likely_unit_error():
    rows = [em(fiscal_year=2023, scope1=100.0), em(fiscal_year=2024, scope1=100_000.0, unit="tCO2e"),
            em(fiscal_year=2022, scope1=100.0, unit="tCO2e")]  # 2022 entered in t instead of kt
    _, flags = check_emissions(pd.DataFrame(rows), YEARS)
    jumps = flags[flags["check_id"] == "E08"]
    assert list(jumps["fiscal_year"]) == [2023]  # 2022->2023 is x1000; 2023->2024 is unchanged


def test_ets_above_reported_scope1_is_error_but_below_is_fine():
    rows = [em(), em(source_type="eu_ets", scope1=130.0),
            em(company_id="BBB"), em(company_id="BBB", source_type="eu_ets", scope1=80.0)]
    _, flags = check_emissions(pd.DataFrame(rows), [2024])
    e09 = flags[flags["check_id"] == "E09"]
    assert list(e09["company_id"]) == ["AAA"]


def test_primary_sources_disagreeing_flagged_and_preferred_source_kept():
    rows = [em(source_type="annual_report", scope1=100.0), em(source_type="sustainability_report", scope1=80.0)]
    silver, flags = check_emissions(pd.DataFrame(rows), [2024])
    assert "E05" in ids(flags)
    assert silver.iloc[0]["source_type"] == "sustainability_report"


def test_unknown_source_type_is_error_and_third_party_ranks_last():
    rows = [em(source_type="blog"), em(company_id="BBB", source_type="third_party", scope1=100.0),
            em(company_id="BBB", source_type="annual_report", scope1=100.0)]
    silver, flags = check_emissions(pd.DataFrame(rows), [2024])
    assert "E12" in ids(flags)
    assert silver.set_index("company_id").loc["BBB", "source_type"] == "annual_report"


def test_intensity_outlier_vs_sector_peers():
    emis = pd.DataFrame({"company_id": list("ABCD"), "fiscal_year": 2024,
                         "scope12_t": [1_000.0, 1_100.0, 900.0, 1_000_000.0]})
    fin = pd.DataFrame({"company_id": list("ABCD"), "fiscal_year": 2024, "revenue_eur_m": 100.0})
    comp = pd.DataFrame({"company_id": list("ABCD"), "sector": "Materials"})
    flags = check_intensity(emis, fin, comp)
    assert list(flags["company_id"]) == ["D"]


def test_provider_conflict_uses_ranks_not_raw_scales():
    # MSCI: A best, D worst. Sustainalytics (risk, lower = better): D best, A worst.
    rows = []
    for cid, letter, risk in [("A", "AAA", 40.0), ("B", "AA", 25.0), ("C", "BBB", 20.0), ("D", "CCC", 8.0)]:
        rows += [dict(company_id=cid, provider="MSCI", rating_raw=letter, rating_scale="msci_letter",
                      rating_date="2026-06-01"),
                 dict(company_id=cid, provider="Sustainalytics", rating_raw=risk,
                      rating_scale="sustainalytics_risk", rating_date="2024-01-01")]
    wide, flags = check_ratings(pd.DataFrame(rows), as_of="2026-09-26")
    conflicted = set(wide.loc[wide["provider_conflict"], "company_id"])
    assert {"A", "D"} <= conflicted
    assert "R02" in ids(flags)  # Sustainalytics dates are stale


def test_invalid_rating_value():
    rows = [dict(company_id="A", provider="MSCI", rating_raw="AAAA", rating_scale="msci_letter",
                 rating_date="2026-06-01")]
    _, flags = check_ratings(pd.DataFrame(rows), as_of="2026-09-26")
    assert "R01" in ids(flags)


def test_price_spike_gap_and_stale_run():
    dates = list(pd.bdate_range("2026-01-05", periods=10)) + [pd.Timestamp("2026-02-02")]
    px = [10, 10, 10, 10, 10, 10, 11, 20, 20.5, 21, 21]
    flags = check_prices(pd.DataFrame({"date": dates, "company_id": "A", "adj_close": px}))
    assert {"P02", "P03", "P04"} <= ids(flags)


def test_carbon_intensity_blank_when_scope2_location_missing():
    silver, _ = check_emissions(pd.DataFrame([em(scope2_location=None)]), [2024])
    fin = pd.DataFrame([dict(company_id="AAA", fiscal_year=2024, revenue_eur_m=1000.0, source_url="x")])
    row = build_carbon_intensity(silver, fin).iloc[0]
    assert pd.isna(row["intensity_location_tco2e_per_eurm"])
    assert row["intensity_market_tco2e_per_eurm"] == (100_000 + 10_000) / 1000.0


def test_carbon_intensity_blank_when_revenue_missing():
    silver, _ = check_emissions(pd.DataFrame([em()]), [2024])
    fin = pd.DataFrame(columns=["company_id", "fiscal_year", "revenue_eur_m", "source_url"])
    row = build_carbon_intensity(silver, fin).iloc[0]
    assert pd.isna(row["intensity_market_tco2e_per_eurm"])
    assert pd.isna(row["intensity_location_tco2e_per_eurm"])


def test_carbon_intensity_blank_not_inf_when_revenue_zero():
    silver, _ = check_emissions(pd.DataFrame([em()]), [2024])
    fin = pd.DataFrame([dict(company_id="AAA", fiscal_year=2024, revenue_eur_m=0.0, source_url="x")])
    row = build_carbon_intensity(silver, fin).iloc[0]
    assert pd.isna(row["intensity_market_tco2e_per_eurm"])  # blank, not inf (pd.isna(inf) is False)
    assert pd.isna(row["intensity_location_tco2e_per_eurm"])


def test_carbon_intensity_no_fallback_between_scope2_methods():
    # market missing, location present -> market stays blank, NOT filled from location
    # (unlike check_emissions' combined scope12_t, which does fall back).
    silver, _ = check_emissions(pd.DataFrame([em(scope2_market=None)]), [2024])
    fin = pd.DataFrame([dict(company_id="AAA", fiscal_year=2024, revenue_eur_m=1000.0, source_url="x")])
    row = build_carbon_intensity(silver, fin).iloc[0]
    assert pd.isna(row["intensity_market_tco2e_per_eurm"])
    assert row["intensity_location_tco2e_per_eurm"] == (100_000 + 20_000) / 1000.0


def test_carbon_intensity_uses_tonnes_already_converted_by_silver():
    rows = [em(scope1=0.002, scope2_location=0.0005, scope2_market=0.0003, unit="MtCO2e")]
    silver, _ = check_emissions(pd.DataFrame(rows), [2024])
    fin = pd.DataFrame([dict(company_id="AAA", fiscal_year=2024, revenue_eur_m=500.0, source_url="x")])
    row = build_carbon_intensity(silver, fin).iloc[0]
    assert row["scope1_t"] == 2000.0  # 0.002 Mt -> 2,000 t
    assert row["intensity_market_tco2e_per_eurm"] == (2000.0 + 300.0) / 500.0


def test_carbon_intensity_boundary_match_defaults_true():
    silver, _ = check_emissions(pd.DataFrame([em()]), [2024])
    fin = pd.DataFrame([dict(company_id="AAA", fiscal_year=2024, revenue_eur_m=1000.0, source_url="x")])
    row = build_carbon_intensity(silver, fin).iloc[0]
    assert row["boundary_match"] == "true"


def test_carbon_intensity_boundary_match_overridden_by_review():
    silver, _ = check_emissions(pd.DataFrame([em()]), [2024])
    fin = pd.DataFrame([dict(company_id="AAA", fiscal_year=2024, revenue_eur_m=1000.0, source_url="x")])
    reviews = pd.DataFrame([dict(company_id="AAA", fiscal_year=2024, boundary_match="unknown",
                                 reason="revenue source document differs from emissions source document")])
    row = build_carbon_intensity(silver, fin, reviews).iloc[0]
    assert row["boundary_match"] == "unknown"
    assert "differs from emissions source" in row["notes"]


def test_carbon_intensity_rejects_unknown_boundary_match_value():
    silver, _ = check_emissions(pd.DataFrame([em()]), [2024])
    fin = pd.DataFrame([dict(company_id="AAA", fiscal_year=2024, revenue_eur_m=1000.0, source_url="x")])
    reviews = pd.DataFrame([dict(company_id="AAA", fiscal_year=2024, boundary_match="maybe", reason="x")])
    try:
        build_carbon_intensity(silver, fin, reviews)
        raise AssertionError("expected ValueError for invalid boundary_match")
    except ValueError:
        pass


def test_carbon_intensity_notes_stora_enso_boundary_choice():
    rows = [em(company_id="STERV.HE", company_name="Stora Enso Oyj", boundary="operational_control")]
    silver, _ = check_emissions(pd.DataFrame(rows), [2024])
    fin = pd.DataFrame([dict(company_id="STERV.HE", fiscal_year=2024, revenue_eur_m=1000.0, source_url="x")])
    row = build_carbon_intensity(silver, fin).iloc[0]
    assert "operational-control" in row["notes"]


def _fin_row(**kw):
    base = dict(company_id="AAA", fiscal_year=2024, revenue_eur_m=1000.0,
               source_url="Some Annual Report 2024, p.1", notes="")
    base.update(kw)
    return pd.Series(base)


def test_verify_financials_classifies_yfinance_source():
    row = _fin_row(source_url="yfinance Ticker.income_stmt (Total Revenue)")
    source, error = classify(row, {("AAA", 2024): 1000.0})
    assert source == "yfinance" and error is None


def test_verify_financials_classifies_matching_primary_as_primary_report():
    row = _fin_row(revenue_eur_m=1000.0)
    source, error = classify(row, {("AAA", 2024): 1005.0})  # 0.5% apart
    assert source == "primary_report" and error is None


def test_verify_financials_flags_unexplained_mismatch():
    row = _fin_row(revenue_eur_m=1000.0, notes="no justification given")
    source, error = classify(row, {("AAA", 2024): 500.0})  # 100% apart
    assert source == "override" and error is not None


def test_verify_financials_accepts_documented_override():
    row = _fin_row(revenue_eur_m=1000.0, notes="OVERRIDE of yfinance: chose the report figure because ...")
    source, error = classify(row, {("AAA", 2024): 500.0})
    assert source == "override" and error is None


def test_verify_financials_blank_revenue_classified_blank():
    row = _fin_row(revenue_eur_m=float("nan"))
    source, error = classify(row, {("AAA", 2024): 1000.0})
    assert source == "" and error is None


def _prices_with_spike():
    return pd.DataFrame({
        "date": pd.bdate_range("2026-01-05", periods=5),
        "company_id": "A",
        "adj_close": [10.0, 10.0, 13.0, 10.0, 10.0],
    })


def test_price_cleaning_leaves_unconfirmed_anomaly_untouched():
    reviews = pd.DataFrame([dict(company_id="A", date="2026-01-07", check_id="P02",
                                 status="unconfirmed", treatment="none",
                                 reason="no second source", reviewed_date="2026-10-02")])
    out = build_cleaned_prices(_prices_with_spike(), reviews)
    row = out[out["date"] == pd.Timestamp("2026-01-07")].iloc[0]
    assert row["adj_close_cleaned"] == 13.0  # unconfirmed -> left exactly as reported
    assert row["anomaly_status"] == "unconfirmed"


def test_price_cleaning_interpolates_confirmed_bad_tick():
    reviews = pd.DataFrame([dict(company_id="A", date="2026-01-07", check_id="P02",
                                 status="confirmed_bad_tick", treatment="interpolate",
                                 reason="confirmed via exchange notice", reviewed_date="2026-10-02")])
    out = build_cleaned_prices(_prices_with_spike(), reviews)
    row = out[out["date"] == pd.Timestamp("2026-01-07")].iloc[0]
    assert row["adj_close_cleaned"] == 10.0  # average of its two neighbours (10, 10)


def test_price_cleaning_rejects_unknown_status():
    prices = pd.DataFrame({"date": ["2026-01-05"], "company_id": "A", "adj_close": [10.0]})
    reviews = pd.DataFrame([dict(company_id="A", date="2026-01-05", check_id="P02",
                                 status="bogus", treatment="none", reason="x", reviewed_date="2026-10-02")])
    try:
        build_cleaned_prices(prices, reviews)
        raise AssertionError("expected ValueError for unknown status")
    except ValueError:
        pass


def _nvt_row(**kw):
    base = dict(company_id="AAA", company_name="A Oyj", fiscal_year=2024, error_category="unit_error",
                raw_scope1=120.0, raw_scope2_location=20.0, raw_scope2_market=10.0,
                raw_combined_footprint=None, raw_combined_footprint_label=None,
                trusted_scope1=100.0, trusted_scope2_location=20.0, trusted_scope2_market=10.0,
                unit="tCO2e", raw_source="Report AR2024 p.39", trusted_source="emissions_raw AAA 2024",
                notes="x", verification_status="verified_pdf")
    base.update(kw)
    return base


def _nvt_problems(**kw):
    raw = pd.DataFrame([em(unit="tCO2e", scope1=100.0, scope2_location=20.0, scope2_market=10.0)])
    return validate_naive_vs_trusted(pd.DataFrame([_nvt_row(**kw)]), raw)


def test_naive_vs_trusted_valid_row_has_no_problems():
    assert _nvt_problems() == []


def test_naive_vs_trusted_rejects_unknown_category_and_status():
    msgs = " ".join(_nvt_problems(error_category="bogus", verification_status="guessed"))
    assert "unknown error_category" in msgs and "unknown verification_status" in msgs


def test_naive_vs_trusted_trusted_values_must_match_an_emissions_raw_row():
    assert any("match no emissions_raw row" in m for m in _nvt_problems(trusted_scope1=99.0))


def test_naive_vs_trusted_verified_pdf_needs_page_but_from_notes_does_not():
    assert any("cite a page" in m for m in _nvt_problems(raw_source="Report AR2024"))
    assert _nvt_problems(raw_source="Report AR2024", verification_status="from_notes") == []


def test_naive_vs_trusted_rejects_identical_raw_and_trusted():
    assert any("identical" in m for m in _nvt_problems(raw_scope1=100.0))


def test_naive_vs_trusted_one_row_per_company_year_category():
    raw = pd.DataFrame([em(unit="tCO2e", scope1=100.0, scope2_location=20.0, scope2_market=10.0)])
    two = pd.DataFrame([_nvt_row(), _nvt_row(raw_scope1=130.0)])
    assert any("duplicate row" in m for m in validate_naive_vs_trusted(two, raw))
    other_cat = pd.DataFrame([_nvt_row(), _nvt_row(error_category="pre_restatement")])
    assert validate_naive_vs_trusted(other_cat, raw) == []


def test_naive_vs_trusted_real_file_is_consistent_with_emissions_raw():
    nvt = pd.read_csv(ROOT / "data/bronze/emissions_naive_vs_trusted.csv")
    raw = pd.read_csv(ROOT / "data/bronze/emissions_raw.csv")
    assert validate_naive_vs_trusted(nvt, raw) == []


def test_real_emissions_flags_are_the_seven_documented_ones():
    raw = pd.read_csv(ROOT / "data/bronze/emissions_raw.csv")
    _, flags = check_emissions(raw, [2023, 2024, 2025])
    got = sorted(zip(flags["check_id"], flags["company_id"], flags["fiscal_year"]))
    assert got == [("E05", "METSO.HE", 2023), ("E05", "STERV.HE", 2024), ("E05", "STERV.HE", 2025),
                   ("E08", "ELISA.HE", 2024), ("E08", "ELISA.HE", 2025),
                   ("E08", "NDA-FI.HE", 2024), ("E08", "NOKIA.HE", 2024)]


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(tests)} passed")
