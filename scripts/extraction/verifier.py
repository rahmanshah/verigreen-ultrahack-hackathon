"""Rule-based verifier for extracted records. No LLM, no verified values. Pass or fail per value, naming the check.

Checks (page numbers are 1-based PDF page indexes):
  a_quote_on_page   the quote appears verbatim on the cited page (whitespace normalised, nothing else)
  b_number_matches  a number in the quote equals the extracted value after unit conversion (t, kt, Mt; thousands
                    separators as printed; a unit printed right after the number in the quote overrides
                    unit_as_printed for that number). A line break in the quote is a cell boundary: digits are
                    grouped only within one line. If the value matches only a fragment of a grouped number
                    ("1 027" inside "1 027 622"), the result is "ambiguous", not pass
  c_page_index      the cited page is a page the quote is on (searched over the whole document)
  d_sanity          value is non-negative (fail); Scope 2 market vs location for the same company-year differ by
                    more than 10x (flag on both, not a fail)
A null value passes only as status "not_stated" with a non-empty null_reason.

    <side env python> scripts/extraction/verifier.py <run_dir>    # verifies <run_dir>/records.json
"""
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

SCOPES = ("1", "2_location", "2_market")
RATIO_LIMIT = Decimal(10)

_SPACES = re.compile(r"[\s   ]+")
_RUN = re.compile(r"\d+(?:[ ,.]\d+)*")
_UNIT_AFTER = re.compile(r"\s?(Mt|kt|million tonnes|thousand tonnes|tonnes|t)(?![a-z])")  # "tCO2e" counts as t


def normalise(s: str) -> str:
    """Collapse all whitespace (incl. non-breaking and thin spaces) to one space; unify the minus sign."""
    return _SPACES.sub(" ", s.replace("−", "-")).strip()


def unit_factor(unit: str | None) -> Decimal | None:
    """Tonnes per printed unit, or None if the unit is not recognised."""
    if not unit:
        return None
    s = normalise(unit)
    low = s.lower()
    if re.search(r"million\s*(metric\s*)?(tonnes|tons|t)\b", low) or re.search(r"\bMt", s):
        return Decimal(1_000_000)
    if re.search(r"thousand|['’]000|\b1[ ,.]?000\s*t", low) or re.search(r"\bkt", low):
        return Decimal(1000)
    if re.search(r"\b(t|tonnes?|tons?|metric tons?)\b|\btco", low):
        return Decimal(1)
    return None


def _interpret(atoms: list[str], seps: list[str], thousands: set[str], decimal: str) -> Decimal | None:
    """Value of digit groups joined by seps under one separator convention, or None if not valid under it."""
    if seps and seps[-1] == decimal:
        int_atoms, int_seps, frac = atoms[:-1], seps[:-1], atoms[-1]
    else:
        int_atoms, int_seps, frac = atoms, seps, ""
    if any(s not in thousands for s in int_seps) or len(set(int_seps)) > 1:
        return None
    if int_seps:
        if not 1 <= len(int_atoms[0]) <= 3 or any(len(a) != 3 for a in int_atoms[1:]):
            return None
    if len(int_atoms[0]) > 1 and int_atoms[0][0] == "0":
        return None
    try:
        return Decimal("".join(int_atoms) + ("." + frac if frac else ""))
    except InvalidOperation:
        return None


def numbers_in_quote(quote: str) -> list[tuple[Decimal, Decimal | None, str, bool]]:
    """Every reading of every number in the quote: (value as printed, unit factor printed right after it or None,
    printed text, whole). Space-separated table cells are ambiguous ("1 027 622 1 013 282"), so all contiguous
    groupings valid under comma/space-thousands or dot/space-thousands conventions are returned. A reading is whole
    if no longer valid grouping under the same convention contains it ("1 027 622"); otherwise it is a fragment
    ("1 027", "622"). A line break is a cell boundary: digits are grouped only within one line."""
    out = []
    for line in quote.splitlines():
        out += _numbers_in_line(normalise(line))
    return out


def _numbers_in_line(q: str) -> list[tuple[Decimal, Decimal | None, str, bool]]:
    out = []
    for m in _RUN.finditer(q):
        parts = re.split(r"([ ,.])", m.group())
        atoms, seps = parts[0::2], parts[1::2]
        negative = m.start() > 0 and q[m.start() - 1] == "-"
        after_end = _UNIT_AFTER.match(q, m.end())
        for thousands, dec in (({",", " "}, "."), ({".", " "}, ",")):
            valid = {}
            for i in range(len(atoms)):
                for j in range(i, len(atoms)):
                    v = _interpret(atoms[i : j + 1], seps[i:j], thousands, dec)
                    if v is not None:
                        valid[(i, j)] = v
            for (i, j), v in valid.items():
                whole = not any(i2 <= i and j2 >= j and (i2, j2) != (i, j) for i2, j2 in valid)
                text = "".join(a + s for a, s in zip(atoms[i : j + 1], seps[i:j] + [""]))
                after = unit_factor(after_end.group(1)) if after_end and j == len(atoms) - 1 else None
                out.append((-v if negative and i == 0 else v, after, text, whole))
    return out


