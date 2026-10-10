"""Phase B: score the frozen run_001 extraction against the verified emissions rows. No API call.

Rules: data/extraction_eval/run_001_scoring/scoring_rules.md (hashed in scoring_manifest.json before any verified row
was read). Counts with denominators only; no accuracy figure.

    <side env python> -X utf8 scripts/extraction_eval/score_phase_b.py --write-manifest   # hash rules + scorer (once)
    <side env python> -X utf8 scripts/extraction_eval/score_phase_b.py --structure        # structure only, no values
    <side env python> -X utf8 scripts/extraction_eval/score_phase_b.py --run              # score ONCE (guarded)
"""
import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "extraction"))
import verifier  # noqa: E402  (frozen; only normalise and unit_factor are used)

RUN_DIR = ROOT / "data" / "extraction_eval" / "run_001"
OUT_DIR = ROOT / "data" / "extraction_eval" / "run_001_scoring"
VERIFIED_CSV = ROOT / "data" / "bronze" / "emissions_raw.csv"
RULES_MD = OUT_DIR / "scoring_rules.md"
MANIFEST = OUT_DIR / "scoring_manifest.json"
HERE = Path(__file__).resolve()

YEARS = (2023, 2024, 2025)
SCOPES = ("1", "2_location", "2_market")
SCOPE_COL = {"1": "scope1", "2_location": "scope2_location", "2_market": "scope2_market"}
VERIFIED_COLUMNS = ["company_id", "company_name", "fiscal_year", "scope1", "scope2_location", "scope2_market", "unit",
                    "boundary", "source_type", "source_url", "source_page", "retrieved_date", "notes"]
SPIKE_FILES = {"Outokumpu_Sustainability_Statement_2025.pdf", "orion-financial-statement-documents-2025.pdf",
               "Elisa_AnnualReport_2025.pdf"}
PLACEHOLDERS = {"-", "n/a"}
PRIMARY_TYPES = {"primary", "primary_report", "company_report", "verified_pdf", "annual_report", "sustainability_report"}
THIRD_PARTY_TYPES = {"third_party"}
DERIVED_TYPES = {"from_notes", "derived"}
DERIVED_NOTE_TOKENS = ("from_notes", "derived", "calculated", "computed")  # literal, case-insensitive, never widened
EXACT, NEAR = Decimal("1e-6"), Decimal("0.01")
CATEGORIES = ["not_extracted", "extracted_failed_verifier", "unit_ambiguous", "verified_match", "ambiguous_extracted",
              "ambiguous_verified", "verified_mismatch"]
BUCKETS = ["unmapped", "year_outside_2023_2025", "no_verified_key", "outside_r2_window", "in_pair_scope"]
VERDICTS = ["extraction_wrong", "our_verified_value_wrong", "vintage_or_restatement", "boundary_or_method",
            "year_column_wrong", "unclear"]


# ---------------------------------------------------------------------------------------------------------------------
# numbers, units, tiers
# ---------------------------------------------------------------------------------------------------------------------
def classify_unit(unit):
    """(kind, reason, factor): kind ok | tons | ambiguous. Conversion is the frozen verifier.unit_factor."""
    if unit is None or not str(unit).strip():
        return "ambiguous", "missing_unit", None
    low = verifier.normalise(str(unit)).lower()
    if "or as indicated" in low:
        return "ambiguous", "as_indicated", None
    if re.search(r"(?<![a-z])m t(?![a-z])", low):
        return "ambiguous", "m_t", None
    f = verifier.unit_factor(str(unit))
    if f is None:
        return "ambiguous", "unrecognised", None
    if re.search(r"\btons?\b", low) and "metric" not in low:
        return "tons", "tons", f
    return "ok", "", f


def fmt(d):
    """Plain-notation decimal (Decimal.normalize alone prints 1000 as 1E+3)."""
    return format(d.normalize(), "f")


def rel_diff(e, v):
    if v == 0:
        return Decimal(0) if e == 0 else Decimal("Infinity")
    return abs(e - v) / abs(v)


def tier_of(d):
    return "exact" if d <= EXACT else "near" if d <= NEAR else "other"


def agree(a, b):
    m = max(abs(a), abs(b))
    return m == 0 or abs(a - b) / m <= EXACT


def parse_verified_number(s):
    """Plain or comma-thousands decimal; anything else is None (counted, never guessed)."""
    t = (s or "").strip().replace(" ", "")
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", t):
        t = t.replace(",", "")
    if not re.fullmatch(r"-?\d+(\.\d+)?", t):
        return None
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def is_null(rec):
    v = rec.get("value_as_printed")
    return v is None or not str(v).strip()


