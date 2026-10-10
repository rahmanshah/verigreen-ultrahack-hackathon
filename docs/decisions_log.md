# Decisions log

Judgment calls made when building derived datasets from `docs/verification_log.md` and
`data/bronze/*.csv` — things that aren't verification findings themselves, but choices about
how to use them. One entry per decision, newest first.

## 2026-10-06 — Stages G (reduced), H and H2: settings fixed before any run (`verigreen/stage_gh.py`)

Approved by Shah before any run. Simulator only (Aer), no hardware submission, no `qiskit-iqm`. Code:
`verigreen/stage_gh.py`, `scripts/report_stage_gh.py`. Outputs `data/gold/qaoa_stage_*.csv`, results in
`docs/quantum_results.md`. The raw-vs-trusted result comes from exact enumeration (G0) and the classical relaxation; QAOA is
shown reproducing it, and the docs say so.

**G (reduced).** Four cases, FY2024, practical penalty, warm start eps 0.1, p = 1 and 3, restarts 0-9 per (case, p)
(`restart_seed`, random initial points, no "extend" restart, so restarts 0-4 reuse the F2 seeds), selection rule = lowest
final expected energy as in F2.
- MAIN trusted; MAIN with the Nordea financed error; MAIN with the Sampo financed error (both `frozen_trusted_z`, trusted
  scales frozen, as in G0); TRUST (u) trusted alone (no naive data).
- Each case is scored against its own QUBO's exact optimum. That optimum is read from `raw_vs_trusted_exact_fy2024.csv` and
  asserted equal to a fresh brute-force run. The relaxation and the practical penalty (1.1 x P_gs) are recomputed per QUBO.
- Reported per (case, p): selected restart, median over the 10 restarts, how many of the 10 beat the p = 0 warm state
  (on P(opt), on within-5% mass given feasible, on mean r), and the most likely feasible portfolio (statevector and shots).
- "Selection result reproduced" = the selected restart's most likely feasible portfolio equals the case's exact optimum.
  For the financed cases that is the exact change (Nordea: Nokia in, Nordea out) or no change (Sampo, vs MAIN trusted).

**H (sizing, the 8-asset instance).** The assets with c* > 1e-6 in the MAIN relaxation, K = 6, the 15-asset coefficients with
frozen scales, so its objective values are those of the 15-asset problem; P* and P_gs are recomputed on the subset. A
classical pre-screen, labelled so everywhere. Baseline for p = 1 is **p = 0** (warm initial state, no entangling gates).
- Transpiled with qiskit optimization level 3 to the IQM-style native set {r, cz}, on all-to-all (no routing), a line and
  a 2 x 4 grid as stand-ins; 20 transpiler seeds because routing is stochastic; depth and two-qubit (cz) counts are
  reported as median (min-max). The real IQM topology replaces the stand-ins at the event.
- Simulated P(opt): warm start eps 0.1, practical penalty, p = 1, restarts 0-9, selected restart as above; exact
  (statevector) and 16,384 shots, noise-free. With 28 feasible portfolios the random baseline is 1/28 = 3.6%, so the
  bar for any gain is much higher than at 15 assets.

**H2 (optional, 20-minute timebox, illustrative).** Aer depolarising noise: two-qubit error on cz in {0, 0.5%, 1%, 2%},
single-qubit error on r ten times smaller; p = 0 and p = 1 with the noise-free selected parameters (not re-optimised under
noise); all-to-all and the 2 x 4 grid; 65,536 shots, seed 20261006; the transpile seed with the fewest cz out of 20.
Not IQM's real noise: no readout, relaxation or crosstalk error.

## 2026-10-06 — Stage H3: residual subproblem, settings fixed before any run (`verigreen/stage_gh.py`)

Requested by Shah after H and H2 were seen; 30-minute timebox. **Variable fixing from a classical relaxation, no advantage
claimed.** Simulator only.
- Fixed to 1: assets with MAIN relaxation weight c* >= 0.99 (Elisa, Nordea, Orion, Sampo). Fixed to 0: c* <= 1e-6 (the 7
  others). Undecided: the rest (Wartsila 0.91, KONE 0.54, Nokia 0.38, Kesko 0.17): a 4-qubit problem with K_res = 6 - 4 = 2, i.e.
  6 feasible portfolios, so the random baseline is 1/6 = 16.7%.
- Coefficients: the frozen 15-asset ones. The fixed assets' contributions are folded into the undecided assets' linear terms
  (h_res_i = h_i + sum over fixed-to-1 j of (J_ij + J_ji)); the constant is dropped (it shifts energies, not the ranking). The budget
  penalty is applied to the residual constraint sum(x_res) = 2. P* and P_gs are recomputed on the residual.
- Checks: the exact residual optimum plus the fixed assets equals the 15-asset optimum, with the same objective once the constant
  is added back; the relaxation re-solved on the residual equals the 15-asset c* on those four assets.
- Warm start eps 0.1, practical penalty, p = 0 (baseline) and p = 1, restarts 0-9, selected restart = lowest final expected
  energy, median over the 10. Sizing on all-to-all, a line and a 2 x 2 grid (stand-ins), native {r, cz}, 20 transpiler seeds. Noise
  sweep as in H2 (cz error 0 / 0.5 / 1 / 2%, single-qubit one tenth, 65,536 shots, seed 20261006, noise-free parameters).
- The doc states that p = 0 is a product state, classically equivalent to independent biased coin flips.

## 2026-10-06 — Stage H3 results: reporting calls (`docs/quantum_results.md`)

Settings as in the entry above, unchanged; one run, seconds (30-minute timebox). Calls made while reporting:
- **Framed as variable fixing from a classical relaxation**, with the 1/6 random baseline and the fact that 16 brute-force
  evaluations solve it. The doc says p = 0 is a product state, classically equivalent to four independent biased coin flips,
  and a test checks that coin flips reproduce its distribution.
- **"Within 5%" equals P(opt) here**, because only the optimum is within 5% of the 6-portfolio range (best-to-second gap 14.8%).
  Stated in the doc so the two columns are not read as independent evidence.
- **p = 1 vs p = 0 reported as in H**: P(opt) rises (25.1% to 34.9% selected, 30.7% median) through the feasible share, not
  through the choice among feasible portfolios; only 4 of 10 restarts beat p = 0 on P(opt) given feasible. One restart ends
  below the random feasible baseline.
- **Noise sweep**: p = 1 stays above p = 0 up to 2% two-qubit error at 12-17 cz, in contrast to H2 (56-70 cz). The doc gives the gate count
  as the likely reason and says it was not tested separately; nothing is extrapolated beyond 2%.

## 2026-10-06 — Stages G, H and H2 results: reporting calls (`docs/quantum_results.md`)

Settings were the ones in the entry above, unchanged; each stage ran once (G: 80 restarts, 5.6 minutes; H: seconds; H2: under
a minute, well within its 20-minute timebox). Calls made while reporting:
- **Reproduced is stated as inherited from the classical step.** In all four cases the rounded relaxation is the exact optimum
  and the p = 0 warm state's most likely feasible portfolio is already the optimum, so the doc says QAOA keeps and sharpens
  the result rather than finding it.
- **Medians and the failing restarts are reported next to the selected restart**, as requested: at p = 3 the median restart is
  below the median p = 1 restart in all four cases, and for TRUST (u) below its own p = 0 state. The selected restart is a good
  draw by the energy rule, which the doc says.
- **H baseline is p = 0.** The finding that p = 1 raises P(opt) only through the feasible share (P(opt) given feasible 45.1% vs
  45.4%) is reported as such. The 8-asset random baseline is 1/28 = 3.6%, so the bar is much higher than at 15 assets.
- **H2:** p = 1 does worse than p = 0 from about 1% two-qubit error. This is reported plainly and carried into the event plan (p = 0
  is the safe hardware baseline). The noise-free parameters were used under noise (no re-optimisation), and the
  transpile seed with the fewest cz was used for each circuit; both are stated as limits. Not IQM's real noise.
- The sizing stand-ins (line, 2 x 4 grid) and the native set {r, cz} are labelled as stand-ins; the real topology replaces them.

## 2026-10-06 — Stage F2 results: reporting calls (`docs/quantum_results.md`)

The settings were the ones fixed in the "Stages F / F2" entry, unchanged. F2 ran within its 90-minute timebox (22 minutes, all 228 restarts ok).
- **The baseline for warm-start QAOA is the p = 0 warm state, not random sampling.** Every warm-start restart beats random
  feasible sampling trivially, because the initial state already does (P(opt) 7.9% at eps 0.1, about 390x). The doc
  therefore reports "x p=0" and counts restarts that beat the p = 0 state. This baseline was pre-registered as a
  reference row; using it as the bar for the restart counts is a reporting call.
- The rounded relaxation is the exact optimum. This is said first in the F2 section, so the result is not read as QAOA
  finding the portfolio.
- Under the exact penalty, P(opt) rises mainly through the feasible share. This is reported as "feasibility, not
  quality", because within-5%-given-feasible and mean r do not improve on the p = 0 state.
