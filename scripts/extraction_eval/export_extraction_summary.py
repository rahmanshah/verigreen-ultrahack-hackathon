# Environment: PROJECT env (.venv) or any Python 3.12; standard library only. No network, no API call, no key read.
# What it does: reads the frozen run_001 results and the scoring/adjudication files (read-only) and writes two derived
#   files of COUNTS AND RUN FACTS ONLY for the Streamlit Extraction page:
#     data/gold/extraction_run001_pdfs.csv    one row per PDF of the run (30)
#     data/gold/extraction_run001_counts.csv  long format: section, label, count, denominator, note
#   No verified values, extracted values, quotes, reviewer notes or page images are copied. The reviewer notes are only
#   searched for two fixed keywords; only counts and pair ids are printed, never note text.
#   Before writing, it checks the numbers against the expected cross-check (EXPECTED below) and the two keyword counts;
#   on any difference it prints STOP and writes nothing. Deterministic: same input gives byte-identical files.
# Run (from the repo root, no bytecode written):
#   $env:PYTHONDONTWRITEBYTECODE='1'
#   .venv\Scripts\python.exe scripts\extraction_eval\export_extraction_summary.py
# Date: 2026-10-09
"""Export run_001 counts and run facts to data/gold for the app (counts only)."""
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUN = REPO / "data" / "extraction_eval" / "run_001"
SCORING = REPO / "data" / "extraction_eval" / "run_001_scoring"
OUT_PDFS = REPO / "data" / "gold" / "extraction_run001_pdfs.csv"
OUT_COUNTS = REPO / "data" / "gold" / "extraction_run001_counts.csv"

# Fixed before the results were seen (user decision, 2026-10-09). Never change them after looking at the output.
# Only one keyword is used; the other pattern on the page comes from a verdict token, not from the notes.
KEYWORDS = {"pattern_wrong_entity": "parent"}
EXPECTED_KEYWORD_PAIRS = {"pattern_wrong_entity": ["P08"]}

# Expected cross-check: (section, label) -> (count, denominator or None). Compared before anything is written.
EXPECTED = {
    ("run", "extraction_calls"): (29, None), ("run", "availability_calls"): (1, None),
    ("run", "records"): (451, None), ("run", "nulls"): (77, None), ("run", "values"): (374, None),
    ("run", "verifier_pass"): (325, 374), ("run", "verifier_fail"): (49, 374),
    ("verifier_failures", "value_parse"): (19, 49), ("verifier_failures", "quote_page"): (30, 49),
    ("verifier_failures", "number_matches"): (1, 49),
    ("scoring_pairs", "verified_match"): (57, 119), ("scoring_pairs", "verified_match_exact"): (56, 57),
    ("scoring_pairs", "verified_match_near"): (1, 57), ("scoring_pairs", "ambiguous_extracted"): (15, 119),
    ("scoring_pairs", "ambiguous_verified"): (7, 119), ("scoring_pairs", "verified_mismatch"): (11, 119),
    ("scoring_pairs", "unit_ambiguous"): (14, 119), ("scoring_pairs", "not_extracted"): (9, 119),
    ("scoring_pairs", "extracted_failed_verifier"): (6, 119), ("scoring_pairs", "not_scorable_total"): (29, 119),
    ("keys", "no_source_pdf"): (9, 131), ("keys", "spike_only"): (18, 131), ("keys", "has_main_pair"): (104, 131),
    ("spike_pairs", "verified_match"): (15, 18), ("spike_pairs", "ambiguous_extracted"): (3, 18),
    ("adjudication", "pairs_reviewed"): (33, None),
    ("adjudication", "token_vintage_or_restatement"): (7, 33), ("adjudication", "token_boundary_or_method"): (6, 33),
    ("adjudication", "token_year_column_wrong"): (10, 33), ("adjudication", "token_extraction_correct"): (22, 33),
    ("adjudication", "year_column_wrong_more_than_one_candidate"): (8, 10),
    ("adjudication", "year_column_wrong_one_candidate"): (2, 10),
    ("adjudication", "boundary_or_method_in_verified_mismatch"): (2, 11),
    ("adjudication", "boundary_or_method_in_ambiguous_extracted"): (4, 15),
    ("adjudication", "pattern_wrong_entity"): (1, 33),
    ("scorer_labels", "vintage_difference_right"): (3, 4), ("scorer_labels", "year_mapping_suspect_real_error"): (1, 3),
}
EXPECTED_COST_4DP = "0.0433"