def is_placeholder(rec):
    return not is_null(rec) and verifier.normalise(rec["value_as_printed"]).lower() in PLACEHOLDERS


def has_value(rec):
    return not is_null(rec) and not is_placeholder(rec)


def canon(s):
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if not unicodedata.combining(c)).lower())


# ---------------------------------------------------------------------------------------------------------------------
# verified file
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class Cell:
    cid: str
    year: int
    scope: str
    cls: str  # primary | third_party | derived | unclassified
    source_type: str
    unit: str
    kind: str
    reason: str
    tonnes: Decimal | None
    source_url: str
    source_page: str
    notes: str
    row_no: int


def classify_source_type(st):
    s = (st or "").strip().lower()
    return ("primary" if s in PRIMARY_TYPES else "third_party" if s in THIRD_PARTY_TYPES
            else "derived" if s in DERIVED_TYPES else "unclassified")


def classify_cell(source_type, notes):
    """third_party stays third_party; else a row whose notes contain a derived token is derived (notes are never printed)."""
    cls = classify_source_type(source_type)
    if cls != "third_party" and any(tok in (notes or "").lower() for tok in DERIVED_NOTE_TOKENS):
        return "derived"
    return cls


def read_verified(path=VERIFIED_CSV):
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != VERIFIED_COLUMNS:
            raise SystemExit(f"verified file columns differ from the rule set: {reader.fieldnames}")
        return list(reader)


def build_verified(rows):
    """Rows -> (cells by key, stats). Blank cells are no key. Unparseable cells are counted, not guessed."""
    cells, stats = defaultdict(list), Counter()
    for i, r in enumerate(rows):
        try:
            year = int(str(r["fiscal_year"]).strip())
        except ValueError:
            stats["rows_year_unparseable"] += 1
            continue
        if year not in range(1990, 2100):
            stats["rows_year_unparseable"] += 1
            continue
        kind, reason, factor = classify_unit(r["unit"])
        note_hit = classify_cell(r["source_type"], r["notes"]) == "derived" and classify_source_type(r["source_type"]) != "derived"
        if note_hit and year in YEARS:
            stats["rows_derived_by_notes_2023_2025"] += 1
        for scope, col in SCOPE_COL.items():
            raw = (r[col] or "").strip()
            if not raw:
                continue
            if note_hit and year in YEARS:
                stats[f"cells_derived_by_notes_{scope}"] += 1
            val = parse_verified_number(raw)
            if val is None:
                stats["cells_unparseable"] += 1
                continue
            tonnes = val * factor if kind == "ok" else None
            cells[(r["company_id"], year, scope)].append(
                Cell(r["company_id"], year, scope, classify_cell(r["source_type"], r["notes"]), r["source_type"], r["unit"],
                     kind, reason, tonnes, r["source_url"], r["source_page"], r["notes"], i))
    return cells, stats


def build_company_map(ext_companies, rows):
    """Extraction company name -> verified company_id, by normalised prefix on company_name / company_id."""
    names = defaultdict(set)
    for r in rows:
        names[r["company_id"]].update({canon(r["company_id"]), canon(r["company_name"])} - {""})
    out, unresolved = {}, []
    for ext in sorted(set(ext_companies)):
        c = canon(ext)
        hits = [cid for cid, ns in names.items() if any(n.startswith(c) or c.startswith(n) for n in ns)]
        if len(hits) == 1:
            out[ext] = hits[0]
        else:
            unresolved.append((ext, hits))
    return out, unresolved


def key_truth(cells):
    """Ground truth of one key from its cells: state + distinct primary values (tonnes)."""
    prim = [c for c in cells if c.cls == "primary"]
    if not prim:
        return {"state": "derived_not_extractable" if any(c.cls == "derived" for c in cells) else "third_party_only",
                "vals": [], "unit_problem": False, "prim": [], "n_third": sum(c.cls == "third_party" for c in cells),
                "n_derived": sum(c.cls == "derived" for c in cells)}
    vals = []
    for c in prim:
        if c.tonnes is not None and not any(agree(c.tonnes, x) for x in vals):
            vals.append(c.tonnes)
    return {"state": "eligible", "vals": vals, "unit_problem": any(c.kind != "ok" for c in prim), "prim": prim,
            "n_third": sum(c.cls == "third_party" for c in cells),
            "n_derived": sum(c.cls == "derived" for c in cells)}


# ---------------------------------------------------------------------------------------------------------------------
# extraction run
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class Rec:
    d: dict
    v: dict