- The relaxed optimum (c*) is penalty-independent (exact constraint), and a test asserts it.

## 2026-10-06 — Additional reliability run for F and F2 (requested after F results were seen)

**Not pre-registered**, and labelled that way everywhere (`stage = F_reliability` / `F2_reliability` in
`qaoa_runs_fy2024.csv`, summary in `qaoa_reliability_fy2024.csv`).
- 20 more random restarts with restart indices 10-29, so the seeds (`restart_seed(p, r)`) are disjoint from the
  pre-registered 0-5. Rows: practical p = 1, 2, 3 and exact p = 3. p = 1 has 25 restarts in total, because it has no
  "extend" restart.
- The headline rows are unchanged, because the selection rule still picks from restarts 0-5. The table adds what the
  same rule would pick from all restarts, and an oracle "best by P(opt)" that is not a usable result.
- F2 gets the same treatment: the same four rows and the same 20 seeds, for each eps, so F and F2 are paired seed by seed.
- "Beats random feasible sampling" = strictly above 1/5,005 on statevector P(opt), and strictly above 14/5,005 on
  within-5% mass given feasible.

## 2026-10-06 — Stage F results: reporting calls (`docs/quantum_results.md`)

Results and tables are in `docs/quantum_results.md`. The pre-registered settings were not changed after seeing results.
Calls made while reporting:
- **F did not fail** under the pre-registered rule: practical penalty, p = 3 beats both thresholds (P(opt) 0.21% vs
  0.020%, 8.0% within 5% given feasible vs 0.28%). So the 12/10-asset fallback is not run. This rests on 1 of 6
  restarts, and the doc says so.
- **The best sampled portfolio (metric b) is reported but called weak.** It is the optimum in every row, but a random
  feasible sample of the same size would contain it 55-82% of the time.
- COBYLA used its library defaults (rhobeg 1.0, tol none) and stopped after 27-76 evaluations, never at maxiter 300.
  Not tuned after the fact.
- Classical baselines evaluate f on feasible portfolios only, so the penalty choice does not affect them. The SA
  calibration swaps (1,000) are not counted in any run's budget.

## 2026-10-06 — Stages F / F2: QAOA settings fixed before any QAOA result (`verigreen/qaoa.py`)

Approved by Shah before any QAOA run on the real QUBO (one timing probe only: about 0.12 s per 15-qubit evaluation at
4,096 shots; its output energies were not looked at). Simulator only (Aer), FY2024, `MAIN_CONFIG`, main inputs from
`data/gold/qubo_inputs_fy2024.json`. Results go to `docs/quantum_results.md` and `data/gold/qaoa_*.csv`.

- **Two penalties.** Exact: P = 1.1 x P* (the stage D default, separates all 2^15 states). Practical: P = 1.1 x P_gs,
  where P_gs is the smallest P for which the global minimum over all 2^15 states is still the exact feasible optimum:
  P_gs = max_{d != 0} (F_min - m_d) / d^2 (same derivation as P*, with F_min in place of F_max). Above P_gs the ground
  state is right, but infeasible states may sit below poor feasible ones. P_gs / P* is reported.
- **Hamiltonian.** QUBO -> Ising with x_i = (1 - Z_i)/2, qubit i = asset i (sorted company_id). The operator is divided
  by its largest absolute Pauli coefficient so gamma is O(1); this rescales energies and reorders nothing.
- **Optimiser.** qiskit-algorithms `QAOA`, COBYLA maxiter 300, objective = mean energy of 4,096 shots (default
  aggregation). Per (p, penalty): 5 random restarts, initial beta and gamma uniform in [0, pi] from a seeded RNG; for
  p >= 2 one extra restart from the selected (p-1) parameters with zeros appended. Aer, transpiler and sampler seeds fixed.
