"""Self-tests for the extraction verifier. Made-up page texts and values only (fictional "Testco"); no PDFs, no
verified data, no network.

    <side env python> scripts/extraction/test_verifier.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from verifier import unit_factor, verify  # noqa: E402

PAGES = {
    1: "Testco GHG emissions\nScope 1 emissions 1,234 t CO2e in 2025\n",
    2: "Energy use\nScope 1 emissions 1.2 kt CO2e (2024)\n",
    3: "Scope 1 emissions 0.5 Mt CO2e in 2023\nScope 1 (tCO2e) 2025 2024\n1 027 622 1 013 282\n",
    4: "Correction: -150 t\n",
    5: "Scope 2 market-based 50,000 t CO2e\nScope 2 location-based 3,000 t CO2e\nScope 2 location-based 10,000 t CO2e\n",
    6: "Scope 1 (t) 2025 2024\n1 027 622 1 013 282\n",
    7: "Gross Scope 1 (tCO2eq)\n1,458\n925\n",
}


def rec(value, unit, page, quote, scope="1", year=2025, null_reason=None):
    return {"company": "Testco", "scope": scope, "year": year, "value": value, "unit_as_printed": unit,
            "pdf_page": page, "quote": quote, "note": None, "null_reason": null_reason}


def one(r, sent=None):
    return verify([r], PAGES, sent)[0]


def test_unit_factors():
    assert unit_factor("t CO2e") == 1 and unit_factor("tCO₂e") == 1 and unit_factor("tonnes CO2e") == 1
    assert unit_factor("kt CO2e") == 1000 and unit_factor("thousand tonnes") == 1000 and unit_factor("'000 t") == 1000
    assert unit_factor("Mt CO2e") == 1_000_000 and unit_factor("million tonnes") == 1_000_000
    assert unit_factor("MWh") is None and unit_factor(None) is None


def test_comma_thousands_1234_t():
    r = one(rec(1234, "t CO2e", 1, "Scope 1 emissions 1,234 t CO2e"))
    assert r["status"] == "pass", r
    r = one(rec(1243, "t CO2e", 1, "Scope 1 emissions 1,234 t CO2e"))
    assert r["status"] == "fail" and r["failed"] == ["b_number_matches"], r


def test_decimal_kt_1_2_kt():
    assert one(rec(1.2, "kt CO2e", 2, "Scope 1 emissions 1.2 kt CO2e"))["status"] == "pass"
    # unit printed in the quote overrides unit_as_printed: 1.2 kt == 1,200 t
    assert one(rec(1200, "t CO2e", 2, "Scope 1 emissions 1.2 kt CO2e"))["status"] == "pass"
    r = one(rec(12, "kt CO2e", 2, "Scope 1 emissions 1.2 kt CO2e"))
    assert r["failed"] == ["b_number_matches"], r


def test_megatonnes_0_5_mt():
    q = "Scope 1 emissions 0.5 Mt CO2e"
    for value, unit in ((0.5, "Mt CO2e"), (500, "kt CO2e"), (500000, "t CO2e")):
        assert one(rec(value, unit, 3, q, year=2023))["status"] == "pass", (value, unit)
    r = one(rec(50000, "t CO2e", 3, q, year=2023))
    assert r["failed"] == ["b_number_matches"], r


def test_space_separated_table_row_with_nbsp():
    q = "1 027 622 1 013 282"
    assert one(rec(1027622, "tCO2e", 3, q))["status"] == "pass"
    assert one(rec(1013282, "tCO2e", 3, q, year=2024))["status"] == "pass"
    assert one(rec(1027, "tCO2e", 3, q))["status"] == "ambiguous"  # "1 027" is only a fragment of "1 027 622"
    assert one(rec(27622, "tCO2e", 3, q))["failed"] == ["b_number_matches"]  # "027 622" is not a valid grouping


def test_fragment_of_grouped_number_is_ambiguous_whole_number_passes():
    q = "1 027 622 1 013 282"
    r = one(rec(1027, "t", 6, q))
    assert r["status"] == "ambiguous" and r["ambiguous"] == ["b_number_matches"] and not r["failed"], r
    assert "1 027" in r["details"]["b_number_matches"]
    for v in (1027622, 1013282):
        r = one(rec(v, "t", 6, q))
        assert r["status"] == "pass" and not r["ambiguous"], r
    for v in (622, 282, 1013):  # also fragments
        assert one(rec(v, "t", 6, q))["status"] == "ambiguous", v
    assert one(rec(1027623, "t", 6, q))["failed"] == ["b_number_matches"]
    assert one(rec(1.2, "kt", 2, "Scope 1 emissions 1.2 kt CO2e", year=2024))["status"] == "pass"  # "1" alone is a fragment, 1.2 is whole


def test_line_break_is_a_cell_boundary():
    q = "Gross Scope 1 (tCO2eq)\n1,458\n925"
    r = one(rec(925, "tCO2eq", 7, q))
    assert r["status"] == "pass" and not r["ambiguous"], r
    assert one(rec(1458, "tCO2eq", 7, q))["status"] == "pass"
    r = one(rec(458925, "tCO2eq", 7, q))
    assert r["status"] == "fail" and r["failed"] == ["b_number_matches"], r


def test_quote_not_on_page():
    r = one(rec(1234, "t CO2e", 1, "Scope 1 emissions 4,321 t CO2e"))
    assert r["status"] == "fail"
    assert "a_quote_on_page" in r["failed"] and "c_page_index" in r["failed"], r
    assert "none" in r["details"]["c_page_index"]


def test_wrong_page_index():
    r = one(rec(1.2, "kt CO2e", 1, "Scope 1 emissions 1.2 kt CO2e", year=2024))  # quote is on page 2
    assert set(r["failed"]) == {"a_quote_on_page", "c_page_index"}, r
    assert "[2], cited 1" in r["details"]["c_page_index"]
    r = one(rec(1.2, "kt CO2e", 99, "Scope 1 emissions 1.2 kt CO2e", year=2024))
    assert "outside the document" in r["details"]["a_quote_on_page"]


def test_cited_page_not_among_sent_pages():
    r = one(rec(1234, "t CO2e", 1, "Scope 1 emissions 1,234 t CO2e"), sent=[2, 3])
    assert r["failed"] == ["c_page_index"] and "not among the pages sent" in r["details"]["c_page_index"], r


def test_negative_value():
    r = one(rec(-150, "t", 4, "Correction: -150 t"))
    assert r["status"] == "fail" and r["failed"] == ["d_sanity"], r


def test_scope2_market_vs_location_more_than_10x_is_flagged_not_failed():
    rs = verify([rec(50000, "t CO2e", 5, "Scope 2 market-based 50,000 t CO2e", scope="2_market"),
                 rec(3000, "t CO2e", 5, "Scope 2 location-based 3,000 t CO2e", scope="2_location")], PAGES)
    assert all(r["status"] == "pass" for r in rs), rs
    assert all(r["flags"] and "ratio 16.7 > 10" in r["flags"][0] for r in rs), rs
    rs = verify([rec(50000, "t CO2e", 5, "Scope 2 market-based 50,000 t CO2e", scope="2_market"),
                 rec(10000, "t CO2e", 5, "Scope 2 location-based 10,000 t CO2e", scope="2_location")], PAGES)
    assert not any(r["flags"] for r in rs), rs  # 5x: same order of magnitude


def test_null_needs_reason():
    assert one(rec(None, None, None, None, null_reason="2023 not on supplied pages"))["status"] == "not_stated"
    r = one(rec(None, None, None, None))
    assert r["status"] == "fail" and r["failed"] == ["null_reason"], r


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(tests)} passed")