@dataclass
class Run:
    file: str
    company: str
    fy: int
    status: str
    records: list
    cid: str | None = None
    spike: bool = False


def load_runs(run_dir=RUN_DIR):
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    runs = []
    for p in manifest["pdfs"]:
        out = json.loads((run_dir / "outputs" / f"{p['stem']}.json").read_text(encoding="utf-8"))
        ver = json.loads((run_dir / "verification" / f"{p['stem']}.json").read_text(encoding="utf-8"))
        if len(ver) != len(out["records"]) or out["report_fiscal_year"] != p["report_year"]:
            raise SystemExit(f"output / verification misaligned for {p['file']}")
        recs = []
        for d, v in zip(out["records"], ver):
            if d["record_index"] != v["record_index"] or d["scope"] != v["scope"] or d["mapped_year"] != v["mapped_year"]:
                raise SystemExit(f"record misaligned in {p['file']} at {d['record_index']}")
            recs.append(Rec(d, v))
        runs.append(Run(p["file"], out["company"], out["report_fiscal_year"], out["status"], recs,
                        spike=p["file"] in SPIKE_FILES))
    return runs


# ---------------------------------------------------------------------------------------------------------------------
# scoring one pair
# ---------------------------------------------------------------------------------------------------------------------
def decide(cvals, vvals):
    """cvals: [(tonnes, rec)] agreeing or not; vvals: distinct primary verified values. -> (category, tier, details)."""
    best = [min(rel_diff(c, v) for v in vvals) for c, _ in cvals]
    matched = [d <= NEAR for d in best]
    agreeing = all(agree(a[0], b[0]) for a in cvals for b in cvals)
    if not any(matched):
        return "verified_mismatch", "other", {"multi_candidate": not agreeing, "best": best}
    tier = tier_of(max(d for d, m in zip(best, matched) if m))
    multi_v = len(vvals) > 1
    if not agreeing:
        return "ambiguous_extracted", tier, {"also_multi_valued": multi_v, "best": best}
    if multi_v:
        return "ambiguous_verified", tier, {"best": best}
    return "verified_match", tier, {"best": best}


def score_pair(run, key, truth, other_year_vals):
    cid, year, scope = key
    recs = [r for r in run.records if r.d["scope"] == scope]
    at_year = [r for r in recs if r.d["mapped_year"] == year]
    cands = [r for r in at_year if has_value(r.d)]
    pair = {"group": "spike" if run.spike else "main", "company": run.company, "cid": cid, "year": year, "scope": scope,
            "report_file": run.file, "report_fy": run.fy, "category": None, "detail": "", "tier": "", "labels": [],
            "n_cand_passed": 0, "n_cand_failed": 0, "n_unit_dropped": 0, "multi_candidate": False,
            "also_multi_valued": False, "also_matches_other_year": False, "thousands_flag": False, "d_sanity_flag": False,
            "extracted_t": [], "verified_t": [fmt(v) for v in truth["vals"]], "n_primary_rows": len(truth["prim"]),
            "n_third_party_ignored": truth["n_third"], "n_derived_ignored": truth["n_derived"], "failed_checks": [],
            "tons_only": False, "sens_category": "", "sens_tier": "", "cands": [], "key_truth": truth}
    if not cands:
        if run.status == "no_pages_found":
            why = "finder_no_pages"
        elif run.status != "completed":
            why = "run_not_completed"
        elif any(is_null(r.d) for r in at_year):
            why = "scope_null"
        elif any(is_placeholder(r.d) for r in at_year):
            why = "placeholder_value"
        elif any(r.d["mapped_year"] is None and has_value(r.d) for r in recs):
            why = "only_unmapped_labels"
        else:
            why = "no_record_for_key"
        pair.update(category="not_extracted", detail=why)
        return pair
    passed = [r for r in cands if r.v["status"] == "pass"]
    pair["n_cand_passed"], pair["n_cand_failed"] = len(passed), len(cands) - len(passed)
    pair["failed_checks"] = sorted({c for r in cands if r.v["status"] != "pass" for c in (r.v["failed"] + r.v["ambiguous"])})
    if not passed:
        pair.update(category="extracted_failed_verifier")
        return pair
    pair["thousands_flag"] = any("assumed_thousands_separator" in r.d.get("harness_flags", []) for r in passed)
    pair["d_sanity_flag"] = any(r.v.get("flags") for r in passed)
    scorable, dropped = [], []
    for r in passed:
        kind, reason, factor = classify_unit(r.d["unit_as_printed"])
        num = r.d.get("value_numeric")
        if kind == "ok" and num is not None:
            scorable.append((Decimal(str(num)) * factor, r))
        else:
            dropped.append((kind if num is not None else "ambiguous", reason if num is not None else "no_numeric", r, num, factor))
    pair["n_unit_dropped"] = len(dropped)
    if truth["unit_problem"] or not scorable:
        reasons = sorted({d[1] for d in dropped}) + (["verified_unit"] if truth["unit_problem"] else [])
        pair.update(category="unit_ambiguous", detail="+".join(reasons))
        if (not scorable and dropped and all(d[0] == "tons" for d in dropped) and not truth["unit_problem"]
                and truth["vals"]):
            pair["tons_only"] = True
            hyp = [(Decimal(str(d[3])) * d[4], d[2]) for d in dropped]
            cat, tier, _ = decide(hyp, truth["vals"])
            pair.update(sens_category=cat, sens_tier=tier)
        return pair
    if not truth["vals"]:
        pair.update(category="unit_ambiguous", detail="verified_unit")
        return pair
    cat, tier, det = decide(scorable, truth["vals"])
    pair.update(category=cat, tier=tier, multi_candidate=det.get("multi_candidate", False),
                also_multi_valued=det.get("also_multi_valued", False),
                extracted_t=[fmt(c) for c, _ in scorable])
    pair["cands"] = [(c, r) for c, r in scorable]
    if cat == "verified_mismatch":
        for (c, _), d in zip(scorable, det["best"]):
            if d <= NEAR:
                continue
            for oy, ov in other_year_vals:
                if rel_diff(c, ov) <= NEAR:
                    same = any(agree(ov, v) for v in truth["vals"])
                    pair["labels"].append("year_mapping_ambiguous" if same else "year_mapping_suspect")
                    break
        pair["labels"] = sorted(set(pair["labels"]))
    elif cat == "verified_match":
        pair["also_matches_other_year"] = any(rel_diff(scorable[0][0], ov) <= NEAR for _, ov in other_year_vals)
    return pair


