"""Merge the human adjudication verdicts into a CSV. No API call, no scoring.

    uv run python scripts/extraction_eval/build_adjudication_verdicts.py

Inputs (read only): the verdicts.txt written by hand and the pack template (adjudication_list.csv columns plus
pair_id). Output: data/extraction_eval/run_001_scoring/adjudication_verdicts.csv (UTF-8 with BOM). Verdicts are copied
exactly as written; the script stops without writing anything if a line does not parse or a token is not allowed.
"""
import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACK = Path(r"<adjudication_pack>")
VERDICTS_TXT = PACK / "verdicts.txt"
TEMPLATE_CSV = PACK / "adjudication_verdicts_template.csv"
LIST_CSV = ROOT / "data" / "extraction_eval" / "run_001_scoring" / "adjudication_list.csv"
OUT_CSV = ROOT / "data" / "extraction_eval" / "run_001_scoring" / "adjudication_verdicts.csv"

MAIN_TOKENS = {"vintage_or_restatement", "boundary_or_method", "year_column_wrong", "extraction_correct"}
OTHER_TOKENS = {"unclear", "our_verified_value_wrong", "extraction_wrong"}
ALLOWED_TOKENS = MAIN_TOKENS | OTHER_TOKENS
LINE_RE = re.compile(r"^P0*(\d+)\s+(\S+)\s+-\s+(.*)$")
NOT_ADJUDICATED = "not_adjudicated"


def pair_id(n):
    return f"P{int(n):02d}"


def parse_verdicts(path):
    """Return {pair_id: (verdict or '', note)} and the list of unparsed lines (line number, text)."""
    parsed, bad = {}, []
    for i, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        m = LINE_RE.match(line.strip())
        if not m:
            bad.append((i, line))
            continue
        pid, verdict, note = pair_id(m.group(1)), m.group(2), m.group(3).strip()
        if pid in parsed:
            bad.append((i, f"duplicate pair id {pid}: {line}"))
            continue
        if verdict == "?":
            parsed[pid] = ("", f"{NOT_ADJUDICATED} - {note}")
            continue
        tokens = verdict.split("+")
        unknown = [t for t in tokens if t not in ALLOWED_TOKENS]
        if unknown:
            bad.append((i, f"token(s) not allowed {unknown}: {line}"))
            continue
        parsed[pid] = (verdict, note)
    return parsed, bad


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--verdicts", type=Path, default=VERDICTS_TXT)
    ap.add_argument("--template", type=Path, default=TEMPLATE_CSV)
    ap.add_argument("--list", type=Path, default=LIST_CSV)
    ap.add_argument("--out", type=Path, default=OUT_CSV)
    args = ap.parse_args()

    verdicts, bad = parse_verdicts(args.verdicts)
    if bad:
        for n, text in bad:
            print(f"DID NOT PARSE, line {n}: {text}", file=sys.stderr)
        sys.exit("stopped: nothing written")

    fields, rows = read_csv(args.template)
    list_fields, list_rows = read_csv(args.list)
    if fields[0] != "pair_id" or fields[1:] != list_fields:
        sys.exit("stopped: template columns are not pair_id + the adjudication_list.csv columns")
    if len(rows) != len(list_rows):
        sys.exit(f"stopped: template has {len(rows)} rows, adjudication_list.csv has {len(list_rows)}")
    for i, (t, l) in enumerate(zip(rows, list_rows), start=1):
        if any(t[c] != l[c] for c in list_fields):
            sys.exit(f"stopped: template row {i} differs from adjudication_list.csv")

    template_ids = {r["pair_id"] for r in rows}
    if template_ids != set(verdicts):
        sys.exit("stopped: pair ids differ. only in template: "
                 f"{sorted(template_ids - set(verdicts))}; only in verdicts.txt: {sorted(set(verdicts) - template_ids)}")
    for r in rows:
        if r["human_verdict"] or r["human_notes"]:
            sys.exit(f"stopped: template row for {r['pair_id']} already has a verdict or note")
        r["human_verdict"], r["human_notes"] = verdicts[r["pair_id"]]

    with args.out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    used_other = sorted({t for v, _ in verdicts.values() for t in v.split("+") if t in OTHER_TOKENS})
    print(f"wrote {args.out}: {len(rows)} rows, {len(verdicts)} pairs, "
          f"{sum(1 for v, _ in verdicts.values() if not v)} not adjudicated")
    print(f"tokens outside the four main ones: {used_other or 'none'}")


if __name__ == "__main__":
    main()
