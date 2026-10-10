"""Data-trust score for the FY2024 emissions inputs (`data/bronze/data_trust_inputs.csv`).

What `u` is: a revision-risk / comparability score. It says how likely a company's FY2024 Scope 1+2
figure is to be revised, or to be not like-for-like with adjacent years, based on documented
verification evidence. It is NOT a judgement of the company's honesty or of its reporting quality.
Companies that disclosed restatements transparently score HIGHER by construction, because the
disclosure is what makes the restatement visible. u = 0 means "no documented revision risk found",
not "known to be correct".

Rule table (see WEIGHTS), equal weights over the four scored flags:
- restated: the company later changed its published FY2024 Scope 1 or market-based Scope 2 value, and
  the log documents the change.
- boundary_or_methodology_break: the log documents a change in organisational boundary, consolidation
  scope or calculation method that makes the FY2024 value not like-for-like with FY2023 and/or FY2025.
- partly_estimated: a primary document or the log states that part of the FY2024 Scope 1+2 figure
  rests on estimates, extrapolation or assumptions rather than measurement.
- revenue_boundary_mismatch: the FY2024 revenue denominator is not confirmed to cover the same
  entities as the FY2024 emissions (`boundary_match` is not true in `revenue_boundary_reviews.csv`).
- single_source (weight 0, informational): the FY2024 value has no third-party row in
  `emissions_raw.csv`. It describes our dataset, not the company, and is true for most companies, so
  it is kept but not scored.

Two scores: `u` treats every flag marked ambiguous as false; `u_high` treats every ambiguous flag as
true. u_high is an upper bound for sensitivity tests.

Evidence column grammar: segments joined by " ;; ", each `flag::file::section::quote` (a citation) or
`flag::ambiguous::reason`. Every true flag needs at least one citation, every ambiguous segment must be
on a flag that is false, and every quote must still appear, verbatim (whitespace-normalised), in the
cited file under the cited section. The quote and section must not contain "::" or " ;; ".
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
INPUTS_PATH = ROOT / "data" / "bronze" / "data_trust_inputs.csv"

FLAGS = ["restated", "boundary_or_methodology_break", "partly_estimated",
         "revenue_boundary_mismatch", "single_source"]
WEIGHTS = {"restated": 0.25, "boundary_or_methodology_break": 0.25, "partly_estimated": 0.25,
           "revenue_boundary_mismatch": 0.25, "single_source": 0.0}
SEGMENT_SEP = " ;; "
FIELD_SEP = "::"
AMBIGUOUS = "ambiguous"


class Segment(NamedTuple):
    flag: str
    file: str | None      # None for an ambiguous segment
    section: str | None
    text: str             # the quote, or the reason for an ambiguous segment

    @property
    def is_ambiguous(self) -> bool:
        return self.file is None


def parse_evidence(cell) -> list[Segment]:
    """Parses one evidence cell. Raises ValueError on a malformed segment."""
    if pd.isna(cell) or not str(cell).strip():
        return []
    out = []
    for raw in str(cell).split(SEGMENT_SEP):
        parts = raw.split(FIELD_SEP)
        if len(parts) == 3 and parts[1] == AMBIGUOUS:
            out.append(Segment(parts[0].strip(), None, None, parts[2].strip()))
        elif len(parts) == 4:
            out.append(Segment(*(p.strip() for p in parts)))
        else:
            raise ValueError(f"malformed evidence segment: {raw[:80]!r}")
    return out


def ambiguous_flags(cell) -> set[str]:
    return {s.flag for s in parse_evidence(cell) if s.is_ambiguous}


def load_data_trust_inputs(path: Path = INPUTS_PATH) -> pd.DataFrame:
    return pd.read_csv(path)


def compute_data_trust(inputs: pd.DataFrame) -> pd.DataFrame:
    """Adds u, u_high, and tie-aware ranks (1 = most trusted, ties share the lowest rank) to a copy."""
    df = inputs.copy()
    amb = df["evidence"].map(ambiguous_flags)
    for flag in FLAGS:
        df[flag] = df[flag].astype(bool)
    df["u"] = sum(WEIGHTS[f] * df[f].astype(float) for f in FLAGS)
    df["u_high"] = sum(WEIGHTS[f] * (df[f] | amb.map(lambda s, f=f: f in s)).astype(float) for f in FLAGS)
    df["n_ambiguous"] = amb.map(len)
    df["rank_u"] = df["u"].rank(method="min").astype(int)
    df["rank_u_high"] = df["u_high"].rank(method="min").astype(int)
    return df


def _section_body(text: str, section: str) -> str | None:
    """Text under the first heading (or bold-only title line) starting with `section`, up to the next
    heading of the same or higher level (for a bold title: the next bold title or any heading)."""
    lines = text.splitlines()
    heading = re.compile(r"^(#+)\s+(.*)$")
    bold = re.compile(r"^\*\*([^*]+)\*\*$")
    start = level = None
    for i, line in enumerate(lines):
        m = heading.match(line)
        if m and m.group(2).strip().startswith(section):
            start, level = i, len(m.group(1))
            break
        b = bold.match(line.strip())
        if b and b.group(1).strip().startswith(section):
            start, level = i, 99
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        m = heading.match(lines[j])
        if (m and len(m.group(1)) <= level) or (level == 99 and (m or bold.match(lines[j].strip()))):
            end = j
            break
    return "\n".join(lines[start:end])


def _norm(s: str) -> str:
    return " ".join(s.split())


def check_citation(seg: Segment, root: Path = ROOT) -> str | None:
    """None if the quote is still in the cited file (and section, for markdown); else a problem string."""
    path = root / seg.file
    if not path.exists():
        return f"{seg.flag}: cited file not found: {seg.file}"
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".md":
        body = _section_body(text, seg.section)
        if body is None:
            return f"{seg.flag}: section {seg.section!r} not found in {seg.file}"
        text = body
    if _norm(seg.text) not in _norm(text):
        where = f"{seg.file} / {seg.section}" if path.suffix == ".md" else seg.file
        return f"{seg.flag}: quote not found in {where}: {seg.text[:60]!r}"
    return None


def validate_data_trust_inputs(df: pd.DataFrame, expected_companies: set[str] | None = None,
                               root: Path = ROOT) -> list[str]:
    """Human-readable problems; empty list means the file is consistent."""
    problems: list[str] = []
    need = ["company_id", "fiscal_year", *FLAGS, "evidence"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        return [f"missing columns: {missing}"]
    if df["company_id"].duplicated().any():
        problems.append("duplicate company_id rows")
    if set(df["fiscal_year"]) != {2024}:
        problems.append("fiscal_year must be 2024 for every row")
    if expected_companies is not None and set(df["company_id"]) != expected_companies:
        problems.append(f"company set differs: {sorted(set(df['company_id']) ^ expected_companies)}")
    for flag in FLAGS:
        if not df[flag].map(lambda v: isinstance(v, (bool,)) or str(v).lower() in ("true", "false")).all():
            problems.append(f"{flag} must be boolean")
    for _, row in df.iterrows():
        cid = row["company_id"]
        try:
            segs = parse_evidence(row["evidence"])
        except ValueError as e:
            problems.append(f"{cid}: {e}")
            continue
        for seg in segs:
            if seg.flag not in FLAGS:
                problems.append(f"{cid}: unknown flag {seg.flag!r} in evidence")
            if not seg.text:
                problems.append(f"{cid}: empty evidence text for {seg.flag}")
        for flag in FLAGS:
            value = str(row[flag]).lower() == "true"
            cites = [s for s in segs if s.flag == flag and not s.is_ambiguous and s.text]
            ambs = [s for s in segs if s.flag == flag and s.is_ambiguous]
            if value and not cites:
                problems.append(f"{cid}: {flag} is true but has no evidence citation")
            if ambs and value:
                problems.append(f"{cid}: {flag} is ambiguous but set true")
            if ambs and cites:
                problems.append(f"{cid}: {flag} has both ambiguous and cited evidence")
        for seg in segs:
            if not seg.is_ambiguous and seg.text:
                p = check_citation(seg, root)
                if p:
                    problems.append(f"{cid}: {p}")
    return problems