# ---------------------------------------------------------------------------------------------------------------------
# scoring everything
# ---------------------------------------------------------------------------------------------------------------------
def score(runs, cells, cid_names):
    """runs must have .cid set. Returns every table needed for the outputs."""
    truths = {k: key_truth(v) for k, v in cells.items() if k[1] in YEARS}
    eligible = {k for k, t in truths.items() if t["state"] == "eligible"}
    by_cid = defaultdict(list)
    for r in runs:
        by_cid[r.cid].append(r)
    other_years = defaultdict(list)
    for (cid, year, scope), cs in cells.items():
        for c in cs:
            if c.cls == "primary" and c.tonnes is not None:
                other_years[(cid, scope)].append((year, c.tonnes))
    pairs, key_states = [], []
    for k in sorted(eligible):
        cid, year, scope = k
        covering = [r for r in by_cid[cid] if r.fy in (year, year + 1)]
        main_runs = [r for r in covering if not r.spike]
        name = cid_names.get(cid, cid)
        if not covering:
            state = "no_source_pdf"
        elif not main_runs:
            state = "spike_only"
        else:
            state = "has_main_pair"
        key_states.append({"company": name, "cid": cid, "year": year, "scope": scope, "state": state,
                           "n_main_pairs": len(main_runs), "n_primary_rows": len(truths[k]["prim"]),
                           "multi_valued": len(truths[k]["vals"]) > 1})
        oy = [(y, v) for y, v in other_years[(cid, scope)] if y != year]
        for r in covering:
            p = score_pair(r, k, truths[k], oy)
            p["company"] = name
            pairs.append(p)
    by_key = defaultdict(list)
    for p in pairs:
        by_key[(p["cid"], p["year"], p["scope"])].append(p)
    for ps in by_key.values():  # vintage_difference: another main report matches the same key
        for p in ps:
            if p["category"] == "verified_mismatch" and any(
                    q is not p and q["group"] == "main" and q["category"] == "verified_match" for q in ps):
                p["labels"] = sorted(set(p["labels"]) | {"vintage_difference"})
    buckets = {g: Counter() for g in ("main", "spike")}
    failed = {g: [] for g in ("main", "spike")}
    for r in runs:
        g = "spike" if r.spike else "main"
        for rec in r.records:
            y, s = rec.d["mapped_year"], rec.d["scope"]
            if y is None:
                b = "unmapped"
                buckets[g][(b, "valued" if has_value(rec.d) else "no_value")] += 1
                continue
            if y not in YEARS:
                b = "year_outside_2023_2025"
            elif (r.cid, y, s) not in eligible:
                b = "no_verified_key"
            elif r.fy not in (y, y + 1):
                b = "outside_r2_window"
            else:
                b = "in_pair_scope"
            buckets[g][(b, "")] += 1
            if b == "in_pair_scope" and has_value(rec.d) and rec.v["status"] != "pass":
                failed[g].append(failed_row(rec, truths[(r.cid, y, s)]))
    return {"pairs": pairs, "key_states": key_states, "buckets": buckets, "failed": failed, "truths": truths,
            "n_records": sum(len(r.records) for r in runs)}


