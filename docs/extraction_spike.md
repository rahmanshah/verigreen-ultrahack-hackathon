# LLM extraction spike: Scope 1 / Scope 2 from three report PDFs (7 Oct 2026)

Pre-event spike of the extraction + verification step. Three PDFs, one gpt-6-luna call each, a rule-based verifier,
no retries, no hand-fixing, no fallback model. **No accuracy rate is stated**: values were not scored against the
hand-verified rows, by design. Correctness here means only "passed the verifier", plus whatever Shah confirms by
reading the page.

Page numbers in this report are **1-based PDF page indexes** (the PDF's own page order), not the page numbers
printed in the reports.

## Setup

| Item | Value |
|---|---|
| Code | `scripts/extraction/` (`config.py`, `page_finder.py`, `extractor.py`, `verifier.py`, `test_verifier.py`) |
| Environment | side env `<venvs>\verigreen-extract`, Python 3.12.11, pymupdf 1.28.2, openai 3.26.0, python-dotenv 1.2.4 (all from PyPI); project env untouched |
| Provider / base URL | openai / `https://api.openai.com/v1` (only in `config.py`) |
| Model | `gpt-6-luna`; reasoning effort `low`; temperature not sent; strict JSON-schema output; `max_output_tokens` 8000; `store` false; `max_retries` 0 |
| Page finder | keyword score, page must mention Scope 1 and Scope 2 and a Scope 2 method or a CO2e unit; top 4 pages per PDF |
| Targets | scopes 1, 2_location, 2_market x years 2023, 2024, 2025 = 9 records per PDF |
| Raw outputs | `data/extraction/raw_responses/<run>/` (git-ignored: they quote the PDFs verbatim) |

### Model capabilities (checked before the first call, no completion call used)

| Capability | Status | Source |
|---|---|---|
| Structured JSON output | verified | model page lists `structured_outputs` |
| Reasoning effort | verified: `none`, `low`, `medium` (default), `high`, `xhigh`, `max` | model page |
| Reasoning tokens billed as output, bounded by `max_output_tokens` | verified | reasoning guide |
| Temperature | **not documented**; not sent. Every response reports `temperature: 1.0`, so the model runs at its default and the output is **not guaranteed repeatable**. No repeat run was made to measure this. | model page, reasoning guide, responses |

### Verifier (no LLM)

| Check | Rule |
|---|---|
| a_quote_on_page | quote appears verbatim on the cited page (whitespace normalised only) |
| b_number_matches | a number in the quote equals the value after unit conversion (t, kt, Mt; separators as printed). A line break in the quote is a cell boundary: digits are grouped only within one line. Matching only a fragment of a grouped number gives **ambiguous**, not pass |
| c_page_index | the cited page is a page the quote is on, and was among the pages sent |
| d_sanity | negative value fails; Scope 2 market vs location more than 10x apart is **flagged** (not failed) |

Self-tests use made-up inputs only: 13 tests, all pass (`1,234 t`, `1.2 kt`, `0.5 Mt`, quote not on page, wrong page
index, page not sent, negative value, market vs location 16.7x, `1 027 622 1 013 282` with 1027 ambiguous and
1027622 pass, `Gross Scope 1 (tCO2eq)\n1,458\n925` with 925 pass and 458925 fail, null without reason).

**Revision (7 Oct, after the three calls):** check (b) originally collapsed line breaks to spaces before grouping
digits, which made two Elisa values "ambiguous" (see Failures and oddities, item 2). On Shah's instruction, line breaks
are now cell boundaries in check (b) only; checks (a) and (c) keep the full whitespace normalisation. The three saved
responses were re-verified from disk with no API call. This is a post-hoc change to the verifier, made after seeing
results; it changes no model output. The previous verifier results are kept as `verification_before_linebreak_fix.json`
in each run folder. Tables below show the re-verified statuses.

## Results per PDF

`⏎` marks a line break inside the quote as returned by the model. Status is the verifier's; "not stated" = value
null with a reason.

### Outokumpu: `Outokumpu_Sustainability_Statement_2025.pdf`

Pages sent: 45, 47, 48, 49. Run `20261007T122947Z_outokumpu_2025_gpt-6-luna`.
Tokens in 5,314 (5,311 cache write), out 929 (182 reasoning). Latency 9.48 s. Cost USD 0.00113.

| Year | Scope | Value | Unit as printed | Page | Status | Failing check |
|---|---|---|---|---|---|---|
| 2023 | 1 | null | | | not stated | |
| 2024 | 1 | 990643 | tCO2eq | 48 | pass | |
| 2025 | 1 | 1027622 | tCO2eq | 48 | pass | |
| 2023 | 2_location | null | | | not stated | |
| 2024 | 2_location | 448567 | tCO2eq | 48 | pass | |
| 2025 | 2_location | 435773 | tCO2eq | 48 | pass | |
| 2023 | 2_market | null | | | not stated | |
| 2024 | 2_market | 364704 | tCO2eq | 48 | pass | |
| 2025 | 2_market | 373505 | tCO2eq | 48 | pass | |

Quotes (page 48):
- Scope 1: `Gross Scope 1 GHG emissions (tCO2eq)1) ⏎ 1,213,634 ⏎ 990,643 ⏎ 1,027,622`
- 2_location: `Gross location-based Scope 2 GHG emissions (tCO2eq))4) ⏎ n/a ⏎ 448,567 ⏎ 435,773`
- 2_market: `Gross market-based Scope 2 GHG emissions (tCO2eq) ⏎ 1,210,872 ⏎ 364,704 ⏎ 373,505`

Column header text on page 48 (as extracted): `Base year2) / Comparative / N / %N/N-1 / 2016 / 2024 / 2025 / Change, %`.

Notes returned (the first two checked by Shah on the rendered pages, see Verified vs not verified; the third
unchecked):
- Scope 1 2025: "Liner ships transporting material between Tornio and Terneuzen are reported in Scope 1 due to the nature of their use."
- 2_location 2024: "Calculations updated to utilize more recent emission factors; the 2024 reported value changed from 540,274 tCO2 to 448,567 tCO2."
- 2_location 2025: "Scope 2 location-based calculations were updated to utilize more recent emission factors, resulting in changes to prior-period reported emissions."

Null reasons (2023, all three scopes): "No ... figure for 2023 is printed on the supplied pages."

### Orion: `orion-financial-statement-documents-2025.pdf`

Pages sent: 66, 68, 69. Run `20261007T123818Z_orion_2025_gpt-6-luna`.
Tokens in 2,863 (2,860 cache write), out 771 (119 reasoning). Latency 7.11 s. Cost USD 0.00074.

| Year | Scope | Value | Unit as printed | Page | Status | Failing check |
|---|---|---|---|---|---|---|
| 2023 | 1 | null | | | not stated | |
| 2024 | 1 | 5625 | tCO2e | 68 | pass | |
| 2025 | 1 | 5018 | tCO2e | 68 | pass | |
| 2023 | 2_location | null | | | not stated | |
| 2024 | 2_location | 11247 | tCO2e | 68 | pass | |
| 2025 | 2_location | 6776 | tCO2e | 68 | pass | |
| 2023 | 2_market | null | | | not stated | |
| 2024 | 2_market | 5330 | tCO2e | 68 | pass | |
| 2025 | 2_market | 4557 | tCO2e | 68 | pass | |

Quotes (page 68):
- Scope 1: `Gross Scope 1 GHG emissions (tCO2e) ⏎ 2023 ⏎ 5,625 ⏎ 5,018`
- 2_location: `Gross location-based Scope 2 GHG emissions (tCO2e) ⏎ 2023 ⏎ 11,247 ⏎ 6,776`
- 2_market: `Gross market-based Scope 2 GHG emissions (tCO2e) ⏎ 2023 ⏎ 5,330 ⏎ 4,557`

Column header text on page 68 (as extracted): `Base year / 2024 / 2025 / Change`; the Scope 1 row continues `-11%`.

Notes returned: none.
Null reasons (2023): "The table identifies 2023 as the base year but does not print a ... value for 2023."

### Elisa: `Elisa_AnnualReport_2025.pdf`

Pages sent: 63, 67, 68. Run `20261007T123838Z_elisa_2025_gpt-6-luna`.
Tokens in 3,026 (3,023 cache write), out 622 (0 reasoning). Latency 4.53 s. Cost USD 0.00069.

| Year | Scope | Value | Unit as printed | Page | Status | Before revision | Flag |
|---|---|---|---|---|---|---|---|
| 2023 | 1 | null | | | not stated | not stated | |
| 2024 | 1 | 925 | tCO2eq | 67 | pass | ambiguous (b: fragment `925`) | |
| 2025 | 1 | 1458 | tCO2eq | 67 | pass | pass | |
| 2023 | 2_location | null | | | not stated | not stated | |
| 2024 | 2_location | 44026 | tCO2eq | 67 | pass | pass | d: market/location 30.7x |
| 2025 | 2_location | 35158 | tCO2eq | 67 | pass | pass | d: market/location 72.5x |
| 2023 | 2_market | null | | | not stated | not stated | |
| 2024 | 2_market | 1432 | tCO2eq | 67 | pass | pass | d: market/location 30.7x |
| 2025 | 2_market | 485 | tCO2eq | 67 | pass | ambiguous (b: fragment `485`) | d: market/location 72.5x |

Quotes (page 67):
- Scope 1: `Gross Scope 1 GHG emissions (tCO2eq) ⏎ 1,035 ⏎ 1,458 ⏎ 925`
- 2_location: `Gross location-based Scope 2 GHG emissions (tCO2eq) ⏎ 53,510 ⏎ 35,158 ⏎ 44,026`
- 2_market: `Gross market-based Scope 2 GHG emissions (tCO2eq) ⏎ 2,328 ⏎ 485 ⏎ 1,432`

Column header text on page 67 (as extracted): `Base year (2021) / 2025 / 2024 / % 2025/2024 / 2030 / 2040`, i.e. **2025 before
2024**. The Scope 1 row continues `158 / 600`.

Notes returned: none.
Null reasons (2023): "The supplied pages do not print a ... figure for 2023."

## Totals

| | Outokumpu | Orion | Elisa | Total |
|---|---|---|---|---|
| Input tokens | 5,314 | 2,863 | 3,026 | 11,203 |
| Output tokens (reasoning) | 929 (182) | 771 (119) | 622 (0) | 2,322 (301) |
| Latency | 9.48 s | 7.11 s | 4.53 s | 21.12 s |
| Cost (USD, input at cache-write rate) | 0.00113 | 0.00074 | 0.00069 | **0.00256** |
| Verifier: pass / ambiguous / fail / not stated | 6 / 0 / 0 / 3 | 6 / 0 / 0 / 3 | 6 / 0 / 0 / 3 | 18 / 0 / 0 / 9 |
| Before the line-break revision | 6 / 0 / 0 / 3 | 6 / 0 / 0 / 3 | 4 / 2 / 0 / 3 | 16 / 2 / 0 / 9 |

Per-PDF counts only; do not quote the total as an accuracy rate.

Spend cap EUR 5; spent about EUR 0.0026 (1 USD treated as 1 EUR, conservative). Pre-call input estimates
(characters / 4) were within 4% of actual input tokens (5,139 vs 5,314; 2,957 vs 2,863; 2,972 vs 3,026); the cap
check used 2x that plus the full 8,000-token output cap.

## Failures and oddities

1. **No call failed**; all three responses were `completed` with valid JSON. No retry, no hand-fixing, no Sol.
2. **Elisa, two "ambiguous" results were a verifier artefact, not model behaviour.** The first verifier collapsed
   line breaks to spaces, so the cells `1,458 ⏎ 925` read as `1,458 925`, and `458 925` is a valid space-grouped
   number; `925` and `485` counted as fragments. Fixed in the verifier (line break = cell boundary in check (b));
   re-verified from disk, both now pass. No other status or flag changed in any of the three runs.
3. **Elisa market vs location flags (30.7x, 72.5x).** The flag works as designed. A large gap can happen when
   renewable electricity is bought (market-based low), but the verifier cannot judge that, and it was not checked.
4. **Temperature reported as 1.0** in every response although none was sent: the model's default, not controllable
   as far as the docs show. Output repeatability is untested.
5. **Prompt caching wrote the input** (`cache_write_tokens` about equal to input tokens) even with `store` false, so
   input bills at the cache-write rate ($0.125 vs $0.10 per 1M). The first ledger entry (Outokumpu) was recorded at
   the old rate (`cost_eur` 0.00100); the ledger was not edited, the running total is recomputed at the new rate.
6. **Orion quotes contain `2023`** (the base-year label in the base-year column). Check (b) would accept a value of
   2023 from that quote: a year printed in a row can pass as a number.
7. **Footnote markers are glued to labels** (`(tCO2eq)1)`, `(tCO2eq))4)`); harmless here, but a marker glued to a
   number would break check (b) or match the wrong number.

## Verified vs not verified

Verified mechanically by the verifier, for every non-null value:
- the quote is on the cited page (a) and that page is where the quote is (c), against PyMuPDF text of the PDF;
- the value appears in the quote as a whole number within one line (b);
- non-negative; Scope 2 market vs location ratio checked (d).

Checked by Claude reading the extracted page text (not by the verifier): the column headers above each table, quoted
above. On that text the year assigned to each of the 18 values matches the column order, including Elisa's
2025-before-2024 order, and the printed % columns fit (Elisa Scope 1 158 = 1,458 / 925; Orion Scope 1 -11% =
5,018 / 5,625). **Manually checked by Shah on the rendered pages on 7 Oct** (Outokumpu PDF p48, Elisa p67, Orion
p68): values, year columns, printed change columns, 2023 nulls. 18 values from three clean tables; not an accuracy
rate.

Notes, checked by Shah on the rendered pages (7 Oct):
- Outokumpu 2_location 2024, restatement 540,274 to 448,567 tCO2: confirmed by footnote 4 on p48.
- Outokumpu Scope 1 2025, liner ships: confirmed across p48 and p49, but the note is a paraphrase stitched across two
  pages and omits the boundary change printed next to it (Tornio product transports were reported in Scope 3 in
  previous years).
- All other notes remain unchecked.

Pricing: gpt-6.1-sol cache write $2.50 per 1M tokens vs $2.00 input, verified from the pricing page (Sol was not used).

Not verified:
- **which year a column belongs to**: the verifier cannot check this; a value from the wrong column still passes
  (for these 18 values it was checked manually, above);
- **notes**: not checked by the verifier; apart from the two Outokumpu notes above, unchecked;
- **null reasons**: "not printed on the supplied pages" only covers the 3-4 pages sent, not the whole report;
- that the text PyMuPDF extracts matches the rendered page (verification is against the same text the model saw);
- whether other pages of the report hold a different or restated figure for the same company-year;
- repeatability (one run per PDF, temperature fixed at the model default).

## Failure modes that worry me for a full evaluation at the event

1. **Column-to-year mapping.** Base-year columns and non-chronological order (Elisa 2025 before 2024) are exactly
   the error class this project has already documented, and the verifier is blind to it. Candidate check: parse the
   header row, or use the printed change column (e.g. % 2025/2024) to confirm the pair of values.
2. **Number grouping depends on line breaks in the extracted text.** Check (b) now treats a line break as a cell
   boundary, which fixed the false "ambiguous" on Elisa. It relies on PyMuPDF putting each table cell on its own line.
   Where cells of a space-separated table land on one line (`1 027 622 1 013 282`), the ambiguity is real and stays
   "ambiguous"; where one number is split across lines, (b) will fail it. Any further verifier change should be fixed
   before the event run, not tuned on its results (this revision was made after seeing results).
3. **Scrambled table text.** The decisions log records PDFs where text extraction scrambles tables (Kemira 2023 chart
   page, Sampo 2025 E1-6 row shift). The model copies from the same scrambled text, so checks (a)-(c) can pass on a
   value from the wrong row.
4. **Page finder recall.** With 4 pages, a missed table produces confident nulls with plausible reasons, and null
   reasons are not verified.
5. **Vintages and restatements.** A 2025 report restates 2024 (Outokumpu's Scope 2 location note). An evaluation must
   compare against the right vintage, or a correct extraction will look wrong.
6. **Scope 3 / financed emissions** (Nordea, Sampo) and **kt / Mt units** were not exercised by these three PDFs;
   unit conversion is tested only on made-up inputs.
7. **Repeatability.** Temperature cannot be set, so two runs may differ; at least one repeat run per PDF would show
   the agreement rate.
8. **Notes are free text** and can carry an unverified number or claim into the dataset. In this spike, Outokumpu's
   Scope 1 liner-ships note is supported by p48 and p49 but is a paraphrase stitched across two pages, and it omits
   the boundary change printed next to it (Tornio product transports were reported in Scope 3 in previous years): a
   note can be true and still drop the information that matters for comparability.

## Deviation: verified rows read during the dry run

During the dry run (7 Oct), before any extraction call, Claude read `data/bronze/emissions_raw.csv`, compared the
page finder's selected pages with the verified source pages, and searched the PDFs for verified Scope 1 values. This
broke the rule that verified data is held out from extraction work. Handling:
- the comparison scripts were deleted; the comparison is not reported as a result;
- nothing was tuned on it: the page cap stayed at 4 as first written, the scoring is unchanged;
- after the correction, `emissions_raw.csv`, `docs/verification_log.md`, `data/silver/` and verified values were
  not read again.

Exposure for these three PDFs: the comparison showed Claude the verified source page for Outokumpu 2025, Orion 2025
and Elisa 2025, and the verified **Outokumpu 2025 Scope 1 value**. Prompt, page finder and verifier were not changed
in response, but Outokumpu 2025 Scope 1 is not a blind check for anyone evaluating with Claude's help.

## Files

Repo, uncommitted:
- `.gitignore` (modified: ignores `data/extraction/raw_responses/`)
- `scripts/extraction/config.py`, `page_finder.py`, `extractor.py`, `verifier.py`, `test_verifier.py` (new)
- `docs/extraction_spike.md` (this report, new)

Repo, git-ignored:
- `data/extraction/raw_responses/spend_ledger.jsonl`
- `data/extraction/raw_responses/<run>/{meta.json, prompt.txt, response_raw.json, records.json, verification.json,
  verification_before_linebreak_fix.json}` for the three runs above

Outside the repo: side env `<venvs>\verigreen-extract`.

Rerun (side env python, `PYTHONDONTWRITEBYTECODE=1`):
```
scripts/extraction/test_verifier.py
scripts/extraction/extractor.py estimate
scripts/extraction/extractor.py run <outokumpu_2025|orion_2025|elisa_2025> --go
```
