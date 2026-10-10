# VeriGreen: Verified ESG Data for Quantum Portfolio Optimisation

> **Garbage in, quantum out.** A quantum computer won't fix bad data. It will just optimise it faster.

VeriGreen verifies ESG emissions data before it reaches a portfolio optimiser, classical or quantum.
Every number is traced to its source page, and the project measures which data errors actually change
a portfolio decision.

Built at the **Quantum × Finance Hackathon** (Hanken, Helsinki, 8–10 October 2026).
**No quantum advantage is claimed:** at 15 assets, classical methods find the exact optimum, and every
quantum result here is scored against it.

## What it does

1. **Hand-verified data.** Scope 1 and Scope 2 (location- and market-based) emissions for 15 Nasdaq
   Helsinki companies, 2023–2025, each value checked against the company's own report with source and page.
2. **Raw vs trusted.** 8 documented FY2024 errors (a base year republished as a recent year, a unit error,
   restatements, and financed emissions counted as a company's own) are re-run through the exact optimiser
   to see which ones matter.
3. **Portfolio optimisation as a QUBO.** Choose 6 of 15 assets, scored on risk, return, carbon and data trust.
   Brute force over all 5,005 portfolios gives the exact reference for classical baselines and QAOA (Qiskit).
4. **IQM hardware.** A 4-qubit residual problem (11 assets fixed by a classical relaxation) run on
   IQM Garnet and Emerald and compared with noiseless simulation.
5. **LLM extraction with a rule-based verifier.** An LLM proposes values from report PDFs; a value passes only
   if its quote appears word for word on the cited page and the number is in the quote. Flagged values go to a person.
6. **Streamlit app** showing every stage from committed data.

## Key results

| Area | Result |
|---|---|
| Raw vs trusted (main setting) | 6 of 8 errors left the portfolio unchanged (footprint off by about 4% at most). Nordea's financed-emissions error changed the selection (Nordea out, Nokia in). Sampo's more than doubled the reported footprint without changing the portfolio. |
| Classical baselines | Greedy swap search and simulated annealing found the exact optimum in 100 of 100 runs. |
| QAOA (simulator) | Standard QAOA: best selected restart 0.21% on the optimum; the median restart is below random feasible sampling (0.02%). Warm-start QAOA: best restart 28%, starting from a classical state that already gives 7.9%. |
| IQM hardware (p = 1, 1,000 shots) | 302 and 333 of 1,000 shots on the optimum, against 34.95% in noiseless simulation. Both output distributions differ from the ideal by more than shot noise (TVD against a 20,000-draw noise floor). Cause not isolated. |
| LLM extraction (run_001, 29 reports, about EUR 0.04) | 57 of 119 pairs in the scoring set matched the hand-verified figures (a count, not an accuracy rate); 33 more were adjudicated by hand; 29 could not be scored. In 10 adjudicated pairs a wrong-year value passed every check: the verifier does not see which year a column belongs to. |

Details and caveats: [`docs/quantum_results.md`](docs/quantum_results.md),
[`docs/hardware_iqm_notes.md`](docs/hardware_iqm_notes.md),
[`docs/verification_log.md`](docs/verification_log.md), [`docs/decisions_log.md`](docs/decisions_log.md).

## Layout

```
verigreen/          pipeline code: quality checks, QUBO, QAOA, classical baselines
scripts/            data fetch, extraction, extraction evaluation, IQM hardware runs
app/                Streamlit app (reads data/gold and data/silver only)
tests/              automated tests
templates/          empty CSV templates for data collection
data/bronze/        hand-collected inputs (emissions with source and page, financials)
data/silver/        cleaned data and quality flags
data/gold/          optimiser-ready inputs and results
data/hardware/      IQM job results (counts, circuit hashes, job IDs)
data/extraction_eval/  frozen LLM extraction run, verifier output, scoring, adjudication
docs/               verification log, decisions log, quantum and hardware results
```

## Run

Requires [uv](https://docs.astral.sh/uv/) (manages Python 3.12 and the virtual environment).

```
uv sync
uv run python -m pytest -q
uv run streamlit run app/streamlit_app.py
```

Not included in this repository, so the related scripts need your own copies:

- **Company report PDFs** (`data/raw_pdfs/`): download them from each company's investor relations pages.
- **Price data**: `scripts/fetch_market_data.py` downloads it from Yahoo Finance.
- **API keys**: copy `.env.example` to `.env` and set `OPENAI_API_KEY` (extraction) and `IQM_TOKEN`
  (hardware runs). The tests and the app need neither.
- `scripts/extraction_eval/build_adjudication_verdicts.py` reads a local adjudication pack that is not published.

`requirements.txt` is generated from `uv.lock`: `uv export --format requirements-txt --no-hashes > requirements.txt`.

## Data sources

- Emissions: companies' own annual and sustainability reports (source and page recorded per value).
  Five values come from aggregators (DitchCarbon, Tracenable) and are marked `third_party`.
- Financials and returns: derived from Yahoo Finance prices, reconciled against company reports where they disagreed.
- Quantum hardware: IQM Garnet and Emerald via IQM Resonance.
- Short quotations from company reports appear in the extraction outputs as citations.

## Team

- **Shah Rahman**: all development (data verification, QUBO and QAOA, IQM hardware runs, LLM extraction and verifier, app, tests).


## Licence

Code: MIT (see [`LICENSE`](LICENSE)). Hand-verified dataset (`data/bronze/emissions_raw.csv` and
derived tables): CC BY 4.0. Third-party figures and quotations remain under their sources' terms.