def failed_row(rec, truth):
    kind, _, factor = classify_unit(rec.d["unit_as_printed"])
    num = rec.d.get("value_numeric")
    tier = "not_comparable"
    if kind == "ok" and num is not None and truth["vals"] and not truth["unit_problem"]:
        tier = tier_of(min(rel_diff(Decimal(str(num)) * factor, v) for v in truth["vals"]))
    return {"tier": tier, "checks": rec.v["failed"] + rec.v["ambiguous"] or [rec.v["status"]]}


# ---------------------------------------------------------------------------------------------------------------------
# summaries (counts with denominators only)
# ---------------------------------------------------------------------------------------------------------------------
def summary_rows(res, structure_lines=None):
    rows = []

    def add(section, gtype, group, category, detail, n, d, dlabel):
        rows.append({"section": section, "group_type": gtype, "group": group, "category": category, "detail": detail,
                     "count": n, "denominator": d, "denominator_label": dlabel})

    ks, pairs = res["key_states"], res["pairs"]
    for gtype, fn in (("all", lambda x: "all"), ("company", lambda x: x["company"]), ("scope", lambda x: x["scope"])):
        for g in sorted({fn(k) for k in ks}):
            sub = [k for k in ks if fn(k) == g]
            for st in ("no_source_pdf", "spike_only", "has_main_pair"):
                add("key_states", gtype, g, st, "", sum(k["state"] == st for k in sub), len(sub), "keys N")
    truths = res["truths"]
    for st in ("derived_not_extractable", "third_party_only"):
        add("excluded_keys", "all", "all", st, "", sum(t["state"] == st for t in truths.values()), len(truths),
            "keys with any verified cell in 2023-2025")
    for sc in SCOPES:
        sk = [t for k, t in truths.items() if k[2] == sc]
        add("excluded_keys", "scope", sc, "derived_not_extractable", "", sum(t["state"] == "derived_not_extractable" for t in sk),
            len(sk), "keys with any verified cell in 2023-2025")
        add("excluded_keys", "scope", sc, "eligible_keys_with_derived_cells_ignored", "",
            sum(t["state"] == "eligible" and t["n_derived"] > 0 for t in sk), len(sk), "keys with any verified cell in 2023-2025")
    add("excluded_keys", "all", "all", "multi_valued_primary_keys", "", sum(k["multi_valued"] for k in ks), len(ks), "keys N")
    for group in ("main", "spike"):
        gp = [p for p in pairs if p["group"] == group]
        for gtype, fn in (("all", lambda x: "all"), ("company", lambda x: x["company"]), ("scope", lambda x: x["scope"])):
            for g in sorted({fn(p) for p in gp}):
                sub = [p for p in gp if fn(p) == g]
                for c in CATEGORIES:
                    add(f"{group}_pairs", gtype, g, c, "", sum(p["category"] == c for p in sub), len(sub), "pairs P")
        def sub_counts(cat, field_fn, label):
            sel = [p for p in gp if p["category"] == cat]
            for d in sorted({x for p in sel for x in field_fn(p)}):
                add(f"{group}_pair_detail", "all", "all", cat, f"{label}={d}", sum(d in field_fn(p) for p in sel),
                    len(sel), f"{cat} pairs")
        sub_counts("not_extracted", lambda p: [p["detail"]], "reason")
        sub_counts("unit_ambiguous", lambda p: p["detail"].split("+"), "reason")
        for cat in ("verified_match", "ambiguous_extracted", "ambiguous_verified"):
            sub_counts(cat, lambda p: [p["tier"]], "tier")
        sub_counts("verified_mismatch", lambda p: p["labels"] or ["none"], "label")
        mm = [p for p in gp if p["category"] == "verified_mismatch"]
        add(f"{group}_pair_detail", "all", "all", "verified_mismatch", "multi_candidate", sum(p["multi_candidate"] for p in mm),
            len(mm), "verified_mismatch pairs")
        vm = [p for p in gp if p["category"] == "verified_match"]
        add(f"{group}_pair_detail", "all", "all", "verified_match", "assumed_thousands_separator",
            sum(p["thousands_flag"] for p in vm), len(vm), "verified_match pairs")
        add(f"{group}_pair_detail", "all", "all", "verified_match", "also_matches_other_year",
            sum(p["also_matches_other_year"] for p in vm), len(vm), "verified_match pairs")
        add(f"{group}_pair_detail", "all", "all", "verified_match", "d_sanity_flag", sum(p["d_sanity_flag"] for p in vm),
            len(vm), "verified_match pairs")
        tons = [p for p in gp if p["tons_only"]]
        add(f"{group}_sensitivity_tons", "all", "all", "unit_ambiguous_tons_only", "would_be_verified_match",
            sum(p["sens_category"] == "verified_match" for p in tons), len(tons),
            "unit_ambiguous pairs where only tons-class units blocked scoring")
        for t in ("exact", "near"):
            add(f"{group}_sensitivity_tons", "all", "all", "unit_ambiguous_tons_only", f"would_be_verified_match_{t}",
                sum(p["sens_category"] == "verified_match" and p["sens_tier"] == t for p in tons), len(tons),
                "unit_ambiguous pairs where only tons-class units blocked scoring")
        fr = res["failed"][group]
        for t in ("exact", "near", "other", "not_comparable"):
            add(f"{group}_failed_records_NOT_A_PIPELINE_RESULT", "all", "all", "tier", t, sum(x["tier"] == t for x in fr),
                len(fr), "valued records that did not pass the verifier")
        for c in sorted({c for x in fr for c in x["checks"]}):
            add(f"{group}_failed_records_NOT_A_PIPELINE_RESULT", "all", "all", "check", c, sum(c in x["checks"] for x in fr),
                len(fr), "valued records that did not pass the verifier")
        tot = sum(res["buckets"][group].values())
        for b in BUCKETS:
            n = sum(v for (bb, _), v in res["buckets"][group].items() if bb == b)
            add(f"{group}_records", "all", "all", b, "", n, tot, "extracted records")
        for det in ("valued", "no_value"):
            add(f"{group}_records", "all", "all", "unmapped", det, res["buckets"][group][("unmapped", det)],
                tot, "extracted records")
    by_key = defaultdict(list)
    for p in pairs:
        if p["group"] == "main":
            by_key[(p["cid"], p["year"], p["scope"])].append(p["category"])
    nk = len(by_key)
    one = Counter(v[0] for v in by_key.values() if len(v) == 1)
    same = Counter(v[0] for v in by_key.values() if len(v) > 1 and len(set(v)) == 1)
    for c in CATEGORIES:
        add("key_rollup", "all", "all", c, "one_report", one[c], nk, "keys with >= 1 main pair")
        add("key_rollup", "all", "all", c, "several_reports_same_category", same[c], nk, "keys with >= 1 main pair")
    add("key_rollup", "all", "all", "mixed", "several_reports_mixed_categories",
        sum(len(v) > 1 and len(set(v)) > 1 for v in by_key.values()), nk, "keys with >= 1 main pair")
    return rows


