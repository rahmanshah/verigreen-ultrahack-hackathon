"""Phase A of the scored extraction evaluation: run the frozen extractor + verifier on every report PDF, no scoring.

Runs in the side env C:\\Users\\Shah\\venvs\\verigreen-extract (pymupdf, openai, python-dotenv), not the project env.
Reuses scripts/extraction/{config,page_finder,verifier}.py unchanged. Only the prompt (prompt_v2.txt), the schema
(schema_v2.json) and this runner are new.

    python -X utf8 scripts/extraction_eval/run_phase_a.py --dry-run   # no API call; writes the manifest
    python -X utf8 scripts/extraction_eval/run_phase_a.py --go        # freeze checks, availability call, full run

--go refuses to start unless: every frozen file and PDF matches the manifest sha256, the git tree is clean apart from
data/extraction_eval/, and run_001 has no outputs yet. No retries. A cap breach stops the run. Nothing is scored.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "scripts" / "extraction"))
import config  # noqa: E402  (spike config, unchanged)
import page_finder  # noqa: E402
import verifier  # noqa: E402

RUN_DIR = REPO / "data" / "extraction_eval" / "run_001"
PROMPT_FILE = HERE / "prompt_v2.txt"
SCHEMA_FILE = HERE / "schema_v2.json"
MODEL = config.MODEL
FX_USD_TO_EUR = config.USD_TO_EUR  # 1.00: an ASSUMPTION (conservative), not a market rate
FX_NOTE = "ASSUMPTION: 1 USD = 1 EUR (conservative, no external source)"
PRICE_SOURCE = ("recalled from spike notes (config.py / docs/extraction_spike.md), not re-verified; "
                "openai.com/api/pricing returned HTTP 403 on 2026-10-09")
FROZEN_FILES = [
    "scripts/extraction_eval/prompt_v2.txt", "scripts/extraction_eval/schema_v2.json",
    "scripts/extraction_eval/run_phase_a.py", "scripts/extraction_eval/test_run_phase_a.py",
    "scripts/extraction/config.py", "scripts/extraction/page_finder.py", "scripts/extraction/verifier.py",
]

# (file, company label, report year the file covers, PDF type). Identified from file name, PDF metadata and the first
# pages of text by Claude on 2026-10-09; not verified against the reports by a human.
PDF_TABLE = [
    ("7spez01rONU0ftvjP9pujP-Neste_Annual_Report_2025_Sustainability_Data_Package.pdf", "Neste", 2025, "data package"),
    ("Fortum-Financials2025.pdf", "Fortum", 2025, "financial statements"),
    ("Outokumpu Sustainability review 2023.pdf", "Outokumpu", 2023, "sustainability report"),
    ("Outokumpu_Sustainability_Statement_2025.pdf", "Outokumpu", 2025, "sustainability report"),
    ("STORAENSO_Annual_Report_2023.pdf", "Stora Enso", 2023, "annual report (full)"),
    ("STORAENSO_Annual_Report_2025.pdf", "Stora Enso", 2025, "annual report (full)"),
    ("upm-annual-report-2023.pdf", "UPM", 2023, "annual report (full)"),
    ("upm-annual-report-2024.pdf", "UPM", 2024, "annual report (full)"),
    ("upm_annual_report_2025.pdf", "UPM", 2025, "annual report (full)"),
    ("kemira-full-annual-report-2023.pdf", "Kemira", 2023, "annual report (full)"),
    ("kemira-full-annual-report-2025.pdf", "Kemira", 2025, "annual report (full)"),
    ("wärtsilä-annual-report-2023.pdf", "Wärtsilä", 2023, "annual report (full)"),
    ("wärtsilä-annual-report-2025.pdf", "Wärtsilä", 2025, "annual report (full)"),
    ("metso-annual-report-2023.pdf", "Metso", 2023, "financial statements"),
    ("metso-annual-report-2023-1.pdf", "Metso", 2023, "GRI supplement"),
    ("metso-financial-review-2024.pdf", "Metso", 2024, "financial statements"),
    ("metso-annual-report-2025.pdf", "Metso", 2025, "annual report (full)"),
    ("kesko-annual-report-2023.pdf", "Kesko", 2023, "annual report (full)"),
    ("kesko-annual-report-2025.pdf", "Kesko", 2025, "annual report (full)"),
    ("Sustainability Statement 2025_tcm17-141616.pdf", "KONE", 2025, "sustainability report"),
    ("nokia-annual-report-2023.pdf", "Nokia", 2023, "annual report (full)"),
    ("nokia-annual-report-2025.pdf", "Nokia", 2025, "annual report (full)"),
    ("Elisa_Annual_Report_2023.pdf", "Elisa", 2023, "annual report (full)"),
    ("Elisa_AnnualReport_2025.pdf", "Elisa", 2025, "annual report (full)"),
    ("orion_sustainability_report_2023.pdf", "Orion", 2023, "sustainability report"),
    ("orion-financial-statement-documents-2025.pdf", "Orion", 2025, "financial statements"),
    ("annual-report-nordea-bank-abp-2023.pdf", "Nordea", 2023, "annual report (full)"),
    ("nordea-annual-report-2025.pdf", "Nordea", 2025, "annual report (full)"),
    ("sampo2023_sustainability_report.pdf", "Sampo", 2023, "sustainability report"),
    ("sampo2025-board-report-financial-statements.pdf", "Sampo", 2025, "financial statements"),
]

LEDGER_COLS = ["timestamp_utc", "call_type", "pdf", "pages_sent", "input_tokens", "output_tokens", "reasoning_tokens",
               "price_in_usd_per_m", "price_out_usd_per_m", "cost_usd", "fx_usd_to_eur", "cost_eur", "cumulative_eur",
               "model_returned", "status", "latency_s", "price_source", "fx_note"]


class CapRefused(Exception):
    pass


class StopAtEightyPercent(Exception):
    pass


# ---------------------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------------------
def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def stem_of(fname: str) -> str:
    s = unicodedata.normalize("NFKD", Path(fname).stem).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True).stdout


def git_state() -> dict:
    status = [ln for ln in git("status", "--porcelain=v1", "--untracked-files=all").splitlines() if ln]
    return {"head": git("rev-parse", "HEAD").strip(), "branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
            "status_porcelain": status}


def dirty_outside_eval(status_lines: list[str]) -> list[str]:
    return [ln for ln in status_lines if not ln[3:].strip().strip('"').startswith("data/extraction_eval/")]


def price_per_m() -> tuple[float, float]:
    return config.PRICES_USD[MODEL]


def cost_usd(in_tok: int, out_tok: int) -> float:
    p_in, p_out = price_per_m()
    return (in_tok * p_in + out_tok * p_out) / 1e6


def check_cap(cum_eur: float, worst_eur: float, cap_eur: float, stop_fraction: float = 0.8) -> None:
    """Called before every API call. Raises, so the call is never made."""
    if cum_eur >= stop_fraction * cap_eur:
        raise StopAtEightyPercent(f"cumulative EUR {cum_eur:.4f} reached {stop_fraction:.0%} of the EUR {cap_eur} cap")
    if cum_eur + worst_eur > cap_eur:
        raise CapRefused(f"cumulative EUR {cum_eur:.6f} + worst case EUR {worst_eur:.6f} would exceed the EUR "
                         f"{cap_eur} cap")


def estimate_input_tokens(instructions: str, user: str, schema: dict) -> int:
    chars = len(instructions) + len(user) + len(json.dumps(schema))
    return round(chars / 4 * config.TOKEN_ESTIMATE_MARGIN)  # conservative, same method as the spike


def worst_case_eur(in_tok_est: int, max_out: int) -> float:
    return cost_usd(in_tok_est, max_out) * FX_USD_TO_EUR


def parse_printed_number(s: str | None) -> tuple[Decimal | None, str, str | None]:
    """The harness (not the model) turns value_as_printed into a number.
    Returns (value, rule used, flag). Ambiguous "1,234" / "12.345" is read as thousands separator and flagged."""
    if s is None:
        return None, "none", None
    t = verifier.normalise(s)
    if not re.fullmatch(r"-?\d[\d ,.]*", t) or not t[-1].isdigit():
        return None, "not_a_number", None
    neg = t.startswith("-")
    t = t.lstrip("-")
    has_c, has_d, has_s = "," in t, "." in t, " " in t
    dec, flag = None, None
    if has_c and has_d:
        dec = "," if t.rfind(",") > t.rfind(".") else "."
    elif has_c != has_d:
        x = "," if has_c else "."
        if t.count(x) == 1:
            before, after = t.split(x)
            if has_s:
                dec = x
            elif len(after) == 3 and 1 <= len(before) <= 3:
                flag = "assumed_thousands_separator"
            else:
                dec = x
    int_part, frac = (t, "")
    if dec:
        if t.count(dec) != 1:
            return None, "bad_grouping", None
        int_part, frac = t.split(dec)
        if not frac.isdigit():
            return None, "bad_grouping", None
    seps = set(re.findall(r"[ ,.]", int_part))
    if len(seps) > 1:
        return None, "bad_grouping", None
    if seps:
        parts = re.split(r"[ ,.]", int_part)
        if not (1 <= len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:])):
            return None, "bad_grouping", None
    digits = re.sub(r"[ ,.]", "", int_part)
    if len(digits) > 1 and digits[0] == "0":
        return None, "bad_grouping", None
    try:
        v = Decimal(digits + ("." + frac if frac else ""))
    except InvalidOperation:
        return None, "not_a_number", None
    parts_used = []
    if seps:
        parts_used.append(f"thousands='{next(iter(seps))}'")
    if dec:
        parts_used.append(f"decimal='{dec}'")
    rule = "+".join(parts_used) or "plain"
    return (-v if neg else v), rule, flag


def numeric_json(v: Decimal | None):
    if v is None:
        return None
    return int(v) if v == v.to_integral_value() else float(v)


# ---------------------------------------------------------------------------------------------------------------------
# one PDF
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class Ctx:
    client: object
    run_dir: Path
    cap_eur: float
    prompt: str
    schema: dict
    cum_eur: float = 0.0
    show_errors: bool = False


def ledger_row(ctx: Ctx, call_type: str, pdf: str, pages: list[int], usage: dict | None, model_returned, status: str,
               latency_s: float | None) -> float:
    p_in, p_out = price_per_m()
    u = usage or {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": None}
    usd = cost_usd(u["input_tokens"], u["output_tokens"])
    eur = usd * FX_USD_TO_EUR
    ctx.cum_eur += eur
    path = ctx.run_dir / "cost_ledger.csv"
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LEDGER_COLS)
        w.writerow([now_utc(), call_type, pdf, ";".join(map(str, pages)), u["input_tokens"], u["output_tokens"],
                    u["reasoning_tokens"], p_in, p_out, f"{usd:.6f}", FX_USD_TO_EUR, f"{eur:.6f}",
                    f"{ctx.cum_eur:.6f}", model_returned, status, "" if latency_s is None else f"{latency_s:.2f}",
                    PRICE_SOURCE, FX_NOTE])
    return eur


def usage_of(resp) -> dict:
    u = resp.usage
    return {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
            "reasoning_tokens": getattr(getattr(u, "output_tokens_details", None), "reasoning_tokens", None)}


def build_user(company: str, fname: str, texts: dict[int, str], sent: list[int]) -> str:
    body = "\n\n".join(f"=== PDF page index {n} ===\n{texts[n]}" for n in sent)
    return f"Company: {company}\nReport file: {fname}\n\n{body}"


def build_params(ctx: Ctx, user: str) -> dict:
    return {"model": MODEL, "instructions": ctx.prompt, "input": user, "store": False,
            "max_output_tokens": config.MAX_OUTPUT_TOKENS,
            "text": {"format": {"type": "json_schema", "name": "ghg_records_v2", "schema": ctx.schema, "strict": True}},
            "reasoning": {"effort": config.REASONING_EFFORT}}


def verify_records(entry: tuple, records: list[dict], texts: dict[int, str], sent: list[int]) -> tuple[list, list]:
    """Build harness records (numeric parse, year_mapping_unverified) and run the unchanged verifier on them.
    The verifier needs an int year and pairs 2_location with 2_market by (company, year). Records are therefore keyed by
    (cited page, printed label, occurrence): the k-th record of a scope with the same page and label is paired with the
    k-th record of the other Scope 2 method with the same page and label. Two tables that share a label (on one page or
    on different pages) are never merged, and one never overwrites the other. This relies on the model listing the
    records of one table in table order. The real fields replace the key in the saved results."""
    _, company, report_year, _ = entry
    out, key_idx, seen, vin, vpos = [], {}, Counter(), [], []
    for i, r in enumerate(records):
        num, rule, flag = parse_printed_number(r["value_as_printed"])
        rec = {"record_index": i, "company": company, "report_file": entry[0], "report_fiscal_year": report_year,
               **r, "value_numeric": numeric_json(num), "value_parse_rule": rule,
               "harness_flags": [flag] if flag else [], "year_mapping_unverified": True}
        out.append(rec)
        if r["value_as_printed"] is not None and num is None:
            continue  # parse failure: failed by the harness below, not passed to the verifier
        group = (r["scope"], r["pdf_page"], r["year_label_as_printed"])
        occurrence = seen[group]
        seen[group] += 1
        key = key_idx.setdefault((r["pdf_page"], r["year_label_as_printed"], occurrence), 1_000_000 + len(key_idx))
        vin.append({"company": company, "scope": r["scope"], "year": key, "value": num,
                    "unit_as_printed": r["unit_as_printed"], "pdf_page": r["pdf_page"], "quote": r["quote"],
                    "null_reason": r["null_reason"]})
        vpos.append(i)
    vres = dict(zip(vpos, verifier.verify(vin, texts, sent)))
    results = []
    for i, rec in enumerate(out):
        res = vres.get(i)
        if res is None:
            res = {"company": rec["company"], "scope": rec["scope"], "unit_as_printed": rec["unit_as_printed"],
                   "pdf_page": rec["pdf_page"], "status": "fail", "failed": ["value_parse"], "ambiguous": [],
                   "flags": [], "details": {"value_parse": f"value_as_printed {rec['value_as_printed']!r} could not be "
                                                           f"parsed ({rec['value_parse_rule']})"}}
        res.pop("year", None)
        res.update(record_index=i, year_label_as_printed=rec["year_label_as_printed"],
                   mapped_year=rec["mapped_year"], value=rec["value_numeric"], value_as_printed=rec["value_as_printed"])
        results.append(res)
    return out, results


def summarise(entry: tuple, status: str, finder_pages: list[int], records: list, results: list, cost_eur: float,
              latency_s: float | None) -> dict:
    st = Counter(r["status"] for r in results)
    reasons = Counter(c for r in results for c in r["failed"] + r["ambiguous"])
    return {"pdf": entry[0], "company": entry[1], "report_year": entry[2], "pdf_type": entry[3], "status": status,
            "finder_pages": finder_pages, "records": len(records), "nulls": sum(r["value_as_printed"] is None for r in records),
            "pass": st["pass"], "ambiguous": st["ambiguous"], "fail": st["fail"], "not_stated": st["not_stated"],
            "flagged": sum(bool(r["flags"]) for r in results), "failure_reasons": dict(reasons),
            "cost_eur": round(cost_eur, 6), "latency_s": None if latency_s is None else round(latency_s, 2)}


def run_one(ctx: Ctx, entry: tuple, texts: dict[int, str], sent: list[int] | None = None) -> dict:
    """sent is None in the real run (the page finder chooses); --smoke passes its single made-up page."""
    fname, company, _, _ = entry
    stem = stem_of(fname)
    sent = page_finder.find_pages(texts) if sent is None else sent
    base = {"file": fname, "company": company, "report_fiscal_year": entry[2], "pdf_type": entry[3],
            "finder_pages": sent, "model": MODEL}
    if not sent:  # no API call, nothing substituted
        write_json(ctx.run_dir / "outputs" / f"{stem}.json", {**base, "status": "no_pages_found", "records": []})
        write_json(ctx.run_dir / "verification" / f"{stem}.json", [])
        return summarise(entry, "no_pages_found", sent, [], [], 0.0, None)

    user = build_user(company, fname, texts, sent)
    in_est = estimate_input_tokens(ctx.prompt, user, ctx.schema)
    worst = worst_case_eur(in_est, config.MAX_OUTPUT_TOKENS)
    check_cap(ctx.cum_eur, worst, ctx.cap_eur)  # raises before any API call

    raw_dir = ctx.run_dir / "raw_responses" / stem
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "prompt.txt").write_text(f"[instructions]\n{ctx.prompt}\n[input]\n{user}\n", encoding="utf-8")
    meta = {"pdf": fname, "company": company, "sent_pages": sent, "provider": config.PROVIDER,
            "model_requested": MODEL, "reasoning_effort": config.REASONING_EFFORT, "temperature": None,
            "max_output_tokens": config.MAX_OUTPUT_TOKENS, "input_tokens_est": in_est, "worst_case_eur": worst,
            "started_utc": now_utc()}
    write_json(raw_dir / "meta.json", meta)

    t0 = time.perf_counter()
    try:
        resp = ctx.client.responses.create(**build_params(ctx, user))
    except Exception as e:  # logged failure, no retry; class name only so nothing sensitive reaches the files
        latency = time.perf_counter() - t0
        status = f"failed:api_error:{type(e).__name__}:{getattr(e, 'status_code', None)}"
        if ctx.show_errors:  # smoke only: print the API's message (any key-like token redacted) to diagnose a schema
            print("API error message:", re.sub(r"sk-[A-Za-z0-9_*.-]+", "sk-REDACTED", str(e))[:800])
        ledger_row(ctx, "extraction", fname, sent, None, None, status, latency)
        meta.update(status=status, latency_s=round(latency, 2))
        write_json(raw_dir / "meta.json", meta)
        write_json(ctx.run_dir / "outputs" / f"{stem}.json", {**base, "status": status, "records": []})
        return summarise(entry, status, sent, [], [], 0.0, latency)
    latency = time.perf_counter() - t0

    (raw_dir / "response_raw.json").write_text(resp.model_dump_json(indent=2), encoding="utf-8")
    usage = usage_of(resp)
    eur = ledger_row(ctx, "extraction", fname, sent, usage, resp.model, resp.status, latency)
    meta.update(model_returned=resp.model, response_id=getattr(resp, "id", None), status=resp.status, usage=usage,
                latency_s=round(latency, 2))
    write_json(raw_dir / "meta.json", meta)

    def fail(status: str) -> dict:
        write_json(ctx.run_dir / "outputs" / f"{stem}.json",
                   {**base, "status": status, "model_returned": resp.model, "records": []})
        return summarise(entry, status, sent, [], [], eur, latency)

    if resp.status != "completed":
        return fail(f"failed:{resp.status}:{getattr(resp.incomplete_details, 'reason', None)}")
    try:
        records = json.loads(resp.output_text)["records"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return fail("failed:invalid_json")

    recs, results = verify_records(entry, records, texts, sent)
    write_json(ctx.run_dir / "outputs" / f"{stem}.json",
               {**base, "status": "completed", "model_returned": resp.model, "records": recs})
    write_json(ctx.run_dir / "verification" / f"{stem}.json", results)
    return summarise(entry, "completed", sent, recs, results, eur, latency)


# ---------------------------------------------------------------------------------------------------------------------
# manifest, dry run, go
# ---------------------------------------------------------------------------------------------------------------------
def settings_block() -> dict:
    return {"provider": config.PROVIDER, "base_url": config.BASE_URL, "model": MODEL,
            "reasoning_effort": config.REASONING_EFFORT, "temperature": "not sent", "store": False,
            "max_output_tokens": config.MAX_OUTPUT_TOKENS, "max_retries": 0, "timeout_s": 300,
            "page_cap": config.PAGE_CAP, "token_estimate_margin": config.TOKEN_ESTIMATE_MARGIN,
            "spend_cap_eur": config.SPEND_CAP_EUR, "stop_fraction": 0.8, "fx_usd_to_eur": FX_USD_TO_EUR,
            "fx_note": FX_NOTE, "prices_usd_per_m_in_out": list(price_per_m()), "price_source": PRICE_SOURCE}


def finder_block() -> dict:
    pf = page_finder
    return {"S1": pf.S1.pattern, "S2": pf.S2.pattern, "METHOD": pf.METHOD.pattern, "UNIT": pf.UNIT.pattern,
            "GHG": pf.GHG.pattern, "NUMBER": pf.NUMBER.pattern, "PAGE_CAP": config.PAGE_CAP}


def plan_pdfs(prompt: str, schema: dict) -> list[dict]:
    rows = []
    for fname, company, year, ptype in PDF_TABLE:
        path = config.PDF_DIR / fname
        texts = page_finder.page_texts(path)
        sent = page_finder.find_pages(texts)
        user = build_user(company, fname, texts, sent) if sent else ""
        in_est = estimate_input_tokens(prompt, user, schema) if sent else 0
        rows.append({"file": fname, "stem": stem_of(fname), "sha256": sha256_file(path), "company": company,
                     "report_year": year, "pdf_type": ptype, "pages_in_pdf": len(texts), "finder_pages": sent,
                     "planned": "call" if sent else "no_pages_found", "input_tokens_est": in_est,
                     "worst_case_eur": round(worst_case_eur(in_est, config.MAX_OUTPUT_TOKENS), 6) if sent else 0.0})
    return rows


def dry_run() -> None:
    if (RUN_DIR / "outputs").exists() or (RUN_DIR / "cost_ledger.csv").exists():
        sys.exit("run_001 already has outputs: refusing to rewrite its manifest. Any change becomes run_002.")
    prompt, schema = PROMPT_FILE.read_text(encoding="utf-8"), json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    pdfs = plan_pdfs(prompt, schema)
    gs = git_state()
    manifest = {"created_utc": now_utc(), "mode": "dry_run (no API call)", "git_at_dry_run": gs,
                "settings": settings_block(), "finder": finder_block(),
                "frozen_files_sha256": {p: sha256_file(REPO / p) for p in FROZEN_FILES},
                "pdf_metadata_source": "file name, PDF metadata and first pages of text, identified by Claude; not "
                                       "verified by a human",
                "pdfs": pdfs}
    write_json(RUN_DIR / "manifest.json", manifest)
    print(f"{'file':<82}{'type':<22}{'pages':>6}  finder pages            in_est   worst EUR")
    for p in pdfs:
        print(f"{p['file'][:80]:<82}{p['pdf_type']:<22}{p['pages_in_pdf']:>6}  {str(p['finder_pages']):<22}"
              f"{p['input_tokens_est']:>7}  {p['worst_case_eur']:>9.5f}")
    calls = [p for p in pdfs if p["planned"] == "call"]
    exp = sum(cost_usd(p["input_tokens_est"], 2500) * FX_USD_TO_EUR for p in calls)
    print(f"\n{len(calls)} calls planned, {len(pdfs) - len(calls)} with no pages found (no call)")
    print(f"worst case total EUR {sum(p['worst_case_eur'] for p in calls):.4f} (cap {config.SPEND_CAP_EUR}); "
          f"expected about EUR {exp:.4f} (input est x2 margin, 2,500 output tokens per call)")
    print(f"HEAD {gs['head']} on {gs['branch']}; uncommitted: {gs['status_porcelain'] or 'none'}")
    print(f"manifest written: {RUN_DIR / 'manifest.json'}")


def freeze_checks(manifest: dict) -> dict:
    problems = []
    if manifest["settings"] != settings_block():
        problems.append("settings differ from the manifest")
    if manifest["finder"] != finder_block():
        problems.append("page-finder keywords differ from the manifest")
    for p, h in manifest["frozen_files_sha256"].items():
        if sha256_file(REPO / p) != h:
            problems.append(f"frozen file changed: {p}")
    for p in manifest["pdfs"]:
        if sha256_file(config.PDF_DIR / p["file"]) != p["sha256"]:
            problems.append(f"PDF changed: {p['file']}")
    gs = git_state()
    if dirty := dirty_outside_eval(gs["status_porcelain"]):
        problems.append(f"git tree not clean outside data/extraction_eval/: {dirty}")
    if (RUN_DIR / "outputs").exists() or (RUN_DIR / "cost_ledger.csv").exists():
        problems.append("run_001 already has outputs (no reruns: any change becomes run_002)")
    if problems:
        sys.exit("REFUSING TO START:\n  " + "\n  ".join(problems))
    return gs


def availability_call(ctx: Ctx) -> None:
    worst = worst_case_eur(50, 1000)
    check_cap(ctx.cum_eur, worst, ctx.cap_eur)
    t0 = time.perf_counter()
    try:
        resp = ctx.client.responses.create(model=MODEL, input="Reply with the single word: ok", store=False,
                                           max_output_tokens=1000, reasoning={"effort": config.REASONING_EFFORT})
    except Exception as e:
        ledger_row(ctx, "availability", "(none)", [], None, None, f"api_error:{type(e).__name__}", None)
        sys.exit(f"MODEL UNAVAILABLE ({type(e).__name__}, status {getattr(e, 'status_code', None)}). Stopping; "
                 f"no model switch.")
    ledger_row(ctx, "availability", "(none)", [], usage_of(resp), resp.model, resp.status,
               time.perf_counter() - t0)
    print(f"availability: status {resp.status}, model returned {resp.model}, reply {resp.output_text.strip()[:20]!r}")


def go() -> None:
    manifest = json.loads((RUN_DIR / "manifest.json").read_text(encoding="utf-8"))
    gs = freeze_checks(manifest)
    print(f"freeze checks passed. HEAD {gs['head']} (dry run was at {manifest['git_at_dry_run']['head']})")
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(REPO / ".env")
    if not os.environ.get(config.API_KEY_ENV):
        sys.exit(f"{config.API_KEY_ENV} not set in .env")
    client = OpenAI(base_url=config.BASE_URL, api_key=os.environ[config.API_KEY_ENV], max_retries=0, timeout=300)
    ctx = Ctx(client=client, run_dir=RUN_DIR, cap_eur=config.SPEND_CAP_EUR,
              prompt=PROMPT_FILE.read_text(encoding="utf-8"), schema=json.loads(SCHEMA_FILE.read_text(encoding="utf-8")))
    manifest["run"] = {"started_utc": now_utc(), "git_head_at_run": gs["head"], "git_branch": gs["branch"],
                       "git_status_at_run": gs["status_porcelain"]}
    write_json(RUN_DIR / "manifest.json", manifest)

    availability_call(ctx)
    summaries, stopped = [], None
    for entry in PDF_TABLE:
        try:
            summaries.append(run_one(ctx, entry, page_finder.page_texts(config.PDF_DIR / entry[0])))
        except (CapRefused, StopAtEightyPercent) as e:
            stopped = f"{type(e).__name__} before {entry[0]}: {e}"
            print("STOPPED:", stopped)
            break
        s = summaries[-1]
        print(f"{s['pdf'][:60]:<62}{s['status']:<28} rec {s['records']:>3} pass {s['pass']:>3} fail {s['fail']:>3} "
              f"cum EUR {ctx.cum_eur:.5f}")

    write_json(RUN_DIR / "run_summary.json", {"stopped": stopped, "cumulative_eur": ctx.cum_eur, "pdfs": summaries})
    with (RUN_DIR / "run_summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summaries[0]) if summaries else ["pdf"])
        w.writeheader()
        w.writerows({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in s.items()} for s in summaries)
    manifest["run"].update(finished_utc=now_utc(), stopped=stopped, cumulative_eur=round(ctx.cum_eur, 6),
                           outputs_sha256={str(p.relative_to(RUN_DIR)).replace("\\", "/"): sha256_file(p)
                                           for p in sorted(RUN_DIR.rglob("*")) if p.is_file() and p.name != "manifest.json"})
    write_json(RUN_DIR / "manifest.json", manifest)
    print(f"done. cumulative EUR {ctx.cum_eur:.5f} of {config.SPEND_CAP_EUR}; ledger {RUN_DIR / 'cost_ledger.csv'}")


SMOKE_DIR = REPO / "data" / "extraction_eval" / "smoke"
SMOKE_ENTRY = ("smoke_made_up_report.pdf", "Madeup Co", 2031, "sustainability report")
SMOKE_TEXT = ("Gross Scope 1 (tCO2e)  |  Base year 1999  |  2030  |  2031\n"
              "100  |  90  |  80")  # the made-up illustration in prompt_v2.txt


def smoke() -> None:
    """One real API call on the made-up illustration page, through the same run_one code. Own ledger and outputs in
    SMOKE_DIR, never in run_001. Same cap check as the run."""
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(REPO / ".env")
    if not os.environ.get(config.API_KEY_ENV):
        sys.exit(f"{config.API_KEY_ENV} not set in .env")
    client = OpenAI(base_url=config.BASE_URL, api_key=os.environ[config.API_KEY_ENV], max_retries=0, timeout=300)
    ctx = Ctx(client=client, run_dir=SMOKE_DIR, cap_eur=config.SPEND_CAP_EUR, show_errors=True,
              prompt=PROMPT_FILE.read_text(encoding="utf-8"), schema=json.loads(SCHEMA_FILE.read_text(encoding="utf-8")))
    s = run_one(ctx, SMOKE_ENTRY, {1: SMOKE_TEXT}, sent=[1])
    print(json.dumps(s, indent=2))
    print(f"smoke files in {SMOKE_DIR}")


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="no API call; writes the manifest")
    g.add_argument("--smoke", action="store_true", help="ONE real call on made-up text; writes to extraction_eval/smoke/")
    g.add_argument("--go", action="store_true", help="freeze checks, availability call, then the full run")
    a = ap.parse_args()
    dry_run() if a.dry_run else smoke() if a.smoke else go()


if __name__ == "__main__":
    main()