def stop(msg: str) -> None:
    sys.exit(f"STOP: {msg}")


def read_csv(path: Path, encoding: str = "utf-8") -> list[dict]:
    with open(path, newline="", encoding=encoding) as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def failing_checks(reasons: dict) -> str:
    """'value_parse 5; quote/page 9; number 1'. quote/page is a_quote_on_page, which always equals c_page_index."""
    if reasons.get("a_quote_on_page", 0) != reasons.get("c_page_index", 0):
        stop(f"a_quote_on_page and c_page_index differ: {reasons}")
    parts = []
    if reasons.get("value_parse"):
        parts.append(f"value_parse {reasons['value_parse']}")
    if reasons.get("a_quote_on_page"):
        parts.append(f"quote/page {reasons['a_quote_on_page']}")
    if reasons.get("b_number_matches"):
        parts.append(f"number {reasons['b_number_matches']}")
    unknown = set(reasons) - {"value_parse", "a_quote_on_page", "c_page_index", "b_number_matches"}
    if unknown:
        stop(f"unknown failure reasons {unknown}")
    return "; ".join(parts)


def summary_lookup(rows: list[dict]):
    """Aggregate ('all') rows of the scoring summary: (section, category, detail) -> (count, denominator)."""
    out = {}
    for r in rows:
        if r["group_type"] == "all":
            key = (r["section"], r["category"], r["detail"])
            if key in out:
                stop(f"duplicate summary row {key}")
            out[key] = (int(r["count"]), int(r["denominator"]))
    return out