def summary_md(rows, header_lines):
    out = ["# Phase B summary (run_001): counts only", "", "No percentages, no accuracy figure. N of M.", ""] + header_lines
    cur = None
    for r in rows:
        head = (r["section"], r["group_type"], r["group"])
        if head != cur:
            cur = head
            out += ["", f"## {r['section']} / {r['group_type']}: {r['group']}"]
        d = f" ({r['detail']})" if r["detail"] else ""
        out.append(f"- {r['category']}{d}: {r['count']} of {r['denominator']} [{r['denominator_label']}]")
    return "\n".join(out) + "\n"


RESULT_COLUMNS = ["group", "company", "year", "scope", "report_file", "report_fy", "category", "detail", "tier", "labels",
                  "n_cand_passed", "n_cand_failed", "n_unit_dropped", "multi_candidate", "also_multi_valued",
                  "also_matches_other_year", "assumed_thousands_separator", "d_sanity_flag", "extracted_tonnes",
                  "verified_tonnes", "n_primary_rows", "n_third_party_ignored", "n_derived_ignored", "failed_checks",
                  "tons_only", "sens_category", "sens_tier"]
ADJ_COLUMNS = ["company", "year", "scope", "category", "labels", "spike_not_blind", "report_file", "report_fy",
               "value_as_printed", "unit_as_printed", "extracted_tonnes", "verified_tonnes", "verified_unit",
               "verified_source_url", "verified_source_page", "verified_notes", "pdf_page", "quote", "human_verdict",
               "human_notes"]


