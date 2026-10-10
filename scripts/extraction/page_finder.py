"""Keyword page finder: picks pages likely to hold the Scope 1 / Scope 2 table. No LLM, no verified values.

A page qualifies only if it mentions Scope 1 and Scope 2 and either a Scope 2 method or a CO2e unit. Qualifying
pages are ranked by keyword hits plus numeric density; the top PAGE_CAP are kept, returned in page order.
Page numbers are 1-based PDF page indexes.

    <side env python> scripts/extraction/page_finder.py            # report for the configured PDFs
"""
import re
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402

S1 = re.compile(r"scope\s*1\b")
S2 = re.compile(r"scope\s*2\b")
METHOD = re.compile(r"market[\s-]*based|location[\s-]*based")
UNIT = re.compile(r"t\s*co\s*2\s*-?\s*e|co2e|co₂e|tonnes? co")
GHG = re.compile(r"ghg emissions|greenhouse gas emissions|e1-6")
NUMBER = re.compile(r"\d[\d ,.]{2,}")


def score(text: str) -> int:
    t = text.lower()
    if not (S1.search(t) and S2.search(t)):
        return 0
    if not (METHOD.search(t) or UNIT.search(t)):
        return 0
    s = 2 * len(S1.findall(t)) + 2 * len(S2.findall(t)) + 3 * len(METHOD.findall(t))
    s += len(UNIT.findall(t)) + 2 * len(GHG.findall(t))
    s += min(len(NUMBER.findall(t)), 40) // 5  # numeric density, capped
    return s


def page_texts(pdf_path: Path) -> dict[int, str]:
    """All page texts keyed by 1-based PDF page index."""
    with pymupdf.open(pdf_path) as doc:
        return {i + 1: page.get_text() for i, page in enumerate(doc)}


def find_pages(texts: dict[int, str], cap: int = config.PAGE_CAP) -> list[int]:
    ranked = sorted(((score(t), n) for n, t in texts.items()), reverse=True)  # same tie order as the dry run
    return sorted(n for s, n in ranked[:cap] if s > 0)


def main() -> None:
    for key, (fname, _) in config.PDFS.items():
        texts = page_texts(config.PDF_DIR / fname)
        sel = find_pages(texts)
        low = [n for n, t in texts.items() if len(t.strip()) < config.LOW_TEXT_CHARS]
        print(f"{key}: {fname} [{len(texts)} pages]")
        print(f"  low-text pages (<{config.LOW_TEXT_CHARS} chars): {low}")
        for n in sel:
            c = len(texts[n].strip())
            flag = "  <-- LOW TEXT" if c < config.LOW_TEXT_CHARS else ""
            print(f"  PDF page {n:<4} score {score(texts[n]):<4} {c:>6} chars{flag}")


if __name__ == "__main__":
    main()