- **Which restart is reported.** The one with the lowest final optimised expected energy (QAOA's own objective), never
  one chosen by knowledge of the exact optimum. Every restart, failed ones included, is kept in `qaoa_runs_fy2024.csv`.
- **Read-out.** Each optimised circuit is re-sampled with 16,384 shots (fixed seed) and also evaluated as an exact
  statevector, because the baselines (~0.02%) are close to the resolution of the shot sample.
- **Failure rule for 15 assets.** F fails if, at every p and both penalties, the feasible-conditional mass within 5% is
  <= 0.28% (random feasible baseline) and P(optimum) <= 1/5,005. Fallback only on Shah's go: 12 assets = drop Metso,
  Neste, Stora Enso (in no main-grid optimum); 10 = also drop the two remaining assets held least often in the main-grid
  optima; K stays 6; scales, P* and the exact optimum re-fitted per subset. This is a classical pre-screen and is said so.
- **Classical baselines** (same QUBO, feasible swap moves only, 100 seeded runs, budget 50,000 objective evaluations
  each): greedy best-improvement swap local search, restarted from a new random feasible portfolio at each local
  optimum; simulated annealing with one random swap per evaluation, geometric cooling from T0 to T0/1000 over the budget,
  T0 = std of swap deltas over 1,000 random swaps from random feasible portfolios (seeded). Reported: share of runs
  that hit the exact optimum, median evaluations to first hit.
- **F2 warm start.** Continuous relaxation of the original formula (full Sigma, not the QUBO's h + J form, whose
  off-diagonal J is indefinite), x in [0,1]^15, sum(x) = 6, SLSQP; convexity asserted (Sigma PSD; the budget penalty
  matrix 11' is PSD). Egger, Marecek and Woerner (2021): c clipped to [eps, 1 - eps] for eps = 0.1 and 0.25, initial
  state RY(theta_i) with theta_i = 2 arcsin(sqrt(c_i)), mixer RY(theta_i) RZ(-2 beta) RY(-theta_i) per qubit. Both
  penalties, same seeds and restarts. Classical-only reference rows: the rounded relaxation (top 6 of c*) and the warm
  initial state alone (p = 0).

## 2026-10-06 — Elisa 2025-07-29: `unconfirmed` review row, cross-ticker look at 2025-07-28..31

Resolves the open item in the returns entry below. `scripts/report_price_window.py` (read-only; returns from `adj_close`
in `prices_raw.parquet`, volume from the cached yfinance history; z = return / std over the 250 prior trading days).
No price changed, no check added, `prices_cleaned.parquet` not rebuilt (an `unconfirmed` row cannot change it).

| ticker | 07-28 | 07-29 | 07-30 | 07-31 | z on 07-29 / 07-30 | volume / 250-day median, 07-29 |
|---|---|---|---|---|---|---|
| KONE | -0.2% | **+29.6%** | **-24.1%** | +1.5% | +23.8 / -19.4 | 1.65 |
| Elisa | -1.2% | **+21.6%** | **-18.5%** | +0.8% | +18.9 / -16.2 | 2.13 |
| Wartsila | -0.8% | +5.8% | -4.5% | +0.8% | +2.7 / -2.1 | 0.70 |
| Nokia | -0.1% | -6.5% | +5.1% | -0.2% | -3.4 / +2.7 | 0.92 |
| Fortum | -1.1% | -6.0% | +2.9% | +0.1% | -3.9 / +1.9 | 1.36 |
| Stora Enso | -0.6% | -5.2% | +1.8% | -4.2% | -2.3 / +0.8 | 0.76 |
| Kesko | +0.2% | -4.0% | +3.3% | -0.7% | -2.8 / +2.3 | 1.02 |
| Sampo | -0.4% | -2.7% | +3.2% | +0.0% | -2.5 / +2.9 | 0.88 |
| other 7 | | within ±4.2% | | | \|z\| < 2.8 | |

- Only KONE and Elisa exceed |z| 4 in the window. No other ticker shows a round trip of that size.
- Wartsila has the same shape (up on 07-29, down on 07-30) at a normal size (|z| < 3). Several others moved the opposite
  way on the same two days (down 2.7-6.5%, then up), also within |z| < 4. This is recorded, not interpreted: without a
  second source it cannot be told apart from ordinary market moves.
- Volume is elevated for Elisa and KONE on 07-29 but comes from the same Yahoo feed, so it is not independent evidence.
- Review row added: `ELISA.HE, 2025-07-29, check_id = manual, unconfirmed, none`. The validator does not constrain
  `check_id`, and no check flagged Elisa (below the P02 25% threshold). `manual` = found by inspection; SCHEMA.md says so.
  KONE's row is unchanged.

## 2026-10-06 — Stage G0: raw vs trusted, exact optimum only (`verigreen/raw_vs_trusted.py`)

Same exact QUBO, FY2024, main window. Sigma, mu and u are always the trusted gold inputs; only the carbon intensity of the
affected companies changes. No QAOA. Output: `data/gold/raw_vs_trusted_exact_fy2024.csv`, 120 rows (10 cases x 3 carbon
conditions x 4 settings). Footprint metric everywhere: **equal-weight WACI** (mean tCO2e/EURm of the 6 held assets).
Reproduce: `uv run python scripts/report_raw_vs_trusted.py`. Tests: `uv run python tests/test_raw_vs_trusted.py`.

**Judgement calls.**
- Naive intensity = raw Scope 1 + raw market-based Scope 2 over the same trusted revenue. A blank raw field keeps the
  trusted value (same assumption as the 2026-10-05 table, which the test reproduces exactly). Financed rows:
  raw_combined_footprint / revenue replaces Scope 1 + 2.
- Cases: the 8 FY2024 rows individually, `all_naive` (all 8), `all_vintage` (the 6 pre_restatement / unit_error rows,
  no financed rows). In `all_naive`, Nordea and Sampo each have a financed row and a pre_restatement row; **the financed
  row wins** and the other is listed in `superseded_rows`, because a pipeline that took the headline total has no
  own-operations figure left to restate. So `all_naive` = Nordea and Sampo financed + Metso + Kesko + Kemira (+ Outokumpu,
  which changes nothing market-based).
- `raw_basis` per row: financed rows "AR2025 comparative, recalculated: a definition illustration, not what the 2024
  reports printed"; vintage rows say where the as-first-published figure is quoted; Sampo Scope 1 says it is derived from
  the stated delta. `verification_status` is carried through (Sampo Scope 1 stays `from_notes`). The loader raises if a
  trusted value in the naive file differs from the silver table.
- Settings: MAIN, TRUST (u), TRUST (u_high), LOW_PRESSURE (preregistered, see its entry below). Rank-based carbon with u_high was
  not a stage D input configuration; it is built here the same way for the trusted baseline and the naive run.
- Carbon conditions: **frozen_trusted_z** (main): ln(naive) z-scored with the trusted ln mean and std, trusted scales
  frozen, so the other 14 coefficients are bit-identical. **refit_naive**: z-score and scales re-fitted on the naive
  inputs. **rank_z**: naive ranks z-scored with the trusted rank mean and std, frozen rank scales; baseline = trusted
  rank-based optimum (for MAIN this is the Nokia portfolio, not the KONE one).
- "Regret" = true objective of the naive portfolio minus the trusted optimum, on trusted data, as % of the trusted
  feasible range. "Heavy emitter" = FY2024 market-based intensity >= 100 tCO2e/EURm (the upper of the two clusters).
- P* is recomputed for every naive QUBO; every one separates all 2^15 states.

**Which cases change the selection.** Only the two financed-emissions cases (and `all_naive`, which contains them), in
every condition. **The six vintage cases and `all_vintage` change no selection in any condition or setting** (asserted
by a test). Even the financed cases do not always move it: Sampo financed does not change MAIN, and neither changes
LOW_PRESSURE.

**Results, frozen_trusted_z** (refit_naive gives identical selections and numbers at all 40 points: the re-fit changes the
effective carbon weight by a factor of 0.90-1.08, which flips no selection):

| setting (trusted optimum, true WACI) | case | naive portfolio vs trusted | naive-reported WACI | true WACI of that portfolio | error | regret |
|---|---|---|---|---|---|---|
| MAIN (KONE portfolio, 4.77) | Nordea financed | -Nordea +Nokia | 5.30 | 5.30 | 0.0% | 6.9% |
| | Sampo financed | same | 9.86 | 4.77 | +106.8% | 0 |
| | all_naive | -Nordea +Nokia | 10.39 | 5.30 | +96.1% | 6.9% |
| | all_vintage | same | 4.56 | 4.77 | -4.3% | 0 |
| TRUST, u (Nokia portfolio, 3.78) | Nordea financed | -Nordea +Kesko | 4.80 | 4.80 | 0.0% | 3.7% |
| | Sampo financed | -Sampo +Kesko | 4.96 | 4.96 | 0.0% | 2.7% |
| | all_naive | -Nordea -Sampo +Kesko +UPM | 59.10 | 59.20 | -0.2% | 8.6% |
| | all_vintage | same | 3.57 | 3.78 | -5.5% | 0 |
| TRUST, u_high (UPM portfolio, 57.48) | Nordea financed | -Nordea +KONE | 59.00 | 59.00 | 0.0% | 6.9% |
| | Sampo financed | -Sampo +KONE | 59.17 | 59.17 | 0.0% | 5.1% |
| | all_naive | -Nordea -Sampo +KONE +Nokia | 59.70 | 59.70 | 0.0% | 12.7% |
| | all_vintage | same | 57.27 | 57.48 | -0.4% | 0 |
| LOW_PRESSURE (Kemira portfolio, 36.70) | Nordea financed | same | 309.82 | 36.70 | +744.1% | 0 |
| | Sampo financed | same | 41.80 | 36.70 | +13.9% | 0 |
| | Kemira restatement | same | 36.12 | 36.70 | -1.6% | 0 |
| | all_naive | same | 314.32 | 36.70 | +756.4% | 0 |
| | all_vintage | same | 35.91 | 36.70 | -2.2% | 0 |

Two patterns, stated plainly:
- When the financed error **changes** the selection, the naive pipeline drops the misreported asset, so its reported WACI
  is about right for what it holds (error 0 to -0.2%), but it holds a different, higher-carbon portfolio. Under TRUST (u),
  `all_naive` holds UPM, true WACI 59.2 vs 3.78 for the trusted optimum.
- When the financed error **does not change** the selection, the portfolio is right but its reported footprint is wrong:
  +14% to +744% across the 9 unchanged test portfolios (Sampo: +14% LOW_PRESSURE, +107% MAIN, +135% MAIN under rank_z;
  Nordea: +744% LOW_PRESSURE).

**Vintage cases: the reported-WACI error is small.** Individually: Nordea pre-restatement -4.1% (MAIN), -5.2% (TRUST, u),
-0.3% (TRUST, u_high), -0.5% (LOW_PRESSURE); Kemira -1.6% (LOW_PRESSURE only, the one setting that holds Kemira); Sampo
Scope 1 -0.0% to -0.3%; Metso, Kesko and Outokumpu 0.0% everywhere (not held in any trusted optimum, or no market-based
change). `all_vintage`: -4.3%, -5.5%, -0.4%, -2.2%. Under TRUST (u) the Nordea case and `all_vintage` are just over 5% in
percentage terms, but the absolute change is 0.20-0.21 tCO2e/EURm (at most 0.79 in LOW_PRESSURE). Why it is small: the
optimised portfolios are already low-carbon and hold almost none of the restated names. The only restated name held in
the MAIN and TRUST portfolios is Nordea, whose -78% is 1.2 tCO2e/EURm on one asset, i.e. 0.2 on the equal-weight
portfolio. The percentage reaches 5% only because the denominator (3.8) is small.

**rank_z** (sensitivity): same pattern. Vintage cases change nothing. Under MAIN, Nordea financed brings in Kemira
(-Nordea +Kemira, true WACI 37.24 vs 3.78, regret 7.2%), and Sampo financed leaves the portfolio unchanged but reported
+134.8%. `all_naive`: -Nordea +Kesko (MAIN), -Nordea -Sampo +Kesko +UPM (TRUST, u, true WACI 59.20), -Nordea -Sampo +Kesko
+Nokia (TRUST, u_high). LOW_PRESSURE: no change; reported errors as in the frozen condition.

**Benchmark** (equal-weight WACI of all 15 assets, trusted 87.33 tCO2e/EURm; independent of the optimiser): Nordea
financed +125.1% (196.57), Sampo financed +2.3% (89.37), `all_naive` +127.2% (198.38). Vintage cases -0.27% (Kemira) to
+0.05% (Metso), Outokumpu 0.0%, `all_vintage` -0.35%.

**Heavy emitters and LOW_PRESSURE.** The trusted LOW_PRESSURE optimum holds a heavy emitter: Kemira (Elisa, Kemira, Nordea,
Orion, Sampo, Wartsila). On the grid (main inputs, return weight 1, lambda_u 0), Kemira is held at lambda_carbon 0, 0.25 and
0.5, and no heavy emitter is held at 1 or above. Of the four heavy names in the request, only Kemira has an FY2024 naive
case that changes the market-based intensity. Outokumpu's is location-based only, and Stora Enso and UPM have no FY2024
naive row. So LOW_PRESSURE can only show the Kemira restatement (-1.6%), and it does.

## 2026-10-06 — Stage E: top-10 portfolios, random-sampling baseline, grid stability (`scripts/report_qubo.py`)

Exact enumeration only, computed from the reloaded gold JSON like the grid. `qubo_exact_fy2024.csv` is unchanged
(identical hash after the rerun). The JSON only gained `LOW_PRESSURE_CONFIG` under `qubo_configs`.

**Outputs.** `data/gold/exact_top10.csv`: 30 rows, the 10 best feasible portfolios for three blocks: MAIN on main inputs, TRUST
on main inputs (u), TRUST on u_high inputs. MAIN on u_high inputs is left out because it is identical to MAIN on main
(lambda_u = 0, and the other scales are identical). Columns: energy, gap to the optimum, gap as % of the feasible range
(F_max - F_min), equal-weight WACI, tier counts under u and u_high. `data/gold/exact_summary_fy2024.json`: the
random-sampling baseline and the stability summary below. "Within x" uses the same definition as stage D:
f - F_min <= x * (F_max - F_min).

**Top 10.**
- MAIN: rank 2 (KONE -> Nokia) is 0.51% of the range behind, rank 3 (KONE -> Kesko) 0.99%. Rank 4 swaps KONE for
  Kemira at 1.8% and has an equal-weight WACI of 36.7 vs 4.8.
- TRUST (u): rank 2 (Nokia -> Kesko) is 0.51% behind. Rank 4 is the u_high optimum (UPM in, WACI 57.5) at 2.7%.
- TRUST (u_high): the u optimum is rank 3 at 2.9%. The gap to rank 2 is 2.3%, larger than under u.

**Random-sampling baseline** (for stage F; uniform over the 5,005 feasible portfolios / over all 32,768 bitstrings):

| block | within 1% | within 5% | P(exact optimum) |
|---|---|---|---|
| MAIN, main | 3 = 0.060% / 0.0092% | 14 = 0.28% / 0.043% | 1/5,005 = 0.020% / 1/32,768 = 0.0031% |
| TRUST, main | 2 = 0.040% / 0.0061% | 8 = 0.16% / 0.024% | same |
| TRUST, u_high | 1 = 0.020% / 0.0031% | 6 = 0.12% / 0.018% | same |

**Grid stability** (from `qubo_exact_fy2024.csv`; swaps = assets in the optimum that are not in the main-inputs MAIN
optimum Elisa, KONE, Nordea, Orion, Sampo, Wartsila):

| inputs | points | in every optimum | in no optimum | grid points by number of swaps 0/1/2/3/4 |
|---|---|---|---|---|
| main | 60 | Elisa, Orion | Metso, Neste, Stora Enso | 1 / 22 / 24 / 5 / 8 |
| full_sample | 60 | Elisa, Orion | Kemira, Metso, Neste, Stora Enso | 0 / 26 / 23 / 5 / 6 |
| rank_carbon | 60 | Elisa, Orion | KONE, Neste, Stora Enso | 0 / 17 / 30 / 5 / 8 |
| u_high | 60 | Elisa, Orion | Metso, Neste, Stora Enso | 3 / 28 / 22 / 7 / 0 |
| all | 240 | Elisa, Orion | Neste, Stora Enso | 4 / 93 / 99 / 22 / 22 |

No grid optimum differs from the reference by more than 4 of 6 assets. Nordea and Sampo are not in every optimum: they
leave at high lambda_u.

## 2026-10-06 — Third headline setting for stage G: LOW_PRESSURE_CONFIG (`verigreen/qubo.py`)

Added by Shah **before any stage G result was computed**. At lambda_carbon = 1 the heavy emitters are already excluded,
so a data error in Kemira, Outokumpu, Stora Enso or UPM cannot reach the reported footprint of the optimised portfolio. A
weak-carbon setting tests whether it does when they can be held. Same model and scaling as the other two; the test reads
this line:

```
LOW_PRESSURE_CONFIG = return_weight 1, lambda_carbon 0.25, lambda_uncertainty 0, k 6
```

## 2026-10-06 — QUBO for choosing 6 of 15, FY2024 (`verigreen/qubo.py`, stage D)

**Model.** Binary selection of K = 6 of the 15 assets, held at equal weight 1/K; weights are not optimised. Solved here
only by exact brute force (all 2^15 states). No QAOA in this stage and no claim of quantum advantage: at 15 assets the
exact classical optimum takes well under a second.

**Inputs** (assets in sorted `company_id` order; the code raises if any input covers a different set):
- Sigma, mu: annualised (x252) covariance and mean of 1/99-winsorised daily simple returns. MAIN window 2022-04-01 to
  2025-03-31 (754 days, see the returns entry below). The full sample (2021-10-05 to 2026-10-02, 1,255 days) is a
  sensitivity only, because it uses returns after the decision date. Sample means are very noisy (Neste -38.7%/yr,
  Wartsila +24.1%/yr in MAIN), so every headline is also reported with mu = 0 (minimum variance).
- c: ln(market-based intensity), then z-score (population std), FY2024. The code raises unless all 15 rows have
  `boundary_match` true (they do), rather than silently dropping a company. Alternative: z-score of rank(intensity),
  average ties, which removes the gap between the 0.5-10.7 and 130-327 clusters.
- u from `data_trust` (main), u_high as the sensitivity.

**Scaling.** Raw terms R = x'Sigma x (= K^2 x the equal-weight portfolio variance), M = mu'x, C = c'x, U = u'x. Each is
divided by s_T, its population std over the 5,005 portfolios with exactly 6 assets, so every scaled term has std 1 across
feasible portfolios and **lambda = 1 means one portfolio-std of that term weighs as much as one portfolio-std of risk**.
A term that is constant on the feasible set gets s_T = 1. Fitted values:

| inputs | s_risk | s_return | s_carbon | s_uncertainty |
|---|---|---|---|---|
| main | 0.1914 | 0.2955 | 1.964 | 0.4559 |
| full_sample | 0.2061 | 0.1688 | 1.964 | 0.4559 |
| rank_carbon | 0.1914 | 0.2955 | 1.964 | 0.4559 |
| u_high | 0.1914 | 0.2955 | 1.964 | 0.3928 |

For a linear term s_T = popstd(v) x sqrt(K(N-K)/(N-1)), which is 1.964 for any z-scored vector, hence the same s_carbon for
log and rank. Consequence, stated honestly: after this scaling, multiplying c by a constant changes nothing, and the
z-score's centring only shifts every feasible portfolio by the same amount. So "z-score vs plain log" cannot change a
selection; the real alternative is **rank vs log**, which is what is tested.

**Objective** (return is the only minus sign; w_R = 1 fixed):
f(x) = w_R R/s_R - w_M M/s_M + lambda_c C/s_C + lambda_u U/s_U, and E(x) = f(x) + P (sum(x) - 6)^2. Expanded with
x_i^2 = x_i: h_i = w_R Sigma_ii/s_R - w_M mu_i/s_M + lambda_c c_i/s_C + lambda_u u_i/s_U + P(1 - 2K),
J_ij = 2 w_R Sigma_ij/s_R + 2P (i < j), constant P K^2. A test checks the QUBO energy against f computed directly on
random bitstrings (feasible and not, two penalties).

**Budget penalty.** Requirement: every 6-asset state has lower energy than every other state. With F_max = the worst
feasible f and m_d = the best f among states with sum(x) - 6 = d, the exact threshold is
P* = max over d != 0 of (F_max - m_d) / d^2 (any such state has E >= m_d + P d^2 > m_d + P* d^2 >= F_max when P > P*).
**P = 1.1 x P\*** (floor 0.1 if P* <= 0), recomputed for every configuration and grid point by enumerating all 2^15 states.
The tests assert the separation on all 2^15 states, and that it **fails at 0.99 x P\***, so P* is tight, not a loose
bound. P* for the headline settings is 11.2 to 14.7. `qubo_with_penalty(P)` swaps in a smaller practical penalty for
stage F; the default is unchanged.

**Frozen scales for stage G.** `fit_scales` and `apply_scales` are separate, so a naive-data condition can be scored with
the scales fitted on the trusted inputs. Otherwise an outlier (Nordea's financed-emissions intensity) would inflate
s_C and silently change what lambda_carbon means. Tested: frozen trusted scales on the trusted inputs reproduce the
re-fitted QUBO bit for bit, and a one-asset outlier then moves only that asset's coefficient. (Open for stage G: whether
the naive c is z-scored on its own mean and std or on the trusted ones. The second keeps the other 14 assets unchanged.)

**Lambda grids and headline settings.** The headline settings were **fixed by Shah before any grid result was
reported**; the full grid is a sensitivity only. (While planning, one scratch run computed the optimum at all weights =
1 to check magnitudes; it was not reported.) The test reads these lines and compares them with the constants in
`qubo.py`:

```
LAMBDA_CARBON_GRID = 0, 0.25, 0.5, 1, 2, 4
LAMBDA_UNCERTAINTY_GRID = 0, 0.25, 0.5, 1, 2
RETURN_WEIGHTS = 1, 0
MAIN_CONFIG = return_weight 1, lambda_carbon 1, lambda_uncertainty 0, k 6
TRUST_CONFIG = return_weight 1, lambda_carbon 1, lambda_uncertainty 1, k 6
```

Return weight 0 is the minimum-variance (mu = 0) variant of each setting.

**Gold exports** (committed, so stages F, G and the demo never need the git-ignored price files):
`data/gold/qubo_inputs_fy2024.json` holds the asset order, Sigma and mu for both windows, intensity, c (log_z and rank_z),
u and u_high, and per input configuration the fitted scales and P* for the four headline variants. These are derived
statistics only; no price is stored. `data/gold/qubo_exact_fy2024.csv` holds 240 rows (4 input configurations x 2 return
weights x 6 x 5 lambdas): the selection, tier counts under both u and u_high, unscaled term values, equal-weight
volatility, return and WACI, P*, P and the readiness statistics. `scripts/report_qubo.py` writes the JSON, reloads it, and
computes the CSV from the reloaded JSON. A test reproduces the headline optima from the JSON. Output is deterministic
(identical hashes on a rerun). Vol and return are in-sample statistics of the estimation window, not forecasts.

**Results, headline settings** (exact optimum; tiers = number selected with trust score 0 / 0.25 / 0.5 / 0.75):

| inputs | setting | selection | tiers in u | vol | return | WACI tCO2e/EURm |
|---|---|---|---|---|---|---|
| main | MAIN | Elisa, KONE, Nordea, Orion, Sampo, Wartsila | 1/2/2/1 | 13.2% | 12.7% | 4.8 |
| main | TRUST | Elisa, Nordea, **Nokia**, Orion, Sampo, Wartsila | 1/3/1/1 | 13.5% | 12.0% | 3.8 |
| main | MAIN, mu = 0 | Elisa, Kesko, Nordea, Nokia, Orion, Sampo | 1/3/1/1 | 12.3% | 7.2% | 3.8 |
| main | TRUST, mu = 0 | same as MAIN, mu = 0 | | | | |
| full_sample | MAIN | = main TRUST (KONE -> Nokia) | | | | 3.8 |
| rank_carbon | MAIN | = main TRUST (KONE -> Nokia) | | | | 3.8 |
| u_high | TRUST | Elisa, Nordea, Orion, Sampo, **UPM**, Wartsila | 2/2/1/1 | 13.1% | 11.6% | **57.5** |
| u_high | TRUST, mu = 0 | same as u_high TRUST | | | | 57.5 |

**QAOA readiness** (main inputs; report only). "Within 5%" is defined on the feasible range, f - F_min <= 5% of
(F_max - F_min), because the objective has an arbitrary constant offset, so a percentage of F_min itself means nothing.

| setting | F_max - F_min | P* | P | P / range | best-to-second gap | states within 5% |
|---|---|---|---|---|---|---|
| MAIN | 13.75 | 14.37 | 15.80 | 1.15 | 0.071 | 14 |
| TRUST | 12.72 | 13.95 | 15.35 | 1.21 | 0.065 | 8 |
| MAIN, mu = 0 | 10.71 | 11.37 | 12.50 | 1.17 | 0.067 | 6 |
| TRUST, mu = 0 | 10.35 | 11.72 | 12.90 | 1.25 | 0.180 | 11 |

**Reading.**
- The optimum is nearly degenerate: the gap between the best and second-best portfolio is 0.5-1.7% of the feasible
  range, and 6-14 portfolios sit within 5%. The strict all-states penalty is larger than the whole feasible range. For
  stage F this means: report the probability of sampling the exact optimum and an approximation ratio, not only the
  most likely bitstring. Try `qubo_with_penalty` with a smaller P next to the exact one.
- Elisa, Nordea, Orion and Sampo appear in all 16 headline rows (4 inputs x 4 settings). The swing slot between KONE and
  Nokia is a near-tie: it flips with the window, with rank-based carbon, and with lambda_u = 1.
- **TRUST vs MAIN** swaps KONE (u 0.5) for Nokia (u 0.25). It does not remove Sampo (u 0.75) or Nordea (u 0.5), because
  they are the lowest-carbon and lowest-volatility names. A trust penalty of the same weight as carbon trades off
  against them but does not override them.
- **u_high is the material sensitivity.** Under u_high, TRUST swaps Nokia (0.25 -> 0.5 in u_high) for UPM (0 in both,
  alone in the top tier in u_high), and the portfolio's WACI jumps from 3.8 to 57.5 because UPM has the highest intensity
  (327). Over the grid with lambda_u > 0, u and u_high give identical names at 22 of 48 points and the same tier
  composition (measured in u) at 30 of 48. So whether the ambiguous flags count changes the headline TRUST portfolio.
  This should be said whenever TRUST_CONFIG is shown.
- Other sensitivities: the full-sample window gives an identical selection at 33 of 60 grid points, rank-based carbon at
  46 of 60. Under the minimum-variance variant, MAIN and TRUST give the same portfolio on the main inputs (not on the
  full sample, where KONE and Nokia swap again).
- Nordea and Sampo, the two financed-emissions cases, are in every headline portfolio, so stage G's naive condition has
  something to move. That is an expectation, not yet a result.

Reproduce: `uv run python scripts/report_qubo.py`. Tests: `uv run python tests/test_qubo.py`.

## 2026-10-06 — Winsorised returns, estimation window, KONE covariance (`verigreen/returns.py`)

**Winsorisation.** Per-asset 1st/99th percentile clip of daily simple returns (`WINSOR_LOWER` / `WINSOR_UPPER`). Same
procedure and quantiles for all 15 assets, quantiles computed inside the estimation window (no look-ahead). No price file is
written: `prices_raw.parquet` is untouched (a test hashes it before and after), and `prices_cleaned.parquet` is read only.
Returns are built from `adj_close_cleaned`, which equals `adj_close` for KONE because its review is still `unconfirmed`.
Percentile winsorisation is not idempotent (clipped values shift the next pass's quantiles), so it is applied once.

**Estimation window = decision-date convention, not a backtest.** MAIN window: the 3 years of daily returns ending
**2025-03-31** (`DECISION_DATE`, when the FY2024 reports were first published), i.e. 2022-04-01 to 2025-03-31, 754 return
days. The optimiser is run as if on that date; no return after it is used. The full sample (2021-10-05 to 2026-10-02,
1,255 days) is a sensitivity only. Winsorisation is applied in both. Covariances are annualised (x252).

**KONE with and without the 2025-07-29 point.** "Without" removes both returns built from that one price (07-29: +29.6%,
07-30: -24.1%), for all assets so dates stay aligned. The KONE row is identical if only KONE's two returns are masked,
because pairwise-complete covariance drops those days for every pair with KONE.

| KONE annualised | raw | point excluded | winsorised |
|---|---|---|---|
| MAIN window, variance (vol) | 0.0584 (24.2%) | 0.0584 (24.2%), identical | 0.0512 (22.6%) |
| FULL sample, variance (vol) | 0.0852 (29.2%) | 0.0561 (23.7%) | 0.0497 (22.3%) |

- **The MAIN window never contains the point**: 2025-07-29 is four months after `DECISION_DATE`. So under the main
  convention the unconfirmed tick cannot affect the optimiser, and the raw and "excluded" columns are identical. Winsorising
  still lowers KONE's covariances in MAIN by 1.9% to 12.7% across the 14 other assets (ordinary tail days, not the anomaly).
- **In the FULL sample the point matters a lot.** KONE's covariance with the other assets changes when it is excluded by:
  Elisa -71.7%, Wartsila -14.9%, UPM -13.4%, Outokumpu -3.4%, Nordea +2.2%, Metso +5.6%, Neste +11.6%, Kemira +14.2%,
  Stora Enso +19.6%, Orion +29.5%, Kesko +29.6%, Sampo +32.5%, Fortum +45.8%, Nokia +64.1%. The sign mostly goes up because
  KONE rose 30% on a day most other stocks fell (Fortum -6.0%, Nokia -6.5%, Stora Enso -5.2%), which drags the raw
  covariance down.
- KONE's status is unchanged: `unconfirmed`, no treatment, no price edited.

**New finding: Elisa shows the same round trip on the same two days** (+21.6% on 2025-07-29, -18.5% on 2025-07-30; adj close
42.69 -> 51.90 -> 42.30). It was never flagged because it is below the P02 spike threshold (25%) and has no row in
`price_anomaly_reviews.csv`. Two unrelated tickers with the same shape on the same dates makes a feed or aggregator artefact
more likely than a KONE-specific bad tick, but this is still circumstantial: no second source was obtained, so nothing was
treated and nothing was added to the reviews table (an `unconfirmed` row was added later the same day, see the Elisa entry above). The Elisa-KONE covariance in the full sample (-71.7% above) is mostly
this shared artefact. Open item for you to decide: add an `unconfirmed` review row for Elisa 2025-07-29, and consider a
cross-asset same-day check. It does not touch the MAIN window.

**Winsorisation cut-off sensitivity (0.5/99.5 vs the approved 1/99).** It exceeds your 5% threshold, so it is reported:
34 of 225 unique covariance entries differ by more than 5% in MAIN (largest: Orion x Outokumpu 40.3%, Fortum x Orion 25.0%,
Kemira variance 22.5%; these are small covariances, so relative changes are large), and 53 of 225 in FULL (largest
KONE x Sampo 14.2%). KONE's own row moves at most 9.3% in MAIN. The approved 1/99 stays the default; stages D and G can test
whether a selection depends on it. Reproduce with `uv run python scripts/report_kone_covariance.py`.

## 2026-10-06 — Data-trust score u, FY2024 (`data_trust_inputs.csv`, `verigreen/data_trust.py`)

**What u means.** A revision-risk / comparability score: how likely the FY2024 Scope 1+2 figure is to be revised or to be
not like-for-like with adjacent years, from documented verification evidence. It is not a judgement of the company's
honesty. **Companies that disclosed restatements transparently score higher by construction**, because the disclosure is
what makes the restatement visible. u = 0 means no documented revision risk was found, not that the number is known to be
right (UPM, u = 0, still has the mislabelled-row template error and a Scope 1 that excludes mobile combustion; those are
not among the scored flags).

**Scoring.** Four scored flags with equal weights (0.25 each): `restated`, `boundary_or_methodology_break`,
`partly_estimated`, `revenue_boundary_mismatch`. `single_source` is kept as a column but has **weight 0** (informational):
it is true for 13 of 15 because we hold one primary document per company-year, so it describes our dataset, not the company,
and scoring it would give UPM the same u as Elisa (a documented methodology break). Flag definitions are in the module
docstring. All flags are about the FY2024 Scope 1 and **market-based** Scope 2 values, the inputs to the 2024 carbon
intensity, so Outokumpu's location-only restatement does not set `restated`.

**Two scores.** `u` treats every ambiguous flag as false; `u_high` treats every ambiguous flag as true (upper bound, for the
sensitivity tests in stages D and G). Ambiguity is stored in the evidence column (`flag::ambiguous::reason`), not in a
separate column, so there is one source of truth.

**Evidence and its test.** Every true flag cites file + section heading + a short verbatim quote (no line numbers). A test
checks that each quote still appears in the cited file under the cited section, so editing a log breaks the build instead of
silently orphaning a citation. `single_source` cites the row's `source_url` in `emissions_raw.csv`, and a test checks the flag
equals "no third-party row for that company-year". `revenue_boundary_mismatch` is false for all 15 (FY2024 is 15/15
`boundary_match` true, see the optimisation-year entry), so it adds nothing for FY2024 but keeps the schema usable for
other years.

**Ambiguities resolved from the PDFs** (15-minute timebox; findings added to `verification_log.md` with page and quote):

| Case | Result | Basis |
|---|---|---|
| KONE `partly_estimated` | **true** | Sustainability Statement 2025 printed p.60, Table 18 footnote on a chart that plots 2023, 2024 and 2025: remaining emissions "are extrapolated to cover 100% of KONE's operations". |
| Metso `partly_estimated` | **true** | Annual report 2025 PDF p.95: estimate for excluded locations "added into reported emissions", "for all the reporting years". |
| Sampo `boundary_or_methodology_break` | **true** | Board report 2025 p.84: Scope 1 and 2 for 2022-2024 "recalculated following the merger of If and Topdanmark" with a common methodology. The held 2023 row is pre-integration. |
| Kesko `boundary_or_methodology_break` | **left ambiguous** | Annual report 2025 (PDF p.125) describes the 2024 recalculation as adding missing information and correcting errors; no method change between 2023 and 2024 is stated. |

Still ambiguous (false in `u`): Kesko break, Nokia `partly_estimated` (fallback factor for market-based cooling), Orion
`partly_estimated` (climate metrics not externally validated is an assurance gap, not an estimate), Outokumpu `restated`
(location-based only), Stora Enso `restated` ("revised", no size documented).

**Result** (tie-aware ranks, 1 = most trusted):

| u | Companies (u -> u_high) |
|---|---|
| 0.00 | UPM; Orion, Outokumpu (both -> 0.25) |
| 0.25 | Elisa, Fortum, Neste, Wartsila; Kesko, Nokia, Stora Enso (each -> 0.50) |
| 0.50 | Kemira, KONE, Nordea |
| 0.75 | Metso, Sampo |

How the ranking differs: u has four tiers (3 / 7 / 3 / 2 companies), u_high has four tiers (1 / 6 / 6 / 2). Only five
companies change tier, each by one step: Orion and Outokumpu leave the top tier; Kesko, Nokia and Stora Enso move into the
tier of Kemira, KONE and Nordea. UPM is alone at the top and Metso and Sampo are at the bottom in both; Spearman correlation
between the two scores is 0.83. Because ties are heavy, any selection test should compare against tiers, not fine rank
order.

**What is not scored here.** Financed-emissions confusion (Nordea, Sampo), mislabelled rows (UPM, Orion, KONE footnote) and
Scope 2 method gaps are raw-vs-trusted or pipeline cases, not revision-risk flags: the trusted FY2024 own-operations value is
clean in those cases.

## 2026-10-05 — Optimisation year: 2024

**Decision: FY2024** is the year for the optimiser run and the raw-vs-trusted demo. The recommendation was confirmed
by the counts below, not just accepted.

**Documented naive errors per year** (`emissions_naive_vs_trusted.csv`, 12 rows):

| Year | Rows | Companies | verified_pdf | Categories |
|---|---|---|---|---|
| 2023 | 2 | 2 | 2 | Outokumpu aggregator error; Kemira pre-restatement |
| **2024** | **8** | **6** | 7 (+1 from_notes) | Metso unit error; Kesko, Kemira, Outokumpu (location), Sampo Scope 1, Nordea pre-restatement; Sampo and Nordea financed emissions |
| 2025 | 2 | 2 | 2 | Sampo and Nordea financed emissions |

**`boundary_match` (carbon_intensity.csv, 15 companies per year):** 2023 = 12 true + **3 unknown** (Fortum, Metso,
Sampo; Sampo 2023 revenue is also blank, so 14 of 15 market-based intensities exist); 2024 = **15 true**, 15 of 15
market-based intensities; 2025 = 15 true, 15 of 15. Metso 2023 is also the second-basis row (see the Metso entry), so
2023 is excluded.

**Why not 2025:** boundary and completeness are as good, but the only documented errors are the two
financed-emissions cases, and 2024 contains those too (Sampo 5,697%, Nordea 108,054%, rows added today), so choosing
2024 loses nothing and adds six more real restatement cases. Argument against 2024 that was considered: the trusted 2024
values are the restated AR2025 comparatives (the latest vintage, which the data rules prefer), and the naive values
in the pre-restatement and unit-error rows are what the 2024 reports printed, so those errors are vintage errors, not
data-entry errors (the financed-emissions rows are a definition error). That is the point of the demo, but it should be
said that way, not as "bad data".

Outokumpu's aggregator error is a **2023** case and stays a pipeline example (source-checking, not an
optimiser case).

**Effect on market-based Scope 1+2 carbon intensity, FY2024 cases** (naive vs trusted, same revenue; where the raw
row leaves a field blank the trusted value is held, which is an assumption only used here, not stored in the data):

| Case | Naive vs trusted | Intensity tCO2e/EURm | Rank of 15 (1 = lowest) | Can it move a portfolio? |
|---|---|---|---|---|
| Nordea financed emissions | +108,054% | 1.5 -> 1,640 | 3 -> 15 | **Yes.** Greenest cluster to by far the worst (5x the next); the asset drops out. |
| Sampo financed emissions | +5,697% | 0.5 -> 31.1 | 1 -> 9 | **Yes.** Rank 1 to mid-table, above the whole low cluster (<=10.7). |
| Nordea pre-restatement | -77.9% | 1.5 -> 0.3 | 3 -> 1 | Marginally. Large percentage, but 1.2 tCO2e/EURm in absolute terms inside the greenest cluster (0.5-1.5); it only reorders three near-zero names. |
| Metso unit error | +8.8% | 7.5 -> 8.2 | 6 -> 8 | Marginally. Reorders within the 7.1-7.7 cluster of Orion, Metso, Kesko, Wartsila. |
| Kesko restatement | -7.2% | 7.6 -> 7.1 | 7 -> 5 | Marginally, same cluster. |
| Sampo Scope 1 (882) | -10.5% (S2 held) | 0.5 -> 0.5 | 1 -> 1 | No (0.05 tCO2e/EURm). from_notes. |
| Kemira Scope 2 market | -1.7% (S1 held) | 202.3 -> 198.7 | 12 -> 12 | No. Documentation only. |
| Outokumpu location-based | 0.0% | 228.1 -> 228.1 | 13 -> 13 | No: only location-based Scope 2 changed; the market-based intensity is unaffected. |

Reading: 2024 intensities are bimodal (nine assets at 0.5-10.7, six at 130-327; median 7.7), so a 7-10% error matters
only among the near-tied assets of the low cluster. Only the two financed-emissions errors change which assets a
penalty-based optimiser would hold. The demo-grade cases are therefore **Nordea and Sampo financed emissions**, with
Metso/Kesko as honest small-effect restatements, and **Nordea's -78% should not be presented as a portfolio mover**
(correcting an earlier assumption in the internal project notes that it was a demo-grade case).

## 2026-10-05 — FY2024 first-published vs restated rows (`emissions_naive_vs_trusted.csv`, 6 -> 12 rows)

Rule applied (per instruction): a restatement note in a later report that quotes the original figure counts as
`verified_pdf` (cite report and page); `from_notes` only when the number appears nowhere on disk; nothing derived
into a cell except where labelled. Page convention for the new and corrected cites: printed page, with the PDF page
added where the two differ (Nordea: printed = PDF - 1; Sampo, Kesko, Kemira: equal).

| Row | Status | Basis |
|---|---|---|
| KESKOB.HE 2024 pre_restatement | verified_pdf | AR2025 p.130 "Bridge calculation": columns *Reported 2024* (as published in the 2024 statement) vs *Restated 2024*: 56,637 / 42,950 / 27,939 -> 59,750 / 43,167 / 31,385. Headers read first, as instructed. The "reported" column is the original. |
| KEMIRA.HE 2024 pre_restatement | verified_pdf | AR2025 p.104 table *Restated value | Reported value | Change*: market-based Scope 2 2024 reported 467,561, restated 477,937. Only that cell is stated, so raw Scope 1 and location-based are **blank**, not assumed equal. |
| OUT1V.HE 2024 pre_restatement | verified_pdf | Sustainability Statement 2025 footnote 4 (PDF p.48): location-based Scope 2 "changed from 540,274 tCO2 to 448,567 tCO2" (new emission factors). Location-based only. |
| SAMPO.HE 2024 pre_restatement | **from_notes** | AR2025 p.84 gives only the deltas (Scope 1 +530, location +710, market +88), not the originals. 882 is therefore **derived from the stated +530 delta** (1,412 - 530) and matches the `emissions_raw.csv` note; it is printed in no PDF on disk. Scope 2 originals would also be derived, so left blank (same decision as 2026-09-26). |
| SAMPO.HE 2024 financed_emissions | verified_pdf | AR2025 E1-6 table p.86 (columns base 2022 / 2024 / 2025), category 15 "Investments" 2024 = 293,860. The 2024 column was recalculated in AR2025, so it is the AR2025 comparative. |
| NDA-FI.HE 2024 financed_emissions | verified_pdf | AR2025 table p.137 (PDF p.138), "Total GHG emissions (location-based)" 2024 = 19,846,338 t (market-based 19,846,099; cat 15 lending + investment 19,805,621). Same definition as the existing Nordea 2025 row (portfolios + own operations). Also an AR2025 comparative (lending 2024 recalculated). |

Nordea 2024 `pre_restatement` already existed and was not duplicated. Not added, because the original is not quoted
anywhere on disk or in the notes: KONE 2024 market-based Scope 2 ("restated with new emission factors"), Stora Enso,
Wartsila (boundary changes). The validator now also rejects two rows with the same company, year and category;
Nordea and Sampo 2024 each have two rows on purpose (different categories).

**Upgrades and corrections to the existing 5 rows, found while reading these tables:**
- Kemira 2023 `from_notes` -> `verified_pdf`. The AR2023 page (p.63) that `pdftotext` scrambles reads cleanly with
  word-level extraction (PyMuPDF): *GHG emissions (kt CO2e) from manufacturing sites*, columns 2023 | 2022 | 2021:
  Scope 1 137, Scope 2 market 488, location 643. This replaces the 2026-09-26 statement that it could not be
  re-derived.
- Sampo 2025 `from_notes` -> `verified_pdf`, with the column alignment confirmed by word coordinates (2025 column,
  category 15 = 388,417) and the report's own statement that category 15 is financed emissions. **Page corrected
  from p.85 to p.86** (the 2026-09-26 row cited the wrong page).
- Nordea 2024 / 2025 cites made unambiguous (printed p.137 = PDF p.138; the 19.8 Mt narrative is printed p.111).
  Values unchanged.

## 2026-10-05 — Metso: unit_error row, second 2023 row, `verification_status`

**Source check.** `data/raw_pdfs/metso-financial-review-2024.pdf` has md5 `d8679bad4d8aa069929bb522de4df8a3`,
158 pages (confirmed with PyMuPDF; an earlier "159" came from counting a trailing form feed), i.e. the same document
as the reviewer's copy. The E1-6 table is on **printed page 39** (= PDF page 39; the footer reads "Financial review
2024 39"). Column order is 2024 | 2023 | 2019. Every number quoted below was read from the PDF, not from the
request: 2024 original 37,670 / 75,652 / 3,308; 2023 gross 36,912 / 76,956 / 3,229. The AR2025 table (p.94, same
printed page) marks the restated 2024 values with `*`, and its footnote gives the reasons.

**`unit_error` row** added to `emissions_naive_vs_trusted.csv` (Metso 2024, original vs the restated values already in
`emissions_raw.csv`). The unit error is attributed to **Scope 1 only**, because that is all the footnote attributes to
it ("For Scope 1, the difference was due to the wrong energy unit used by one site"). The Scope 2 restatement
(75,652 -> 77,789 location; 3,308 -> 4,412 market) has **no specific reason stated** (the footnote gives only the
generic "internal validation and changes in methodology"), so the row says so rather than assigning one. The Scope 3
effect is recorded as a separate, method-change item: total location-based GHG 4,125,322 t (AR2024 p.39) vs
62,563,203 t (AR2025 p.94); 4,125,322 + 58,437,881 (the footnote's stated increase) = 62,563,203, which cross-checks.
Size of the naive error: Scope 1 +13.3%, Scope 1 + market Scope 2 +8.8%.

**Second Metso 2023 row** added to `emissions_raw.csv` from the same table (gross, ESRS, CO2e), tagged
`source_type=annual_report`; the GRI-supplement row is kept. Selection logic deliberately **not** changed: silver keeps
the GRI row for 2023 because `sustainability_report` outranks `annual_report`, and a new E05 flag appears on Metso 2023
(Scope 1 differs by 22%), which is genuine (two accounting bases for one year), so it stays. Silver uses the GRI row for
2023 only because of source-type ranking; the AR2024 row is the more comparable (gross, ESRS) basis; do not use Metso
2023 for any trend or optimisation. Counts changed accordingly: 58 -> 59 rows, 6 -> 7 flags (the internal project notes,
an internal Q&A note, `docs/verification_log.md` updated).

**`verification_status` column** added to `emissions_naive_vs_trusted.csv` (`verified_pdf` / `from_notes`), with a
validator (`verigreen/naive_vs_trusted.py`) that also checks every trusted value equals a real `emissions_raw.csv` row.
Existing rows backfilled: Outokumpu 2023, Nordea 2024 and Nordea 2025 `verified_pdf`; Kemira 2023 and Sampo 2025
`from_notes` at the time; both were upgraded to `verified_pdf` later the same day (see the entry above).

## 2026-10-02 (follow-up) — KONE anomaly, boundary_match, automated revenue verification

Four follow-up items after the entry below, same day.

**KONE price anomaly (2025-07-29)**: tried to independently confirm the P02 flag
(+30%/-24% single-day round trip) against a second source. Found strong circumstantial
evidence of a bad tick (no split/dividend recorded; KONE's Q2 2025 results were released
2025-07-18, 11 days before the anomaly, so not an earnings reaction; no news of a halt or
correction; immediate full reversion the next day) but could **not** obtain an independent
source's exact closing price for that specific date — Stooq's and Nasdaq Nordic's data-export
endpoints are unreachable from this environment (404s), and other sites only expose a rolling
recent window via static fetch. Per instruction, **did not treat the value**:
`prices_raw.parquet` is untouched, and the new `data/bronze/prices_cleaned.parquet` leaves
this point exactly as reported, flagged `unconfirmed`. Built `verigreen/price_cleaning.py` and
`data/bronze/price_anomaly_reviews.csv` as reusable infrastructure for this and future
flagged-but-unconfirmed anomalies, rather than a one-off hack: a review only changes
`adj_close_cleaned` when its `status` is explicitly `confirmed_bad_tick`, never for
`unconfirmed` or `real_event`, regardless of what `treatment` says.

**`boundary_match` column**: added to `carbon_intensity.csv` via a small exception table,
`data/bronze/revenue_boundary_reviews.csv` (company_id, fiscal_year, boundary_match, reason),
rather than requiring an explicit row for all 45 company-years — defaults to `true`, with only
the 3 genuinely unresolved cases (Fortum 2023, Metso 2023, Sampo 2023) listed. Chose to mark
**Metso 2024/2025 as `true`** (not `unknown` like 2023) specifically because both their
revenue and emissions come from the same current document (Metso Annual Report 2025) — a
reasoned, evidence-based distinction from 2023 (sourced from a separate GRI supplement), not a
blanket assumption. **Nokia 2023 is `true`**: the earlier override (using the
as-originally-reported EUR 22,258m, Nokia Annual Report 2023 p.77, instead of yfinance's
continuing-operations-restated EUR 21,138m) was specifically chosen to achieve this match, so
recording anything else would contradict the reason that override was made.

**`scripts/verify_financials.py`**: classifies every `financials_raw.csv` row as `yfinance`
(source_url itself is the yfinance pull), `primary_report` (a primary source agreeing with
cached yfinance within 2%), or `override` (a primary source disagreeing by >2%, with the word
"override" in its notes) — and **fails loudly**, writing nothing, if a >2% disagreement has no
such documented justification. This caught a real gap: the Nokia 2023 note originally said
"overriding yfinance" (present tense, no exact substring match for "override") and the Sampo
2024 note didn't contain the word at all despite being a deliberate 2.6% departure — both were
reworded to include the literal word "OVERRIDE" so the check passes on its merits, not by
loosening the check's string-matching. The script reads `data/bronze/yfinance_cache/` directly
(not `financials_yfinance_firstpass.csv`) so verification doesn't depend on that file staying
in sync.

## 2026-10-02 — revenue, prices, carbon intensity (`financials_raw.csv`, `prices_raw.parquet`, `data/silver/carbon_intensity.csv`)

Per the internal project notes next-steps 1-2. Full detail and per-row sourcing is in `data/bronze/financials_raw.csv`'s
`notes` column and `docs/market_data_report.md`; this entry records the judgment calls behind it.

**Revenue definition for financial companies**: generic yfinance "Total Revenue" is a
Yahoo-normalized figure that doesn't match what banks/insurers report as their own top line.
Used **Nordea's "Total operating income"** (Annual Report 2025 p.136) instead — validated by
Nordea's own report stating this exact figure is the denominator for its own GHG intensity
metric. Used **Sampo's "Insurance revenue"** (Group IFRS statement of profit and other
comprehensive income, p.138, gross of reinsurance) instead of yfinance's generic figure, which
is a materially different and larger concept (confirmed: Sampo 2024, yfinance EUR 9,203m vs.
report EUR 9,450m, a 2.6% gap entirely explained by definition, not error). Sampo 2023 was left
**blank** rather than falling back to yfinance for that one year only, since mixing metrics
across years for the same company would fabricate a false intensity trend; no primary-source
figure for 2023 was available in `data/raw_pdfs`.

**Revenue vs. emissions boundary matching**, for the four companies flagged with portfolio
changes:
- **Kemira**: used Kemira's own as-reported revenue (not its separately-disclosed "O&G
  divestment adjusted" series), because the as-reported figure still includes Oil & Gas through
  its actual divestment date (2 Feb 2024) — matching the emissions data's boundary, which does
  the same.
- **Fortum**: 2024/2025 revenue verified exact match to the primary source, continuing
  operations (excludes recycling & waste, divested Nov 2024) — same boundary Fortum itself uses
  for its own GHG intensity metric. 2023 could not be verified or boundary-matched (no 2023/2024
  Fortum annual report available locally); left as yfinance's figure with an explicit caution
  flag rather than silently assuming it matches.
- **Nokia**: 2023 **overrides** yfinance. yfinance backfills historical revenue to Nokia's
  current continuing-operations classification (EUR 21,138m, excludes Submarine Networks,
  reclassified as discontinued in June 2024) — confirmed by exact reconciliation
  (22,258 − 1,120 = 21,138, where 1,120 is Submarine Networks' actual 2023 net sales). Used the
  as-originally-reported total instead (EUR 22,258m, from Nokia's own 2023 annual report)
  because `emissions_raw.csv`'s Nokia 2023 Scope 1 figure explicitly includes the Submarine
  Networks marine fleet. 2024/2025 needed no override — both yfinance and the emissions data
  already exclude Submarine Networks (2024) and include Infinera (2025) consistently.
- **Metso**: revenue confirmed continuing-operations in both the 2023 and 2025 annual reports
  (two rounds of business discontinuations: Sep 2023 and a further one in 2025), matching
  yfinance exactly for all three years. Left **unresolved** whether `emissions_raw.csv`'s Metso
  2022/2023 Scope 1/2 figures (sourced from a separate GRI supplement, not these financial
  statements) share the same continuing-operations boundary — not confirmed either way.

**Price series**: used `auto_adjust=False` and the explicit "Adj Close" column, not the newer
yfinance default (`auto_adjust=True`, adjustment folded into "Close"), so the
adjusted-for-splits-and-dividends series has its own unambiguous name matching what
`check_prices` expects as `adj_close`.

**Carbon intensity design**: computed market-based and location-based Scope 2 intensity as two
fully independent columns with no fallback between them (per your explicit instruction) — this
intentionally differs from `quality_checks.check_emissions`' combined `scope12_t` column, which
does prefer market-based and falls back to location-based. Put this logic in a new module,
`verigreen/carbon_intensity.py`, rather than in `quality_checks.py`, since it's a derived metric
built on top of the checks, not a check itself. Stora Enso's location-based intensity is blank
in every year by design: the operational-control (GHG Protocol) rows `check_emissions` selects
for Stora Enso (over the financial-control/ESRS rows, by source-type preference) simply don't
report a location-based Scope 2 figure — not substituted with the ESRS rows, just reported as
missing, per your explicit instruction.

**yfinance caching**: raw `Ticker.info`, `.history()`, and `.income_stmt` responses are cached
per-ticker under `data/bronze/yfinance_cache/` (git-ignored) so `scripts/fetch_market_data.py`
is idempotent — reruns rebuild output files from cache rather than re-querying Yahoo, unless
`--refresh` is passed. `.info` falls back to `.fast_info` if it raises or returns empty.

## 2026-09-26 — raw-vs-trusted dataset (`data/bronze/emissions_naive_vs_trusted.csv`)

Built per the internal project notes next-steps #1: naive-pipeline ("raw") values vs verified ("trusted") values,
for the demo showing the same optimiser on raw vs trusted data producing different portfolios.

**Included (5 rows), values confirmed against source PDFs in `data/raw_pdfs/`, not just the
log's summary text:**

| Company | Year | Category | Resolution |
|---|---|---|---|
| OUT1V.HE | 2023 | aggregator_error | DitchCarbon's "2023" figure is Outokumpu's own 2016 base-year row (p.41 of the 2023 Sustainability Review). Confirmed the aggregator's single "Scope 2" number is the **market-based** 2016 figure (1,210,872), not a location/market blend — verified by matching the surrounding 2021-2023 columns in the same table row against the trusted CSV values. `raw_scope2_location` left blank. |
| KEMIRA.HE | 2023 | pre_restatement | Kept as documented in the log/CSV notes (137 kt / 643 kt / 488 kt, AR2023 original). Did not re-derive from the PDF: the AR2023 GHG table sits on a page with bar/donut charts that `pdftotext` scrambles badly (numbers scatter across chart labels, off by one row from their true labels). Trusting the original manual read over a garbled automated extraction. |
| NDA-FI.HE | 2024 | pre_restatement | Confirmed verbatim in `nordea-annual-report-2025.pdf`: "the restatements (in tCO2e) were for scope 1 from 1,025 to 1,810, scope 2 from 6,299 to 16,779 (location-based) and 3,037 to 16,540 (market-based)." Exact match to the existing CSV note. |
| NDA-FI.HE | 2025 | financed_emissions | Confirmed in the same report, p.137: "GHG emissions associated with our lending and investment portfolios and generated by our own operations amounted to 19.8 MtCO2e in 2025." Own Scope1+2 is ~1,400x smaller, so effectively all financed (cat 15). |
| SAMPO.HE | 2025 | financed_emissions | The E1-6 table in `sampo2025-board-report-financial-statements.pdf` has the same row-shift extraction problem as Kemira's table. Cross-referenced against the existing CSV note (which already attributed 388,417 t to cat 15 "Investments") rather than trusting the raw column position, which would suggest cat 14 "Franchises" — implausible for an insurer with no franchise operations. |

**Excluded / deferred, with reasoning:**

- **SAMPO.HE 2024** (pre_restatement): only `raw_scope1=882` is directly quoted (CSV note: "Scope 1 +530 t (from 882)"). The Scope 2 pre-restatement location/market values are *not* directly quoted anywhere available — they'd have to be back-calculated from stated deltas (+710, +88), which is a derived number, not a documented one. Sampo's actual AR2024 (which would have the original figures) isn't in `data/raw_pdfs`. Decision: include the row with `raw_scope1` only, leave Scope2 columns blank rather than compute.
- **Stora Enso 2025 boundary** (operational_control 0.99 Mt vs financial_control 1.14 Mt): not included. Both numbers are legitimately correct for their own boundary — nothing is actually wrong, so it doesn't fit the "naive pipeline ingested a bad value" framing, only a "picked the less-comparable of two correct tables" framing. Revisit if the demo needs a boundary-mismatch example specifically.
- **Elisa's apparent 77% Scope 1 drop 2023→2024**: not included. Both 2023 (old methodology) and 2024 (new methodology) figures are genuinely reported; the issue is a misleading trend across a methodology break, not a single wrong value. Already caught by check E08 (YoY jump) — better told as a "the pipeline flags it" story than as a raw-vs-trusted row.

**Format**: `data/bronze/emissions_naive_vs_trusted.csv`, one row per company-year with a
documented discrepancy — `company_id, company_name, fiscal_year, error_category, raw_scope1,
raw_scope2_location, raw_scope2_market, trusted_scope1, trusted_scope2_location,
trusted_scope2_market, unit, raw_source, trusted_source, notes`. `error_category` one of
`aggregator_error | pre_restatement | financed_emissions`.