def result_row(p):
    return [p["group"], p["company"], p["year"], p["scope"], p["report_file"], p["report_fy"], p["category"], p["detail"],
            p["tier"], ";".join(p["labels"]), p["n_cand_passed"], p["n_cand_failed"], p["n_unit_dropped"],
            p["multi_candidate"], p["also_multi_valued"], p["also_matches_other_year"], p["thousands_flag"],
            p["d_sanity_flag"], ";".join(p["extracted_t"]), ";".join(p["verified_t"]), p["n_primary_rows"],
            p["n_third_party_ignored"], p["n_derived_ignored"], ";".join(p["failed_checks"]), p["tons_only"],
            p["sens_category"], p["sens_tier"]]


def needs_adjudication(p):
    return (p["category"] in ("verified_mismatch", "ambiguous_extracted", "ambiguous_verified")
            or any(l in p["labels"] for l in ("year_mapping_suspect", "year_mapping_ambiguous", "vintage_difference")))


def adjudication_rows(res):
    out = []
    for p in res["pairs"]:
        if not needs_adjudication(p):
            continue
        prim = p["key_truth"]["prim"]
        vt = "; ".join(p["verified_t"])
        urls = " || ".join(dict.fromkeys(c.source_url for c in prim))
        pages = " || ".join(dict.fromkeys(str(c.source_page) for c in prim))
        notes = " || ".join(dict.fromkeys(c.notes for c in prim if c.notes))
        units = " || ".join(dict.fromkeys(c.unit for c in prim))
        for t, rec in p["cands"]:
            out.append([p["company"], p["year"], p["scope"], p["category"], ";".join(p["labels"]),
                        p["group"] == "spike", p["report_file"], p["report_fy"], rec.d["value_as_printed"],
                        rec.d["unit_as_printed"], fmt(t), vt, units, urls, pages, notes, rec.d["pdf_page"],
                        rec.d["quote"], "", ""])
    return out


# ---------------------------------------------------------------------------------------------------------------------
# structure only (no values)
# ---------------------------------------------------------------------------------------------------------------------
def structure_lines(rows, cells, stats, company_map, unresolved, ext_companies):
    lines = []
    yrs = Counter()
    for r in rows:
        try:
            yrs[int(str(r["fiscal_year"]).strip())] += 1
        except ValueError:
            yrs["unparseable"] += 1
    in_range = sum(v for k, v in yrs.items() if k in YEARS)
    lines += [f"verified data rows (header excluded): {len(rows)}", f"rows with fiscal_year 2023-2025: {in_range}",
              f"rows by fiscal_year: {dict(sorted(yrs.items(), key=lambda kv: str(kv[0])))}",
              f"rows with unparseable fiscal_year: {stats['rows_year_unparseable']}",
              f"non-blank scope cells that could not be parsed as numbers: {stats['cells_unparseable']}"]
    lines.append(f"rows 2023-2025 with a derived token in notes (non-third-party; text not printed): "
                 f"{stats['rows_derived_by_notes_2023_2025']}; cells per scope: "
                 f"{ {sc: stats[f'cells_derived_by_notes_{sc}'] for sc in SCOPES} }")
    st = Counter((r["source_type"], classify_source_type(r["source_type"])) for r in rows)
    st_in = Counter((r["source_type"]) for r in rows if str(r["fiscal_year"]).strip().isdigit() and int(r["fiscal_year"]) in YEARS)
    lines.append("source_type (rows total / rows 2023-2025 / rule class):")
    lines += [f"  {k[0]!r}: {v} / {st_in[k[0]]} / {k[1]}" for k, v in sorted(st.items())]
    un = Counter((r["unit"], classify_unit(r["unit"])[:2]) for r in rows)
    lines.append("unit (rows / scorer class and reason):")
    lines += [f"  {k[0]!r}: {v} / {k[1]}" for k, v in sorted(un.items(), key=lambda kv: str(kv[0]))]
    inr = {k: v for k, v in cells.items() if k[1] in YEARS}
    lines.append("non-blank cells in 2023-2025 per scope (all source types): "
                 + str({s: sum(len(v) for k, v in inr.items() if k[2] == s) for s in SCOPES}))
    for label, pred in (("keys per scope with >= 1 primary cell", lambda t: t["state"] == "eligible"),
                        ("keys per scope with only derived cells (derived_not_extractable)",
                         lambda t: t["state"] == "derived_not_extractable"),
                        ("keys per scope with only third_party cells", lambda t: t["state"] == "third_party_only")):
        c = {s: sum(1 for k, v in inr.items() if k[2] == s and pred(key_truth(v))) for s in SCOPES}
        lines.append(f"{label}: {c} (total {sum(c.values())})")
    lines.append("cells per class (2023-2025): " + str(dict(Counter(c.cls for v in inr.values() for c in v))))
    lines.append("keys in 2023-2025 with more than one primary row: "
                 + str(sum(1 for v in inr.values() if sum(c.cls == 'primary' for c in v) > 1)))
    lines.append("keys in 2023-2025 with more than one row of any class: " + str(sum(1 for v in inr.values() if len(v) > 1)))
    lines.append(f"company join: {len(company_map)} of {len(set(ext_companies))} extraction companies matched; "
                 f"unresolved: {unresolved}")
    return lines


