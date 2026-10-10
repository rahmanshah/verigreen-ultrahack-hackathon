"""Self-tests for run_phase_a.py. Made-up inputs only; no API call, no PDF, no real data.

    <side env python> -X utf8 scripts/extraction_eval/test_run_phase_a.py
"""
import csv
import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))
import run_phase_a as r  # noqa: E402


class StubClient:
    """Stands in for the OpenAI client and counts calls. Replies with a fixed made-up response."""

    def __init__(self, records=None):
        self.calls = 0
        self.records = records or []
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **params):
        self.calls += 1
        usage = SimpleNamespace(input_tokens=1000, output_tokens=200,
                                output_tokens_details=SimpleNamespace(reasoning_tokens=50))
        return SimpleNamespace(status="completed", model="stub-model", id="resp_stub", usage=usage,
                               incomplete_details=None, output_text=json.dumps({"records": self.records}),
                               model_dump_json=lambda indent=2: json.dumps({"stub": True}))


PAGE = ("Gross Scope 1 (tCO2e)\nBase year 1999\n2030\n2031\n1,000\n900\n800\n"
        "Gross location-based Scope 2 (tCO2e)\n500\n400\n300\n"
        "Gross market-based Scope 2 (tCO2e)\n50\n40\n30\n")
TEXTS = {1: "cover page, nothing here", 2: PAGE, 3: "Scope 1 and Scope 2 market-based location-based tCO2e 1 2 3"}
ENTRY = ("made_up_report.pdf", "Madeup Co", 2031, "sustainability report")


def rec(scope, label, mapped, value, unit="tCO2e", quote=None, page=2, note=None, reason=None):
    return {"scope": scope, "year_label_as_printed": label, "mapped_year": mapped, "value_as_printed": value,
            "unit_as_printed": unit, "pdf_page": page, "quote": quote, "note": note, "null_reason": reason}


def make_ctx(tmp, cap, client):
    return r.Ctx(client=client, run_dir=Path(tmp), cap_eur=cap,
                 prompt=r.PROMPT_FILE.read_text(encoding="utf-8"), schema=json.loads(r.SCHEMA_FILE.read_text(encoding="utf-8")))


def test_parse():
    cases = {"1,234,567": (1234567, None), "1 027 622": (1027622, None), "448.6": (Decimal("448.6"), None),
             "12,3": (Decimal("12.3"), None), "1.234,5": (Decimal("1234.5"), None),
             "1,234.5": (Decimal("1234.5"), None), "1 234,5": (Decimal("1234.5"), None),
             "1,234": (1234, "assumed_thousands_separator"), "0,5": (Decimal("0.5"), None), "-5": (-5, None),
             "300": (300, None)}
    for s, (want, flag) in cases.items():
        v, rule, fl = r.parse_printed_number(s)
        assert v == Decimal(str(want)) and fl == flag, (s, v, rule, fl)
    for bad in ("n/a", "12,34,567", "–", "1 2", "", "1,234,", "007"):
        assert r.parse_printed_number(bad)[0] is None, bad
    assert r.parse_printed_number(None)[0] is None
    print("parse_printed_number: ok")


def test_cap_refused_no_api_call():
    with tempfile.TemporaryDirectory() as tmp:
        client = StubClient()
        ctx = make_ctx(tmp, cap=1e-9, client=client)  # tiny cap
        try:
            r.run_one(ctx, ENTRY, TEXTS)
        except r.CapRefused as e:
            print(f"cap test: call REFUSED -> {e}")
        else:
            raise AssertionError("expected CapRefused")
        assert client.calls == 0, "API was called despite the refusal"
        assert not (Path(tmp) / "cost_ledger.csv").exists()
        print(f"cap test: API calls made = {client.calls}, ledger rows = 0  -> ok")
        # availability call is guarded the same way
        try:
            r.availability_call(ctx)
        except r.CapRefused:
            pass
        else:
            raise AssertionError("availability call not guarded")
        assert client.calls == 0
        print("cap test: availability call also refused, API calls made = 0 -> ok")


def test_stop_at_80_percent():
    with tempfile.TemporaryDirectory() as tmp:
        client = StubClient()
        ctx = make_ctx(tmp, cap=10.0, client=client)
        ctx.cum_eur = 8.0
        try:
            r.run_one(ctx, ENTRY, TEXTS)
        except r.StopAtEightyPercent as e:
            print(f"80% test: STOPPED -> {e}")
        else:
            raise AssertionError("expected StopAtEightyPercent")
        assert client.calls == 0
        print("80% test: API calls made = 0 -> ok")


