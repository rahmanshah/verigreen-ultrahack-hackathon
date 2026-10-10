# Phase B scoring rules for run_001 (pre-registered)

Written and hashed BEFORE any verified data row was read. The hash is in `scoring_manifest.json`.
Any change after seeing the verified file's structure is logged in that manifest as
"changed before scoring, after seeing structure, before any comparison", with a new hash.
No rule changes after the scorer has run. The scorer runs once.

No API calls. run_001 is read-only. Output is counts with denominators ("N of M"). No percentages, no accuracy
figure, no "validated".

## Definitions
- **Key** = (company, year, scope). Year 2023-2025. Scope in `1`, `2_location`, `2_market`. A key exists where the
  verified file has a non-blank value in that cell (scope1 / scope2_location / scope2_market).
- **Report** = one PDF of run_001. **Pair** = (key, report). The unit of scoring is the pair, because the verified
  file has no source-report or vintage column (R7 fallback: report per report).
- **Spike PDFs** (not blind, R9): `Outokumpu_Sustainability_Statement_2025.pdf`,
  `orion-financial-statement-documents-2025.pdf`, `Elisa_AnnualReport_2025.pdf`. No others.
- **Candidate** = a record of the report with `mapped_year` = key year, matching scope, and a value that is present
  (`value_as_printed` is not null and not a placeholder). Placeholders: `-` and `n/a` (case-insensitive after the
  verifier's whitespace normalisation). Records with `mapped_year` null are never matched by guessing.
- **Passed** = verifier status `pass`. Only `pass` is what the pipeline would release. Verifier status `ambiguous` and
  `fail` are not passed. A `d_sanity` flag on a passed record is not a failure (shown as a column).

## R1 Ground truth and denominator
- Verified cells are classified by the row's `source_type` (trimmed, lower case):
  - primary printed values: `primary`, `primary_report`, `company_report`, `verified_pdf`, `annual_report`,
    `sustainability_report` (the last two added in change 1 below: in this file `source_type` names the report type)
  - `third_party`: excluded from ground truth, counted
  - derived: source_type `from_notes` / `derived`, OR (change 2 below) a non-third-party row whose `notes` field
    contains any of the literal tokens `from_notes`, `derived`, `calculated`, `computed` (case-insensitive substring;
    the token list is never widened; notes text is never printed): excluded, counted. A key whose only non-third-party cells are derived is
    `derived_not_extractable` and is outside the main denominator.
  - any other `source_type` is "unclassified": the scorer refuses to run until the rule is extended (and logged).
  - Classification is per row (all scope cells of a row share it). Order: third_party, then derived-by-notes, then
    source_type.
- N (main denominator) = keys with at least one primary cell. Counted and reported: verified rows (total, in
  2023-2025), non-blank cells per scope, keys per scope, third-party cells, derived cells,
  `derived_not_extractable` keys, `third_party_only` keys.
- A key with several primary rows has its distinct primary values (equal within 1e-6 relative difference are one
  value). More than one distinct value makes the key "multi-valued" (see R6).

## R2 Source coverage
A PDF could contain a key if the report's fiscal year equals the key year or the key year + 1. Key states, outside
the pair table:
- `no_source_pdf`: no PDF at all could contain the key (not an extraction failure).
- `spike_only`: the only PDFs that could contain it are spike PDFs. Reported in the spike rows.
- otherwise the key has >= 1 main (non-spike) pair.
`N = no_source_pdf + spike_only + keys with >= 1 main pair`.

## R3 Categories of a pair (mutually exclusive, checked in this order)
1. `not_extracted`: no candidate. Sub-reason, first that applies:
   `finder_no_pages` (run status `no_pages_found`) > `scope_null` (a record for that year and scope has a null value)
   > `placeholder_value` > `only_unmapped_labels` (the report has valued records of that scope with `mapped_year`
   null, none for the key year) > `no_record_for_key` (completed report, no record at all for the key).
   (`run_not_completed` for any other non-completed run status.)
2. `extracted_failed_verifier`: candidates exist and none passed.
3. `unit_ambiguous`: at least one passed candidate, none scorable (see R4), or the verified unit of the key is
   ambiguous.
4. `verified_match` (R5 tier exact or near), `ambiguous_extracted`, `ambiguous_verified` (R6), or
5. `verified_mismatch` (tier "other" only).
Sub-labels of `verified_mismatch` (they can overlap): `year_mapping_suspect` / `year_mapping_ambiguous` (R8),
`vintage_difference` (R7).

## R4 Units
- Both sides are converted to tonnes with the frozen `verifier.unit_factor` (unchanged).
- A unit is ambiguous and the candidate is not scored if it is missing, unrecognised by `unit_factor`, is `m t`, or
  contains "or as indicated". Units containing `ton`/`tons` without "metric" are `tons`-class: also not scored
  (short vs metric ton is not guessed). Known limitation, reported not changed: the frozen verifier reads `m t` as
  tonnes.
- If some passed candidates are not scorable, the rest are scored and the dropped number is a column. If none is
  scorable the pair is `unit_ambiguous` (reason recorded).
- **Sensitivity line (outside the main counts, declared here):** among main pairs that are `unit_ambiguous` only
  because all their passed candidates are `tons`-class (M of them, verified unit fine), "if read as tonnes, N of these
  M would match" = N pairs that would be a clean `verified_match` (exact / near split shown). Spike rows get the
  same line separately.

## R5 Match tiers (never merged)
Relative difference = |extracted - verified| / |verified| (verified = 0: only extracted = 0 is exact).
`exact` <= 1e-6, `near` <= 1%, `other` > 1%. `verified_match` = exact or near, always reported with the split.
A mismatch is `other` only.

## R6 Several candidates or several verified values
- Candidates agree if every pair differs by <= 1e-6 relative to the larger one. Equal values from different tables or
  pages agree.
- A candidate is compared with all distinct primary verified values (best tier counts).
- If no candidate matches (exact or near): `verified_mismatch` (column `multi_candidate` shows if they disagreed).
- If at least one matches but the scorable candidates disagree: `ambiguous_extracted`.
- Else, if the key has more than one distinct primary verified value: `ambiguous_verified`.
- Else `verified_match`.
- Neither ambiguous category is a clean match. If both situations apply, `ambiguous_extracted` is the category and
  `also_multi_valued` is set.

## R7 Vintage
There is no vintage column, so results are per report. `vintage_difference` is assigned automatically only to a main
`verified_mismatch` pair when another main report's pair for the same key is a `verified_match`. Other vintage and
restatement questions are left to adjudication. `source_url`, `source_page`, `notes` of the verified rows are copied
verbatim into the adjudication list and are not parsed.

## R8 Year mapping
For a candidate in tier "other" against the key year: if it is exact or near to a verified primary value of another
year (any year in the file) for the same company and scope, then
- `year_mapping_suspect` if that other-year verified value differs from the key-year verified value(s) (> 1e-6),
- `year_mapping_ambiguous` if they are equal.
Never counted as a match; the pair stays `verified_mismatch`. A candidate that matches the key year is never labelled.
Informational column `also_matches_other_year` for matches.

## R9 Spike PDFs
Scored with identical logic, reported in separate rows, excluded from main counts and from `vintage_difference`
comparisons.

## R10 Main result = passed records only
A second table covers records that did not pass (verifier `fail` / `ambiguous`, with a value): count per verifier
check and tier against the verified value (exact / near / other / not_comparable). It is labelled "not a pipeline
result".

## R11 Reporting
Counts with denominators only. By category; by company; by scope; spike rows separate; key roll-up (key with one
report / all covering reports in the same category / mixed). Among `verified_match` pairs: how many carry the harness
flag `assumed_thousands_separator`.

## R12 Records not scored (counted, not scored)
Every extracted record falls in exactly one bucket, first that applies: `unmapped` (`mapped_year` null, valued or
null), `year_outside_2023_2025`, `no_verified_key` (in range, no key with primary cells for that company, year,
scope), `outside_r2_window` (key exists but the report's fiscal year is not the key year or year + 1; candidates
counted, not scored), `in_pair_scope`.

## R13 Adjudication list
`adjudication_list.csv`: one row per scorable candidate of every pair that is `verified_mismatch`,
`ambiguous_extracted` or `ambiguous_verified`, or carries `year_mapping_suspect` / `year_mapping_ambiguous` /
`vintage_difference`. Columns: company, year, scope, category, labels, spike flag, report file and fiscal year,
extracted value as printed, unit, tonnes, verified value(s) in tonnes, verified unit, verified `source_url`,
`source_page`, `notes`, pdf page, quote, then empty `human_verdict` and `human_notes`. Allowed `human_verdict`
values: `extraction_wrong`, `our_verified_value_wrong`, `vintage_or_restatement`, `boundary_or_method`,
`year_column_wrong`, `unclear`. The scorer never fills them.

## Process guards
The scorer refuses to run if the rules file, the scorer or the run_001 manifest hash differs from
`scoring_manifest.json`, or if `results_by_key.csv` already exists (one run only).

## Change log (also in `scoring_manifest.json` -> `rule_change_log`)
Both entries: "changed before scoring, after seeing structure, before any comparison".
1. R1: `annual_report` and `sustainability_report` added to the primary source types (the file's `source_type` holds
   the report type: annual_report / sustainability_report / third_party).
2. R1: derived-by-notes rule (tokens above). Only the count of matching rows and of cells per scope is printed.