# ---------------------------------------------------------------------------------------------------------------------
# hashes, guards, main
# ---------------------------------------------------------------------------------------------------------------------
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def current_hashes():
    return {"scoring_rules.md": sha(RULES_MD), "score_phase_b.py": sha(HERE),
            "run_001_manifest.json": sha(RUN_DIR / "manifest.json"),
            "verifier.py (frozen, imported)": sha(ROOT / "scripts" / "extraction" / "verifier.py")}


def write_manifest():
    if MANIFEST.exists():
        raise SystemExit("scoring_manifest.json exists; changes go through an explicit logged edit, not a rewrite")
    h = current_hashes()
    test = HERE.with_name("test_score_phase_b.py")
    MANIFEST.write_text(json.dumps({
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "rules hashed BEFORE any verified data row was read",
        "sha256": h, "test_file_sha256_at_creation": sha(test) if test.exists() else None,
        "rule_change_log": []}, indent=2), encoding="utf-8")
    print(json.dumps(h, indent=2))


def guard_run():
    if not MANIFEST.exists():
        raise SystemExit("no scoring_manifest.json")
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))["sha256"]
    bad = {k: (v, current_hashes()[k]) for k, v in m.items() if current_hashes()[k] != v}
    if bad:
        raise SystemExit(f"hash differs from scoring_manifest.json (log the change first): {bad}")
    if (OUT_DIR / "results_by_key.csv").exists():
        raise SystemExit("results_by_key.csv exists: the scorer runs ONCE")


def prepare():
    rows = read_verified()
    cells, stats = build_verified(rows)
    runs = load_runs()
    cmap, unresolved = build_company_map([r.company for r in runs], rows)
    for r in runs:
        r.cid = cmap.get(r.company)
    return rows, cells, stats, runs, cmap, unresolved


def run_all():
    guard_run()
    rows, cells, stats, runs, cmap, unresolved = prepare()
    bad = [k for k in cells if k[1] in YEARS for c in cells[k] if c.cls == "unclassified"]
    if unresolved or bad or stats["cells_unparseable"]:
        raise SystemExit(f"refusing: unresolved companies {unresolved}; unclassified source_type cells {len(bad)}; "
                         f"unparseable cells {stats['cells_unparseable']}")
    names = {}
    for r in rows:
        names.setdefault(r["company_id"], r["company_name"])
    res = score(runs, cells, names)
    srows = summary_rows(res)
    header = [f"- verified rows read: {len(rows)}; extraction records: {res['n_records']}; reports: {len(runs)} "
              f"({sum(r.spike for r in runs)} spike)", "- spike PDFs are in the `spike_*` sections only"]
    with open(OUT_DIR / "results_by_key.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(RESULT_COLUMNS)
        w.writerows(result_row(p) for p in res["pairs"])
        for k in res["key_states"]:
            if k["state"] != "has_main_pair":
                w.writerow(["key_state", k["company"], k["year"], k["scope"], "", "", k["state"]] + [""] * (len(RESULT_COLUMNS) - 7))
    with open(OUT_DIR / "summary.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(srows[0]))
        w.writeheader()
        w.writerows(srows)
    (OUT_DIR / "summary.md").write_text(summary_md(srows, header), encoding="utf-8")
    with open(OUT_DIR / "adjudication_list.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(ADJ_COLUMNS)
        w.writerows(adjudication_rows(res))
    (OUT_DIR / "scoring_run.json").write_text(json.dumps({
        "ran_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "hashes": current_hashes(),
        "verified_rows": len(rows), "pairs": len(res["pairs"])}, indent=2), encoding="utf-8")
    print(f"done: {len(res['pairs'])} pairs, {len(srows)} summary rows")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write-manifest", action="store_true")
    g.add_argument("--structure", action="store_true")
    g.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.write_manifest:
        write_manifest()
    elif a.structure:
        rows, cells, stats, runs, cmap, unresolved = prepare()
        print("\n".join(structure_lines(rows, cells, stats, cmap, unresolved, [r.company for r in runs])))
    else:
        run_all()


if __name__ == "__main__":
    main()