def test_control_call_goes_through_and_is_verified():
    """Control: with a normal cap the stub IS called (so the zero above means something), output is verified."""
    q_s1 = "Gross Scope 1 (tCO2e)\nBase year 1999\n2030\n2031\n1,000\n900\n800"
    recs = [rec("1", "Base year 1999", None, "1,000", quote=q_s1, note="label says base year"),
            rec("1", "2030", 2030, "900", quote=q_s1), rec("1", "2031", 2031, "800", quote=q_s1),
            rec("1", "2031", 2031, "801", quote=q_s1),  # number not in quote -> verifier fail
            rec("2_location", "2031", 2031, "n/a", quote="x"),  # not a number -> harness parse fail
            rec("2_market", "2031", 2031, None, unit=None, page=None, reason="not stated")]
    with tempfile.TemporaryDirectory() as tmp:
        client = StubClient(recs)
        ctx = make_ctx(tmp, cap=5.0, client=client)
        s = r.run_one(ctx, ENTRY, TEXTS)
        assert client.calls == 1 and s["status"] == "completed", s
        assert (s["pass"], s["fail"], s["not_stated"]) == (3, 2, 1), s
        out = json.loads((Path(tmp) / "outputs" / "made_up_report.json").read_text(encoding="utf-8"))
        assert all(x["year_mapping_unverified"] is True for x in out["records"])
        assert out["records"][0]["mapped_year"] is None and out["records"][1]["value_numeric"] == 900
        ver = json.loads((Path(tmp) / "verification" / "made_up_report.json").read_text(encoding="utf-8"))
        assert ver[3]["failed"] == ["b_number_matches"] and ver[4]["failed"] == ["value_parse"], ver[3:5]
        assert json.loads((Path(tmp) / "raw_responses" / "made_up_report" / "meta.json").read_text())["model_returned"] == "stub-model"
        rows = list(csv.DictReader((Path(tmp) / "cost_ledger.csv").open(encoding="utf-8")))
        assert len(rows) == 1 and "ASSUMPTION" in rows[0]["fx_note"] and "not re-verified" in rows[0]["price_source"]
        assert float(rows[0]["cumulative_eur"]) == float(rows[0]["cost_eur"]) > 0
        print("control call: 1 API call, records verified, flag set, ledger row written -> ok")


def test_label_collisions_do_not_merge_tables():
    """The same printed label "2031" in table A and B on one page and in table C on another page. Only table A has a
    market/location gap above 10x, and only its two records may be flagged. With a label-only key, C would overwrite
    A and B in the verifier's pairing and nothing would be flagged."""
    page2 = ("Table A\nGross location-based Scope 2 (tCO2e)\n2031\n500\nGross market-based Scope 2 (tCO2e)\n2031\n40\n"
             "Table B\nGross location-based Scope 2 (tCO2e)\n2031\n600\nGross market-based Scope 2 (tCO2e)\n2031\n450\n")
    page3 = "Table C\nGross location-based Scope 2 (tCO2e)\n2031\n700\nGross market-based Scope 2 (tCO2e)\n2031\n600\n"

    def r2(scope, page, value, marker):
        q = f"Gross {'location' if scope == '2_location' else 'market'}-based Scope 2 (tCO2e)\n2031\n{value}"
        return rec(scope, "2031", 2031, value, quote=q, page=page)

    recs = [r2("2_location", 2, "500", "A"), r2("2_market", 2, "40", "A"),
            r2("2_location", 2, "600", "B"), r2("2_market", 2, "450", "B"),
            r2("2_location", 3, "700", "C"), r2("2_market", 3, "600", "C")]
    out, results = r.verify_records(ENTRY, recs, {1: "x", 2: page2, 3: page3}, [2, 3])
    flagged = [i for i, x in enumerate(results) if x["flags"]]
    assert flagged == [0, 1], flagged
    assert [x["status"] for x in results] == ["pass"] * 6
    assert len(out) == len(results) == 6  # nothing dropped
    assert all(x["year_label_as_printed"] == "2031" and "year" not in x for x in results)
    print("label collisions: same label in tables A, B (one page) and C (another page) -> only A flagged, 6/6 kept -> ok")


def test_no_pages_found_makes_no_call():
    with tempfile.TemporaryDirectory() as tmp:
        client = StubClient()
        s = r.run_one(make_ctx(tmp, 5.0, client), ENTRY, {1: "nothing", 2: "nothing either"})
        assert s["status"] == "no_pages_found" and client.calls == 0
        print("no_pages_found: no API call, status logged -> ok")


def test_dirty_filter():
    lines = [" M scripts/a.py", "?? data/extraction_eval/run_001/manifest.json", '?? "data/other/x"']
    assert r.dirty_outside_eval(lines) == [lines[0], lines[2]]
    print("git dirty filter: ok")


if __name__ == "__main__":
    test_parse()
    test_cap_refused_no_api_call()
    test_stop_at_80_percent()
    test_control_call_goes_through_and_is_verified()
    test_label_collisions_do_not_merge_tables()
    test_no_pages_found_makes_no_call()
    test_dirty_filter()
    print("all tests passed")