def _check_record(rec: dict, pages: dict[int, str], sent_pages: list[int] | None) -> dict:
    res = {k: rec.get(k) for k in ("company", "scope", "year", "value", "unit_as_printed", "pdf_page")}
    res.update(status="pass", failed=[], ambiguous=[], flags=[], details={})

    def fail(check: str, why: str) -> None:
        res["failed"].append(check)
        res["details"][check] = why

    if rec.get("scope") not in SCOPES or not isinstance(rec.get("year"), int):
        fail("schema", f"scope {rec.get('scope')!r} / year {rec.get('year')!r} invalid")

    value = rec.get("value")
    if value is None:
        if not (rec.get("null_reason") or "").strip():
            fail("null_reason", "value is null but no reason given")
        res["status"] = "fail" if res["failed"] else "not_stated"
        return res

    quote, page = rec.get("quote") or "", rec.get("pdf_page")
    nq = normalise(quote)

    # (a) quote verbatim on the cited page
    if not nq:
        fail("a_quote_on_page", "no quote given")
    elif page not in pages:
        fail("a_quote_on_page", f"cited PDF page {page} is outside the document (1-{max(pages)})")
    elif nq not in normalise(pages[page]):
        fail("a_quote_on_page", f"quote not found on cited PDF page {page}")

    # (b) number in quote equals value after unit conversion
    f_rec = unit_factor(rec.get("unit_as_printed"))
    if f_rec is None:
        fail("b_number_matches", f"unit_as_printed {rec.get('unit_as_printed')!r} not recognised")
    else:
        target = Decimal(str(value)) * f_rec
        readings = numbers_in_quote(quote)
        hits = [(t, w) for v, f, t, w in readings if v * (f if f is not None else f_rec) == target]
        whole_hits = [t for t, w in hits if w]
        if not hits:
            seen = sorted({t for _, _, t, w in readings if w})
            fail("b_number_matches", f"{value} {rec.get('unit_as_printed')} (= {target.normalize():f} t) not in quote numbers {seen}")
        elif whole_hits:
            res["details"]["b_matched_text"] = whole_hits[0]
        else:
            res["ambiguous"] = ["b_number_matches"]
            res["details"]["b_number_matches"] = f"matches only a fragment of a grouped number: {sorted({t for t, _ in hits})}"

    # (c) cited page is a page the quote is on
    if nq:
        found = [n for n, t in pages.items() if nq in normalise(t)]
        if page not in found:
            fail("c_page_index", f"quote on PDF pages {found or 'none'}, cited {page}")
        elif sent_pages is not None and page not in sent_pages:
            fail("c_page_index", f"cited PDF page {page} was not among the pages sent {sent_pages}")

    # (d) non-negative (the 2_market vs 2_location ratio is checked across records in verify())
    if Decimal(str(value)) < 0:
        fail("d_sanity", f"negative value {value}")

    if res["failed"]:
        res["status"] = "fail"
    elif res["ambiguous"]:
        res["status"] = "ambiguous"
    return res


def verify(records: list[dict], pages: dict[int, str], sent_pages: list[int] | None = None) -> list[dict]:
    """Verify every record against the document's page texts (keyed by 1-based PDF page index)."""
    results = [_check_record(r, pages, sent_pages) for r in records]
    by_key: dict[tuple, dict[str, dict]] = {}
    for res in results:
        if res["scope"] in ("2_location", "2_market") and res["value"] is not None:
            f = unit_factor(res["unit_as_printed"])
            if f is not None:
                res["_t"] = Decimal(str(res["value"])) * f
                by_key.setdefault((res["company"], res["year"]), {})[res["scope"]] = res
    for pair in by_key.values():
        if len(pair) == 2:
            loc, mkt = pair["2_location"]["_t"], pair["2_market"]["_t"]
            lo, hi = sorted((abs(loc), abs(mkt)))
            if (lo == 0 and hi > 0) or (lo > 0 and hi / lo > RATIO_LIMIT):
                ratio = "inf" if lo == 0 else f"{hi / lo:.1f}"
                for r in pair.values():
                    r["flags"].append(f"d_sanity: market {mkt.normalize():f} t vs location {loc.normalize():f} t, ratio {ratio} > 10")
    for res in results:
        res.pop("_t", None)
    return results


def summary_line(r: dict) -> str:
    v = "null" if r["value"] is None else f"{r['value']} {r['unit_as_printed']}"
    why = "; ".join(f"{c}: {r['details'][c]}" for c in r["failed"] + r["ambiguous"])
    return f"{r['company']:<10} {r['year']} {r['scope']:<10} {v:<22} p{r['pdf_page']!s:<4} {r['status'].upper():<10} {why} {' | '.join(r['flags'])}".rstrip()


def main(run_dir: Path) -> None:
    sys.path.insert(0, str(Path(__file__).parent))
    import config
    from page_finder import page_texts

    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    records = json.loads((run_dir / "records.json").read_text(encoding="utf-8"))["records"]
    pages = page_texts(config.PDF_DIR / meta["pdf"])
    results = verify(records, pages, meta["sent_pages"])
    (run_dir / "verification.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    for r in results:
        print(summary_line(r))
    counts = {s: sum(r["status"] == s for r in results) for s in ("pass", "ambiguous", "fail", "not_stated")}
    print(f"{meta['pdf']}: {counts}, flagged {sum(bool(r['flags']) for r in results)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
