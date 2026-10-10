"""Smoke test: every page renders without an exception. Run with the side-environment python (see README.md)."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent / "streamlit_app.py")
PAGES = ["Findings", "Raw vs trusted", "Green frontier", "Quantum tables", "Hardware", "Extraction"]


def test_every_page_renders() -> None:
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    for page in PAGES:
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception, f"{page}: {[e.value for e in at.exception]}"
        assert at.header[0].value == page


def test_required_texts() -> None:
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Quantum tables").run()
    assert at.warning[0].value == "No quantum advantage claimed. At 15 assets classical methods find the exact optimum."
    at.sidebar.radio[0].set_value("Raw vs trusted").run()
    assert at.subheader[0].value == (
        "Only the two definition errors (financed emissions used as own: Nordea, Sampo) could change the portfolio.")
    at.sidebar.radio[0].set_value("Extraction").run()
    assert EXTRACTION_TEXT in [x.value for x in at.info]


HARDWARE_TEXT = (
    "On IQM Garnet and Emerald, 1000 shots of the p=1 circuit put the exact optimum in 30 to 33% of shots, against 35% "
    "in the noiseless simulation. Both distributions differ from the ideal by more than sampling noise. Without "
    "entangling gates, Garnet matched the simulation within noise. We haven't isolated the cause."
)
FORBIDDEN = ["agrees", "validated", "compliant", "audit-grade", "advantage", "accuracy"]
ALLOWED_ADVANTAGE = "no quantum advantage is claimed"
COST_LINE = "6 jobs, 3.50 credits used (charged per job: 0.50 on Garnet, 0.75 on Emerald)"


def _hardware_page() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Hardware").run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _page_text(at: AppTest) -> str:
    """All text the Hardware page shows in the main area (sidebar excluded), tables and the run selector included."""
    parts = [x.value for kind in (at.header, at.subheader, at.markdown, at.caption, at.info, at.warning) for x in kind]
    parts += [str(df.value.to_csv()) for df in at.dataframe]
    parts += [str(o) for sb in at.selectbox for o in sb.options]
    return "\n".join(parts)


def test_hardware_page() -> None:
    at = _hardware_page()
    assert at.header[0].value == "Hardware"
    table = at.dataframe[0].value
    assert len(table) == 6, len(table)
    sim_col = [c for c in table.columns if c.startswith("simulated")]
    assert len(sim_col) == 1
    assert all(float(v) > 0 for v in table[sim_col[0]]), table[sim_col[0]].tolist()
    assert set(table["above noise floor"]) <= {"yes", "no"}
    assert HARDWARE_TEXT in [x.value for x in at.info]
    assert COST_LINE in [x.value for x in at.caption]
    # the run selector works for every run and keeps the page free of exceptions
    for run_no in range(1, 7):
        at.selectbox[0].set_value(run_no).run()
        assert not at.exception, [e.value for e in at.exception]
        assert any(f"Run {run_no}:" in str(o) for o in at.selectbox[0].options)


def test_hardware_page_display() -> None:
    import json

    at = _hardware_page()
    text = _page_text(at)
    assert "Wärtsilä" in text and "Wartsila" not in text
    # all 16 bitstring labels are kept (no skipped labels) and the optimum has the short label
    spec = json.loads(at.get("vega_lite_chart")[0].proto.spec)
    labels = spec["layer"][1]["encoding"]["x"]["sort"]
    assert len(labels) == 16 and "1010 *" in labels and not any("exact optimum" in x for x in labels), labels
    assert spec["layer"][1]["encoding"]["x"]["axis"]["labelOverlap"] is False
    assert "marked 1010 * in the chart" in text
    # table: short headers, nothing dropped, explaining caption present
    table = at.dataframe[0].value
    assert list(table.columns) == ["run", "device", "circuit", "shots", "1010 count", "observed 1010", "simulated 1010",
                                   "TVD", "noise floor (p95)", "above noise floor", "CZ", "depth"], list(table.columns)
    assert ('"observed 1010" and "simulated 1010" are the shares of shots that gave the exact optimum on the hardware '
            "and in the noiseless simulation. The noise floor is the 95th percentile of sampling noise alone.") in text


def test_hardware_page_forbidden_words() -> None:
    text = _page_text(_hardware_page()).lower()
    assert ALLOWED_ADVANTAGE in text
    text = text.replace(ALLOWED_ADVANTAGE, "")
    for word in FORBIDDEN:
        assert word not in text, f"forbidden word {word!r} on the Hardware page"


EXTRACTION_TEXT = (
    "On a first frozen run over 29 reports, which cost about four cents, 57 of 119 comparable value-and-report pairs "
    "matched our hand-verified numbers. We reviewed the 33 pairs that differed or were ambiguous against the report "
    "pages. In 10 pairs a number from the wrong year column passed the checks. This is a count from one run, not an "
    "accuracy rate."
)
EXTRACTION_INTRO = (
    "In the intended workflow, a person reviews the flagged values, not every number. In this run, the review was "
    "our own adjudication."
)
GOLD = Path(__file__).resolve().parent.parent / "data" / "gold"
EXTRACTION_FORBIDDEN = ["accuracy", "validated", "compliant", "audit-grade", "agrees", "advantage", "savings"]


def _extraction_page() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Extraction").run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _extraction_text(at: AppTest) -> str:
    """All text the Extraction page shows in the main area (sidebar excluded), tables and metrics included."""
    parts = [x.value for kind in (at.header, at.subheader, at.markdown, at.caption, at.info, at.warning) for x in kind]
    parts += [f"{m.label} {m.value}" for m in at.metric]
    parts += [str(df.value.to_csv()) for df in at.dataframe]
    return "\n".join(parts)


def _gold_counts():
    import pandas as pd

    counts = pd.read_csv(GOLD / "extraction_run001_counts.csv")

    def get(section: str, label: str) -> tuple[float, float]:
        r = counts[(counts["section"] == section) & (counts["label"] == label)]
        assert len(r) == 1, (section, label)
        return float(r.iloc[0]["count"]), r.iloc[0]["denominator"]

    return get


def test_extraction_page_table_and_box() -> None:
    import pandas as pd

    at = _extraction_page()
    assert at.header[0].value == "Extraction"
    gold = pd.read_csv(GOLD / "extraction_run001_pdfs.csv")
    table = at.dataframe[0].value
    assert len(table) == 30 == len(gold), len(table)
    spike = table[table["note"] == "spike, not blind"]
    assert len(spike) == int(gold["spike_not_blind"].sum()) == 3, len(spike)
    assert sorted(zip(spike["company"], spike["year"])) == [("Elisa", 2025), ("Orion", 2025), ("Outokumpu", 2025)]
    assert (table["note"] == "no pages found").sum() == (gold["status"] != "completed").sum() == 1
    assert int(table["records"].sum()) == int(gold["records"].sum()) == 451
    assert EXTRACTION_TEXT in [x.value for x in at.info]
    intro = [x.value for x in at.markdown if x.value.startswith("An LLM reads the report pages")]
    assert len(intro) == 1 and EXTRACTION_INTRO in intro[0], intro
    assert "A person reviews the flagged values, not every number." not in intro[0]
    # the note column has an explicit width wide enough for "spike, not blind" (16 characters, about 8 px each at 100% zoom)
    import json

    config = json.loads(at.dataframe[0].proto.columns)
    assert config["note"]["width"] >= 130, config["note"]


def test_extraction_page_counts_equal_gold() -> None:
    at = _extraction_page()
    text = _extraction_text(at)
    get = _gold_counts()
    for section, label in [("scoring_pairs", c) for c in (
            "verified_match", "ambiguous_extracted", "ambiguous_verified", "verified_mismatch", "unit_ambiguous",
            "not_extracted", "extracted_failed_verifier")] + [("spike_pairs", "verified_match"),
                                                             ("adjudication", "token_year_column_wrong"),
                                                             ("scorer_labels", "vintage_difference_right"),
                                                             ("scorer_labels", "year_mapping_suspect_real_error")]:
        n, d = get(section, label)
        assert f"{int(n)} of {int(d)}" in text, (section, label, n, d)
    run = {k: int(get("run", k)[0]) for k in ("calls_total", "extraction_calls", "records", "values", "verifier_pass",
                                              "verifier_fail", "input_tokens", "output_tokens")}
    assert (run["calls_total"], run["extraction_calls"], run["records"], run["verifier_pass"], run["verifier_fail"]) == (
        30, 29, 451, 325, 49)
    metrics = {m.label: m.value for m in at.metric}
    assert str(run["calls_total"]) == str(metrics["Calls"])
    assert metrics["Cost (EUR)"] == f"{get('run', 'cost_eur')[0]:.4f}" == "0.0433"
    assert metrics["Tokens in / out"] == f"{run['input_tokens']:,} / {run['output_tokens']:,}"
    assert f"Of {run['values']} valued records, {run['verifier_pass']} pass and {run['verifier_fail']} fail" in text
    for label, text_part in [("value_parse", "value_parse"), ("quote_page", "quote/page"), ("number_matches", "number_matches")]:
        assert f"{text_part} {int(get('verifier_failures', label)[0])}" in text, label
    # the numbers inside the verbatim box equal the counts file
    assert get("scoring_pairs", "verified_match")[0] == 57 and get("scoring_pairs", "total")[0] == 119
    assert get("adjudication", "pairs_reviewed")[0] == 33 and get("adjudication", "year_column_wrong_pairs")[0] == 10
    assert get("run", "extraction_calls")[0] == 29
    assert "29 of the 119 were not scorable" in text and "A count, not a rate: pairs overlap on keys" in text
    # failure patterns: the numbers in the text come from the counts file
    assert get("adjudication", "boundary_or_method_in_ambiguous_extracted")[0] == 4
    assert get("adjudication", "boundary_or_method_in_verified_mismatch")[0] == 2
    assert get("adjudication", "pattern_wrong_entity")[0] == 1
    assert "Wrong-year column: 10 pairs. In 8 of them" in text
    assert "Extra row from a table with a different boundary: 4 pairs" in text
    assert "Boundary or method differences among the mismatches: 2 pairs, of which 1 is a wrong entity" in text


def test_extraction_page_forbidden_words() -> None:
    text = _extraction_text(_extraction_page()).lower()
    assert "not an accuracy rate" in text
    text = text.replace("not an accuracy rate", "")
    for word in EXTRACTION_FORBIDDEN:
        assert word not in text, f"forbidden word {word!r} on the Extraction page"
    assert "%" not in text, "percent sign on the Extraction page"


if __name__ == "__main__":
    test_every_page_renders()
    test_required_texts()
    test_hardware_page()
    test_hardware_page_display()
    test_hardware_page_forbidden_words()
    test_extraction_page_table_and_box()
    test_extraction_page_counts_equal_gold()
    test_extraction_page_forbidden_words()
    print("ok")