def main() -> None:
    run_rows = read_csv(RUN / "run_summary.csv")
    run_json = json.loads((RUN / "run_summary.json").read_text(encoding="utf-8"))
    ledger = read_csv(RUN / "cost_ledger.csv")
    by_key = read_csv(SCORING / "results_by_key.csv")
    summary = summary_lookup(read_csv(SCORING / "summary.csv"))
    verdicts = read_csv(SCORING / "adjudication_verdicts.csv", encoding="utf-8-sig")

    # ---- per-PDF file
    spike_files = {r["report_file"] for r in by_key if r["group"] == "spike"}
    run_files = {r["pdf"] for r in run_rows}
    if not spike_files <= run_files:
        stop(f"spike report files not in the run: {sorted(spike_files - run_files)}")
    ledger_pages = {r["pdf"]: len(r["pages_sent"].split(";")) for r in ledger if r["call_type"] == "extraction"}
    pdf_out = []
    for r in run_rows:
        pages = json.loads(r["finder_pages"])
        if r["pdf"] in ledger_pages and ledger_pages[r["pdf"]] != len(pages):
            stop(f"pages sent differ between run_summary and cost_ledger for {r['pdf']}")
        reasons = json.loads(r["failure_reasons"] or "{}")
        pdf_out.append([
            r["company"], int(r["report_year"]), r["pdf_type"], r["pdf"], str(r["pdf"] in spike_files).lower(),
            r["status"], len(pages), int(r["records"]), int(r["nulls"]), int(r["pass"]), int(r["fail"]),
            failing_checks(reasons), r["cost_eur"], r["latency_s"],
        ])
    if len(pdf_out) != 30:
        stop(f"expected 30 PDFs, got {len(pdf_out)}")

    # ---- run section
    ledger_types = Counter(r["call_type"] for r in ledger)
    models = Counter(r["model_returned"] for r in ledger)
    if len(models) != 1:
        stop(f"more than one model identifier returned: {dict(models)}")
    model, model_calls = models.most_common(1)[0]
    reason_total = Counter()
    for r in run_rows:
        reason_total.update(json.loads(r["failure_reasons"] or "{}"))
    records = sum(int(r["records"]) for r in run_rows)
    nulls = sum(int(r["nulls"]) for r in run_rows)
    n_pass = sum(int(r["pass"]) for r in run_rows)
    n_fail = sum(int(r["fail"]) for r in run_rows)
    if sum(int(r["ambiguous"]) for r in run_rows):
        stop("run_summary has ambiguous verifier results; the page text assumes none")
    if n_pass + n_fail != records - nulls:
        stop("pass + fail does not equal the valued records")
    if reason_total["value_parse"] + reason_total["a_quote_on_page"] != n_fail:
        stop("value_parse + quote/page failures do not add up to the failing records")
    no_pages = sum(1 for r in run_rows if r["status"] == "no_pages_found")

    counts: list[list] = []

    def add(section, label, count, denominator="", note=""):
        counts.append([section, label, count, denominator, note])

    add("run", "calls_total", len(ledger), "", "rows of cost_ledger.csv: extraction calls plus the availability call")
    add("run", "extraction_calls", ledger_types["extraction"])
    add("run", "availability_calls", ledger_types["availability"])
    add("run", "pdfs_in_run", len(run_rows))
    add("run", "pdfs_no_pages_found", no_pages, len(run_rows), "no call and no cost for these")
    add("run", "records", records)
    add("run", "nulls", nulls)
    add("run", "values", records - nulls, "", "records minus nulls")
    add("run", "verifier_pass", n_pass, records - nulls)
    add("run", "verifier_fail", n_fail, records - nulls)
    add("run", "cost_eur", repr(float(run_json["cumulative_eur"])), "",
        "EUR, run_summary.json cumulative_eur; prices recalled from earlier notes, not re-verified; 1 USD = 1 EUR assumed")
    add("run", "input_tokens", sum(int(float(r["input_tokens"])) for r in ledger))
    add("run", "output_tokens", sum(int(float(r["output_tokens"])) for r in ledger))
    add("run", "reasoning_tokens", sum(int(float(r["reasoning_tokens"])) for r in ledger), "",
        "as reported in the ledger")
    add("run", "model_returned", model_calls, len(ledger), model)

    # ---- verifier failures
    qp = reason_total["a_quote_on_page"]
    add("verifier_failures", "value_parse", reason_total["value_parse"], n_fail)
    add("verifier_failures", "quote_page", qp, n_fail,
        "all quote/page failures are on the same records as the a_quote_on_page and c_page_index checks")
    add("verifier_failures", "a_quote_on_page", qp, n_fail)
    add("verifier_failures", "c_page_index", reason_total["c_page_index"], n_fail)
    add("verifier_failures", "number_matches", reason_total["b_number_matches"], n_fail,
        "1 of the 49 failing records also failed the number check")

    # ---- scoring pairs (main, spike excluded)
    def pairs(section, cat, detail=""):
        return summary[(section, cat, detail)]

    main_cats = ["verified_match", "ambiguous_extracted", "ambiguous_verified", "verified_mismatch", "unit_ambiguous",
                 "not_extracted", "extracted_failed_verifier"]
    total = pairs("main_pairs", main_cats[0])[1]
    for cat in main_cats:
        c, d = pairs("main_pairs", cat)
        add("scoring_pairs", cat, c, d)
        if cat == "verified_match":
            for tier in ("exact", "near"):
                add("scoring_pairs", f"verified_match_{tier}", *pairs("main_pair_detail", cat, f"tier={tier}"))
        if cat == "unit_ambiguous":
            for reason, label in (("tons", "unit_ambiguous_tons"), ("as_indicated", "unit_ambiguous_as_indicated")):
                add("scoring_pairs", label, *pairs("main_pair_detail", cat, f"reason={reason}"))
    if sum(pairs("main_pairs", c)[0] for c in main_cats) != total:
        stop("main pair categories do not add up to the total")
    add("scoring_pairs", "total", total, total)
    not_scorable = sum(pairs("main_pairs", c)[0] for c in ("unit_ambiguous", "not_extracted", "extracted_failed_verifier"))
    add("scoring_pairs", "not_scorable_total", not_scorable, total, "unit_ambiguous + not_extracted + extracted_failed_verifier")
    add("scoring_pairs", "matches_also_equal_other_year", *pairs("main_pair_detail", "verified_match", "also_matches_other_year"))

    for cat in ("no_source_pdf", "spike_only", "has_main_pair"):
        add("keys", cat, *pairs("key_states", cat))
    for cat in main_cats:
        add("spike_pairs", cat, *pairs("spike_pairs", cat))

    # ---- adjudication (pair level; one pair = one verified value and its candidate rows)
    pair_rows = defaultdict(list)
    for r in verdicts:
        pair_rows[r["pair_id"]].append(r)
    reviewed = {}
    for pid, rows in pair_rows.items():
        strings = {r["human_verdict"].strip() for r in rows}
        cats = {r["category"] for r in rows}
        if len(strings) != 1 or len(cats) != 1:
            stop(f"pair {pid} has differing verdicts or categories across its rows")
        if "" in strings:
            continue  # not adjudicated (spike pairs, not blind)
        reviewed[pid] = {"verdict": strings.pop(), "category": cats.pop(), "rows": len(rows),
                         "labels": {x for r in rows for x in r["labels"].split(";") if x},
                         "spike": {r["spike_not_blind"] for r in rows}}
    if any("True" in v["spike"] for v in reviewed.values()):
        stop("a spike pair carries a verdict")
    n_rev = len(reviewed)
    n_spike_pairs = len(pair_rows) - n_rev
    add("adjudication", "pairs_reviewed", n_rev, "",
        "pairs that differed or were ambiguous; one person, suggested verdicts in front of them: a first review, not independent")
    add("adjudication", "matches_not_reviewed", pairs("main_pairs", "verified_match")[0], total,
        "compared by number, not reviewed by a person")
    add("adjudication", "spike_pairs_not_adjudicated", n_spike_pairs, "", "spike, not blind")
    for cat in ("verified_mismatch", "ambiguous_verified", "ambiguous_extracted"):
        add("adjudication", f"category_{cat}", sum(1 for v in reviewed.values() if v["category"] == cat), n_rev)
    for verdict, n in sorted(Counter(v["verdict"] for v in reviewed.values()).items()):
        add("adjudication", f"verdict_{verdict}", n, n_rev, "exact verdict string as recorded")
    tokens = ("vintage_or_restatement", "boundary_or_method", "year_column_wrong", "extraction_correct")
    has = lambda v, t: t in v["verdict"].split("+")  # noqa: E731
    for t in tokens:
        add("adjudication", f"token_{t}", sum(1 for v in reviewed.values() if has(v, t)), n_rev,
            "combined verdicts count once under each token, so tokens add to more than the pairs reviewed")
    stray = {x for v in reviewed.values() for x in v["verdict"].split("+")} - set(tokens)
    if stray:
        stop(f"verdict tokens outside the four main ones: {stray}")
    ycw = [v for v in reviewed.values() if has(v, "year_column_wrong")]
    add("adjudication", "year_column_wrong_pairs", len(ycw), n_rev)
    add("adjudication", "year_column_wrong_more_than_one_candidate", sum(1 for v in ycw if v["rows"] > 1), len(ycw),
        "the correct number was also extracted")
    add("adjudication", "year_column_wrong_one_candidate", sum(1 for v in ycw if v["rows"] == 1), len(ycw),
        "only one candidate row; nothing signalled it")
    add("adjudication", "boundary_or_method_in_verified_mismatch",
        sum(1 for v in reviewed.values() if has(v, "boundary_or_method") and v["category"] == "verified_mismatch"),
        pairs("main_pairs", "verified_mismatch")[0])
    extra_row = [pid for pid, v in reviewed.items() if has(v, "boundary_or_method") and v["category"] == "ambiguous_extracted"]
    add("adjudication", "boundary_or_method_in_ambiguous_extracted", len(extra_row),
        pairs("main_pairs", "ambiguous_extracted")[0],
        "extra row from a table with a different boundary; from the verdict token")
    # The page says these pairs are all one company (Sampo): stop if the verdict file says otherwise.
    extra_companies = {r["company"] for pid in extra_row for r in pair_rows[pid]}
    if len(extra_companies) != 1 or not next(iter(extra_companies)).startswith("Sampo"):
        stop(f"the boundary_or_method ambiguous_extracted pairs are not all Sampo: {sorted(extra_companies)}")

    # ---- keyword patterns in reviewer notes (fixed keywords; only counts and pair ids are printed)
    hits = {}
    for label, word in KEYWORDS.items():
        ids = sorted({pid for pid, rows in pair_rows.items() if pid in reviewed
                      and any(word in (r["human_notes"] or "").lower() for r in rows)}, key=lambda p: int(p[1:]))
        hits[label] = ids
        add("adjudication", label, len(ids), n_rev, "counted by keyword in reviewer notes")
    print("keyword pair ids:", hits)
    for pid in hits["pattern_wrong_entity"]:  # the page says the wrong-entity pair is one of the boundary/method mismatches
        if not (has(reviewed[pid], "boundary_or_method") and reviewed[pid]["category"] == "verified_mismatch"):
            stop(f"{pid} is not a boundary_or_method verified_mismatch pair")
    for label, want in EXPECTED_KEYWORD_PAIRS.items():
        if hits[label] != want:
            stop(f"keyword pairs for {label}: expected {want}, got {hits[label]}. Keywords not adjusted.")

    # ---- scorer labels next to the reviewer verdict (pair counts, no rate)
    vint = [v for v in reviewed.values() if "vintage_difference" in v["labels"]]
    ysm = [v for v in reviewed.values() if "year_mapping_suspect" in v["labels"]]
    add("scorer_labels", "vintage_difference_right", sum(1 for v in vint if has(v, "vintage_or_restatement")), len(vint),
        "pairs the scorer labelled vintage_difference whose reviewer verdict contains vintage_or_restatement")
    add("scorer_labels", "year_mapping_suspect_real_error", sum(1 for v in ysm if has(v, "year_column_wrong")), len(ysm),
        "pairs the scorer labelled year_mapping_suspect; real error = reviewer verdict contains year_column_wrong")

    # ---- cross-check before writing
    got = {(s, l): (int(c), None if d == "" else int(d)) for s, l, c, d, _ in counts if s != "run" or l != "cost_eur"}
    bad = [(k, want, got.get(k)) for k, want in EXPECTED.items() if got.get(k) != want]
    if bad:
        stop("cross-check differs, nothing written: " + "; ".join(f"{k}: expected {w}, got {g}" for k, w, g in bad))
    if f"{float(run_json['cumulative_eur']):.4f}" != EXPECTED_COST_4DP:
        stop(f"cost EUR {run_json['cumulative_eur']} does not round to {EXPECTED_COST_4DP}")
    if spike_files != {"Outokumpu_Sustainability_Statement_2025.pdf", "orion-financial-statement-documents-2025.pdf",
                       "Elisa_AnnualReport_2025.pdf"}:
        stop(f"unexpected spike reports {sorted(spike_files)}")

    write_csv(OUT_PDFS, [
        "company", "report_year", "pdf_type", "report_file", "spike_not_blind", "status", "pages_sent", "records", "nulls",
        "verifier_pass", "verifier_fail", "failing_checks", "cost_eur", "latency_s",
    ], pdf_out)
    write_csv(OUT_COUNTS, ["section", "label", "count", "denominator", "note"], counts)
    print(f"cross-check passed. wrote {OUT_PDFS.relative_to(REPO)} ({len(pdf_out)} rows) and "
          f"{OUT_COUNTS.relative_to(REPO)} ({len(counts)} rows)")


if __name__ == "__main__":
    main()
