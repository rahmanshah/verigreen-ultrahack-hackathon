# Quantum results (stages F, F2, G, H, H2, H3): QAOA on the Aer simulator, FY2024 MAIN QUBO

**At 15 assets, classical methods solve this problem easily.** Brute force over all 2^15 = 32,768 states gives the
exact optimum in well under a second, and the simple classical heuristics below find it too. The QAOA result is shown
as a demonstration that the trusted-data pipeline runs end to end on a quantum workflow, **not as an advantage**.
Every QAOA number on this page is scored against the exact brute-force optimum. Everything here is a noise-free or
illustrative-noise **simulation**; no hardware has been used.

Settings were fixed before any QAOA run (`docs/decisions_log.md`, "Stages F / F2", "Stages G / H / H2" and "Stage H3" entries).
Code: `verigreen/qaoa.py`, `verigreen/classical_baselines.py`, `scripts/report_qaoa.py` (F, F2);
`verigreen/stage_gh.py`, `scripts/report_stage_gh.py` (G, H, H2, H3). Tests: `uv run python tests/test_qaoa.py`,
`tests/test_stage_gh.py`.
Outputs: `data/gold/qaoa_runs_fy2024.csv` (every restart, failed ones included), `data/gold/qaoa_summary_fy2024.csv`
(selected restarts + random baselines), `data/gold/qaoa_classical_baselines_fy2024.csv`; stage G
`qaoa_stage_g_runs_fy2024.csv` / `qaoa_stage_g_summary_fy2024.csv`; stage H `qaoa_stage_h_instance_fy2024.csv`,
`_sizing_`, `_simulation_`, `_summary_`; stage H2 `qaoa_stage_h2_noise_fy2024.csv`; stage H3 `qaoa_stage_h3_instance_`, `_sizing_`, `_simulation_`,
`_summary_`, `_noise_fy2024.csv`.

## Setup

- Problem: choose K = 6 of 15 assets, `MAIN_CONFIG` (return weight 1, lambda_carbon 1, lambda_u 0), main inputs frozen
  in `data/gold/qubo_inputs_fy2024.json`. Exact optimum: Elisa, KONE, Nordea, Orion, Sampo, Wartsila.
  5,005 feasible portfolios, 14 of them within 5% of the optimum (stage E).
- Qubit i = asset i (sorted company_id); x_i = (1 - Z_i)/2. The Ising operator is divided by its largest absolute
  Pauli coefficient (reorders nothing). Tested: the operator's diagonal reproduces the QUBO energy on all 2^15 states.
- Penalties: **exact** P = 1.1 x P* (separates all states) and **practical** P = 1.1 x P_gs, where P_gs is the smallest
  P that keeps the exact optimum as the global ground state.
- qiskit-algorithms `QAOA`, COBYLA (maxiter 300), objective = mean energy over 4,096 shots, Aer simulator (noise-free).
  p = 1, 2, 3; 5 seeded random restarts (beta, gamma uniform in [0, pi]) plus, for p >= 2, one restart from the
  selected p - 1 parameters. The restart reported is the one with the lowest final optimised expected energy, i.e.
  chosen by QAOA's own objective, never by knowledge of the optimum.
- Read-out: each optimised circuit is re-sampled with 16,384 shots (fixed seed) **and** evaluated as an exact
  statevector, because the random baselines (~0.02%) are close to the resolution of a shot sample.

## Metrics

F_min / F_max = best / worst objective over the 5,005 feasible portfolios; r(x) = (f(x) - F_min) / (F_max - F_min), so
r = 0 is the optimum and r = 1 the worst feasible portfolio. "Within 5%" = feasible and r <= 0.05.

| metric | definition | baseline QAOA must beat |
|---|---|---|
| (a) P(optimum) | probability of the exact optimal bitstring | 1/5,005 = 0.020% (random feasible); 1/32,768 = 0.0031% (uniform superposition) |
| (a2) near-optimal mass | probability of a feasible state within 5%; also divided by the feasible probability ("given feasible") | 14/32,768 = 0.043% (unconditional); 14/5,005 = 0.28% (given feasible) |
| (a3) baseline | the random-sampling shares above, from `exact_summary_fy2024.json` | |
| (a4) approximation ratio | r of the best feasible sample, and mean r over the feasible probability mass | mean r of a random feasible portfolio |
| (b) best sample | best sampled feasible portfolio and its gap f - F_min | |
| (c) feasible share | probability of exactly 6 assets | C(15,6)/2^15 = 15.3% |
| (d) cost | wall-clock seconds and optimiser evaluations (each = one 4,096-shot circuit run) | |

## Stage F: standard QAOA

Penalties: P* = 14.37, **P_gs = 0.614, P_gs / P* = 0.043**. So the exact penalty is 23x larger than needed to keep
the right ground state. Exact P = 15.80 (Ising norm 25.7), practical P = 0.676 (Ising norm 2.98).

Selected restart per (penalty, p). P(opt), near-optimal mass, feasible share and mean r are from the exact statevector;
the best sample is from the 16,384-shot read-out (the shot values agree with the statevector within sampling noise and
are in the CSV).

| penalty | p | (a) P(opt) | (a2) within 5% | (a2) within 5%, given feasible | (c) feasible share | (a4) mean r, feasible | (a4) best sample r | (d) evals | (d) seconds |
|---|---|---|---|---|---|---|---|---|---|
| **baseline**: random feasible | | 0.020% | 0.28% | 0.28% | 100% | 0.450 | | | |
| **baseline**: uniform superposition | | 0.0031% | 0.043% | 0.28% | 15.3% | 0.450 | | | |
| exact | 1 | 0.011% | 0.15% | 0.29% | 51.7% | 0.447 | 0 | 27 | 4.0 |
| exact | 2 | 0.011% | 0.15% | 0.29% | 52.9% | 0.447 | 0 | 35 | 5.3 |
| exact | 3 | 0.0099% | 0.14% | 0.29% | 47.9% | 0.447 | 0 | 53 | 8.9 |
| practical | 1 | 0.018% | 0.24% | 0.72% | 33.5% | 0.385 | 0 | 27 | 3.9 |
| practical | 2 | 0.018% | 0.24% | 0.78% | 30.5% | 0.379 | 0 | 34 | 5.2 |
| practical | 3 | **0.21%** | **2.0%** | **8.0%** | 25.2% | **0.232** | 0 | 61 | 8.6 |

(b) In every row the best sampled feasible portfolio is the exact optimum (Elisa, KONE, Nordea, Orion, Sampo,
Wartsila), gap 0. **This says almost nothing.** The read-out holds 4,000-8,600 feasible shots, and a uniformly random
feasible sample of that size would contain the optimum with probability 55-82%. Brute force needs 5,005 evaluations.

(d) The whole of stage F (34 restarts, 1,507 optimiser evaluations of 4,096 shots each, plus read-outs) took 4 minutes on
a noise-free laptop simulator. COBYLA stopped after 27-76 evaluations in every restart, well before maxiter 300.

**Reading, stated plainly.**
- **Exact penalty: QAOA does not beat random feasible sampling.** It moves probability onto 6-asset portfolios (48-53%
  vs 15.3%), but among them it is essentially uniform: 0.29% within 5% vs 0.28%, mean r 0.447 vs 0.450, and P(opt)
  about half the random-feasible value. The penalty dominates the Hamiltonian (P = 15.8, feasible range 13.8, and the
  budget term sets the Ising norm), so the optimiser mainly learns "pick 6".
- **Practical penalty, p = 1 and 2: a small gain.** Within 5%, given feasible, is 2.6-2.8x the baseline and mean r
  0.38-0.39, but P(opt) (0.018%) is still below random feasible sampling.
- **Practical penalty, p = 3: the only clear gain.** P(opt) is 10x random feasible sampling (68x the uniform
  superposition), 8.0% of feasible mass is within 5% (29x), and mean r is 0.23. By the pre-registered rule, F
  therefore does **not** count as failed at 15 assets, so the 12/10-asset fallback is not triggered.
- **This rests on one restart.** At practical p = 3, 1 of 6 restarts beats random feasible sampling on P(opt); the other five
  end near random level. Across all 34 restarts, 5 beat P(opt) 1/5,005. The landscape is rough, and the "best restart
  by expected energy" rule picked the good one here, but that is one data point.
- **Selecting by energy has a side effect under the exact penalty.** It favours restarts that maximise feasibility.
  Exact p = 3, restart 3 had P(opt) 0.035% and 3.4% within 5% given feasible, but only 12.7% feasible share, so its
  expected energy was higher and it was not selected. That is the pre-registered rule, kept as is; every restart is in
  `qaoa_runs_fy2024.csv`.
- Even the best QAOA run puts 0.21% of its probability on the optimum. That is far from "solving" the problem; the
  classical methods below solve it every time.

### Additional reliability run (not part of the pre-registered set)

Requested after the stage F results above had been seen. 20 more seeded random restarts (restart indices 10-29, seeds
disjoint from the pre-registered 0-5) for the four rows below, so 26 restarts per row (25 at p = 1, which has no
"extend" restart). The headline rows above are unchanged: the pre-registered selection rule still picks from restarts
0-5 only. "Rule over all" applies the same rule (lowest final expected energy) to all 26, for information.
"Best by P(opt)" is chosen with knowledge of the optimum, so it is an oracle and not a usable result.
Data: `qaoa_runs_fy2024.csv` rows with `stage = F_reliability`, summary `data/gold/qaoa_reliability_fy2024.csv`.

| penalty | p | restarts | beat 0.020% on P(opt) | beat 0.28% within 5%, given feasible | median P(opt) | median within 5%, given feasible | median mean r | rule over all: P(opt) | best by P(opt) (oracle) |
|---|---|---|---|---|---|---|---|---|---|
| exact | 3 | 26 | 2 | 17 | 0.0051% | 0.33% | 0.447 | 0.0099% (headline restart) | 0.035% |
| practical | 1 | 25 | 1 | 15 | 0.0053% | 0.37% | 0.447 | 0.019% | 0.028% |
| practical | 2 | 26 | 11 | 19 | 0.015% | 1.03% | 0.430 | 0.14% | 0.19% |
| practical | 3 | 26 | 11 | 17 | 0.014% | 0.61% | 0.430 | 0.21% (headline restart) | 0.37% |

- **The typical restart does not beat random feasible sampling on P(optimum) in any row**: every median is below 0.020%.
- On within-5% mass given feasible, a majority of restarts beat 0.28% in every row, but at exact p = 3 and practical
  p = 1 the median (0.33%, 0.37%) is only just above it.
- Practical p = 2 and 3: about 4 in 10 restarts (11/26) beat the P(opt) baseline. The energy rule applied to all 26
  picks a good restart in both (0.14%, 0.21%), so selecting by expected energy works when the penalty is small.
- The headline practical p = 3 result (0.21%) is reproducible by the rule, but it is not a typical restart.

## Stage F2: warm-start QAOA (Egger, Marecek and Woerner 2021)

**Most of the F2 result comes from the classical step.** Rounding the classical relaxation already gives the exact
optimum, and the warm initial state alone, before any QAOA layer, puts 7.9% on it (eps = 0.1). The QAOA layers then
multiply that by 1.6-3.5x (selected restarts) or 1.2-1.9x (median restart).

**Relaxation.** The original formula (full Sigma) over x in [0,1]^15 with sum(x) = 6, solved with SLSQP from 5 starts that
agree to 1e-7. It is convex: the smallest eigenvalue of the risk term is 0.078 > 0, and the budget matrix 11' is PSD. The
budget is an exact constraint, so c* is the same for both penalties. f(c*) = -2.082, 0.077 below F_min (0.56% of the
feasible range). File: `data/gold/qaoa_relaxation_fy2024.csv`.

| asset | Elisa | Nordea | Orion | Sampo | Wartsila | KONE | Nokia | Kesko | other 7 |
|---|---|---|---|---|---|---|---|---|---|
| c* | 1.00 | 1.00 | 1.00 | 1.00 | 0.91 | 0.54 | 0.38 | 0.17 | 0.00 |

The relaxation fixes five names and splits the sixth slot between KONE, Nokia and Kesko, which is the same near-tie
stage E found (rank 2 swaps KONE for Nokia at 0.51% of the range, rank 3 for Kesko at 0.99%). **The rounded relaxation
(top 6 of c*) is the exact optimum, rank 1 of 5,005, with no quantum step.**

**Circuit.** c clipped to [eps, 1 - eps]. Initial state RY(theta_i)|0> with theta_i = 2 arcsin(sqrt(c_i)). Mixer per
qubit RY(theta_i) RZ(-2 beta) RY(-theta_i), i.e. exp(-i beta H_M) with H_M = -RY(theta) Z RY(-theta), whose ground state
is the initial state. Both are passed to qiskit-algorithms `QAOA` (`initial_state=`, `mixer=`); `QAOAAnsatz` replaces
the mixer's parameter with beta[k] per layer. Tested: at beta = 0 (any gamma) the marginals equal c_i exactly on the
statevector and within 5 sigma on 20,000 shots, with c_i distinct per qubit so that qubit ordering is checked. Same
seeds, initial points, restarts, optimiser and read-out as F.

Selected restart per row, with the pure classical reference rows next to each (statevector values; shot values agree,
see the CSV). "x p=0" = P(opt) relative to the warm initial state of the same eps.

| row | P(opt) | x p=0 | within 5% | within 5%, given feasible | feasible share | mean r, feasible | evals | s |
|---|---|---|---|---|---|---|---|---|
| random feasible portfolio | 0.020% | | 0.28% | 0.28% | 100% | 0.450 | | |
| best standard QAOA (F, practical p=3) | 0.21% | | 2.0% | 8.0% | 25.2% | 0.232 | 61 | 8.6 |
| **classical**: rounded relaxation | **exact optimum (r = 0)** | | | | | | | |
| **classical**: warm state, eps 0.1, p=0 | **7.9%** | 1 | 16.0% | 52.1% | 30.6% | 0.071 | 0 | |
| warm eps 0.1, exact, p=1 | 12.6% | 1.6 | 26.9% | 48.2% | 55.8% | 0.078 | 31 | 1.9 |
| warm eps 0.1, exact, p=2 | 13.7% | 1.7 | 29.2% | 48.6% | 60.1% | 0.077 | 38 | 3.1 |
| warm eps 0.1, exact, p=3 | 19.9% | 2.5 | 43.1% | 47.3% | 91.1% | 0.079 | 57 | 7.6 |
| warm eps 0.1, practical, p=1 | 16.6% | 2.1 | 32.7% | 66.1% | 49.4% | 0.043 | 34 | 2.1 |
| warm eps 0.1, practical, p=2 | 19.6% | 2.5 | 34.3% | 84.9% | 40.5% | 0.018 | 62 | 4.8 |
| warm eps 0.1, practical, p=3 | **28.0%** | 3.5 | 46.1% | **91.0%** | 50.7% | **0.013** | 67 | 5.8 |
| **classical**: warm state, eps 0.25, p=0 | **0.80%** | 1 | 2.5% | 11.5% | 21.8% | 0.208 | 0 | |
| warm eps 0.25, exact, p=1 | 1.5% | 1.9 | 5.0% | 10.8% | 46.5% | 0.212 | 31 | 3.2 |
| warm eps 0.25, exact, p=2 | 1.6% | 2.0 | 5.3% | 10.5% | 50.7% | 0.214 | 37 | 4.3 |
| warm eps 0.25, exact, p=3 | 2.2% | 2.7 | 7.3% | 10.2% | 71.9% | 0.216 | 52 | 6.2 |
| warm eps 0.25, practical, p=1 | 2.6% | 3.2 | 7.9% | 18.9% | 41.6% | 0.157 | 28 | 2.5 |
| warm eps 0.25, practical, p=2 | 4.8% | 6.0 | 12.6% | 37.9% | 33.2% | 0.100 | 49 | 4.6 |
| warm eps 0.25, practical, p=3 | 4.8% | 6.0 | 12.6% | 38.2% | 32.9% | 0.099 | 52 | 4.9 |

(b) The best sampled feasible portfolio is the exact optimum in every row (gap 0); as in F this is weak evidence.
(d) All of F2 (228 restarts including the reliability run, 10,958 evaluations) took 22 minutes; COBYLA again stopped
after 25-94 evaluations.

**Reliability** (additional run, not pre-registered; same 20 extra seeds as F; `qaoa_reliability_fy2024.csv`). Against
random feasible sampling every warm-start restart wins, which is trivial because the initial state already does. The
relevant bar is the p = 0 warm state:

| row | restarts | beat random feasible on P(opt) | beat the p=0 warm state on P(opt) | on within 5% given feasible | on mean r | median P(opt) | median x p=0 |
|---|---|---|---|---|---|---|---|
| eps 0.1, exact, p=3 | 26 | 26 | 15 | 3 | 2 | 9.1% | 1.16 |
| eps 0.1, practical, p=1 | 25 | 25 | 24 | 24 | 24 | 15.0% | 1.91 |
| eps 0.1, practical, p=2 | 26 | 26 | 20 | 21 | 18 | 9.7% | 1.23 |
| eps 0.1, practical, p=3 | 26 | 26 | 21 | 19 | 22 | 13.6% | 1.72 |
| eps 0.25, exact, p=3 | 26 | 25 | 15 | 14 | 3 | 1.3% | 1.59 |
| eps 0.25, practical, p=1 | 25 | 25 | 18 | 18 | 18 | 1.5% | 1.84 |
| eps 0.25, practical, p=2 | 26 | 25 | 16 | 16 | 13 | 1.0% | 1.29 |
| eps 0.25, practical, p=3 | 26 | 24 | 14 | 13 | 10 | 0.80% | 1.01 |

**Reading, stated plainly.**
- **How much comes from the classical step.** Relative to random feasible sampling (0.020%), the warm initial state
  alone is a factor of about 390 on P(opt) (eps 0.1). The QAOA layers then add a factor of 1.6-3.5 for the selected
  restarts and 1.2-1.9 at the median restart (eps 0.25: 1.9-6.0 and 1.0-1.8, from a starting point 10x lower). The rounded relaxation alone already returns the exact optimum. Without
  the classical step, standard QAOA reached at most 0.21%.
- **eps matters more than depth.** At eps 0.25 the whole warm-start pipeline (best 4.8%) stays below the eps 0.1 initial
  state with no QAOA at all (7.9%). eps is a classical choice.
- **Exact penalty: the gain is feasibility, not quality.** P(opt) rises because the feasible share rises (31% to 56-91%),
  but within the feasible set, QAOA does not improve on the warm state. Within 5% given feasible goes 52% to 47-49%,
  mean r 0.071 to 0.077-0.079, and 2-3 of 26 restarts beat the warm state on those two measures at p = 3. This matches F,
  where the large penalty dominated.
- **Practical penalty, eps 0.1: the QAOA layers do improve the distribution.** At p = 3, within 5% given feasible goes from
  52% to 91%, mean r from 0.071 to 0.013, and P(opt) from 7.9% to 28%. About 4 in 5 restarts beat the warm state on each
  measure (19-22 of 26). This is the clearest quantum-circuit contribution in F and F2, and it sits on top of a classical
  solution that is already exact once rounded.
- None of this is an advantage. The classical relaxation plus rounding, the greedy swap search (median 139 evaluations)
  and brute force each find the optimum outright; the warm-start QAOA is the best demonstration of the workflow, not a
  faster or better solver.

## Classical baselines on the same QUBO

Feasible swap moves only, 100 seeded runs per method, budget 50,000 objective evaluations each
(`data/gold/qaoa_classical_baselines_fy2024.csv`). Simulated annealing T0 = 1.67 (std of random swap deltas; feasible
range 13.75), cooled geometrically to T0/1000.

| method | runs hitting the exact optimum | evaluations to first hit: median | p90 | max |
|---|---|---|---|---|
| greedy swap local search (random restarts) | 100 / 100 | 139 | 239 | 293 |
| simulated annealing | 100 / 100 | 441 | 1,461 | 2,572 |
| brute force over feasible portfolios | exact by construction | 5,005 | | |

**At 15 assets classical methods solve this problem easily.** A greedy swap search finds the exact optimum within 300
objective evaluations in every run. One QAOA evaluation is a 4,096-shot circuit run, and the best QAOA run (61 of them)
leaves 99.8% of its probability elsewhere. The quantum result is a **pipeline demonstration, not an advantage**: it shows
that the trusted inputs, the QUBO and the benchmark run end to end on a quantum workflow and are scored honestly against
the exact optimum.

## Stage G (reduced): does warm-start QAOA reproduce the raw-vs-trusted result?

**Where the result comes from.** Which portfolio is optimal on naive vs trusted inputs is established by **exact
enumeration** (stage G0, `data/gold/raw_vs_trusted_exact_fy2024.csv`) and by the **classical relaxation**, which, solved on
the naive inputs, already returns the changed portfolio. QAOA is shown reproducing it, not finding it. Each case's exact
optimum below is read from the G0 CSV and asserted equal to a fresh brute-force run.

Cases (FY2024, `frozen_trusted_z`, practical penalty P = 1.1 x P_gs, warm start eps 0.1): MAIN trusted; MAIN with the
Nordea financed-emissions error (Nordea 1.5 -> 1,640 tCO2e/EURm); MAIN with the Sampo financed-emissions error
(0.5 -> 31.1); TRUST (u) trusted (no naive data; it shows the data-trust term moving the selection). p = 1 and 3, 10 seeded
random restarts each (restarts 0-4 use the F2 seeds; a test checks that MAIN restart 0 reproduces the F2 row), selected
restart = lowest final expected energy (the F2 rule). Per case the relaxation, P* and P_gs are recomputed.

**Classical rows** (statevector for the p = 0 warm state; "x within 5%" is given feasible):

| case | exact optimum (best-to-second gap) | rounded relaxation | warm state p = 0: P(opt) | within 5% | most likely feasible |
|---|---|---|---|---|---|
| MAIN trusted | Elisa, KONE, Nordea, Orion, Sampo, Wartsila (0.51% of range) | = exact optimum | 7.9% | 52.1% | the optimum |
| MAIN, Nordea financed | **Nordea out, Nokia in** (1.05%) | = exact optimum | 8.7% | 52.0% | the optimum |
| MAIN, Sampo financed | **no change** vs MAIN trusted (0.55%) | = exact optimum | 7.9% | 55.0% | the optimum |
| TRUST (u) trusted | **KONE out, Nokia in** vs MAIN (0.51%) | = exact optimum | 8.4% | 53.5% | the optimum |

In all four cases the rounded relaxation (top 6 of c*) is the exact optimum, rank 1 of 5,005, and the p = 0 warm state's
most likely feasible portfolio is already the optimum. In the Nordea case c* puts Nordea at exactly 0 and Nokia at 0.70.

**Warm-start QAOA** (statevector; the 16,384-shot P(opt) agrees within 0.6 percentage points everywhere, see the CSV). "Beat
p = 0" counts restarts out of 10 better than the p = 0 warm state of the same case, on P(opt) / within-5% given feasible /
mean r. "Top = optimum" counts restarts whose most likely feasible portfolio is the exact optimum.

| case | p | selected: P(opt) | within 5%, given feasible | feasible share | median P(opt) | median within 5%, given feasible | beat p = 0 (of 10) | top = optimum (of 10) |
|---|---|---|---|---|---|---|---|---|
| MAIN trusted | 1 | 16.9% | 64.4% | 52.2% | 15.5% | 62.7% | 8 / 8 / 9 | 10 |
| | 3 | **28.0%** | **91.0%** | 50.7% | 13.8% | 58.8% | 8 / 6 / 6 | 9 |
| MAIN, Nordea financed | 1 | 17.5% | 63.5% | 48.9% | 16.4% | 61.0% | 8 / 8 / 8 | 10 |
| | 3 | 28.4% | 89.9% | 46.1% | 15.6% | 64.2% | 8 / 7 / 7 | 9 |
| MAIN, Sampo financed | 1 | 16.2% | 69.1% | 48.1% | 13.9% | 62.1% | 9 / 9 / 8 | 10 |
| | 3 | 24.0% | 89.1% | 46.9% | 12.8% | 62.1% | 7 / 6 / 6 | 9 |
| TRUST (u) trusted | 1 | 15.6% | 59.0% | 52.2% | 15.4% | 58.5% | 9 / 9 / 9 | 10 |
| | 3 | 26.9% | 85.5% | 51.3% | **7.9%** | 48.9% | **5 / 5 / 5** | 9 |

**Reading, stated plainly.**
- **Reproduced in all 8 (case, p) selected restarts**: the most likely feasible portfolio is the case's exact optimum, so the
  Nordea change (Nokia in, Nordea out), the TRUST change (Nokia replaces KONE) and the Sampo no-change all appear. It is also
  the top portfolio in 9 or 10 of 10 restarts per row. **This is inherited from the classical step**: the p = 0 warm state
  already has the optimum as its most likely feasible portfolio in every case, so QAOA keeps the result and sharpens it
  (selected-restart P(opt) is 1.9-2.1x the p = 0 value at p = 1 and 3.0-3.5x at p = 3), it does not discover it.
- **The selected p = 3 restart is a good draw, not a typical one.** The median p = 3 restart is below the median p = 1 restart in
  all four cases (P(opt) 7.9-15.6% vs 13.9-16.4%), and for TRUST (u) the median p = 3 restart (7.9%) is below its own p = 0
  state (8.4%), with only 5 of 10 restarts beating it. The energy rule picks a good restart each time (selected 24-28%), as in F2,
  but a user running one random restart should expect about 8-16%.
- **The optimiser can fail.** Restarts can end below the p = 0 state: 12 of 40 at p = 3 (2, 2, 3 and 5 per case) and 6 of 40 at
  p = 1 (2, 2, 1, 1). In 4 of the 40 p = 3 restarts the most likely feasible portfolio is no longer the optimum: restart 5 in the
  Nordea, Sampo and TRUST cases (P(opt) 0.5-0.6%, the most likely feasible portfolio has at most 0.9% probability) and restart 6
  in MAIN trusted (P(opt) 1.9%). The same initial point failing in three cases shows that the failure comes from the starting
  point and the landscape, not from the data. The energy rule did not select any of these.
- **Within the feasible set the p = 3 gain is real but rests on selection.** Within 5% given feasible goes from 52-55% (p = 0)
  to 85-91% for the selected restarts, but the median is 49-64%, i.e. roughly the p = 0 level.
- **Sampo (no change) is the case where the data error hides:** the selection is unchanged, but G0 shows the *reported* footprint
  of that portfolio is wrong (+107% equal-weight WACI under MAIN). QAOA cannot see that; it follows from the data, not the optimiser.
- The best-to-second gap is 0.5-1.1% of the feasible range in every case, so the portfolios compared are near ties; the
  distinction between KONE and Nokia, for example, is as small as in stage E.

Cost: 80 restarts, 90 s at p = 1 and 248 s at p = 3 in total on a laptop simulator.

## Stage H (sizing): the hardware-sized instance, classical pre-screen

**What it is.** The 8 assets with nonzero weight in the MAIN relaxation: Elisa, Kesko, KONE, Nordea, Nokia, Orion, Sampo,
Wartsila, K = 6, so 28 feasible portfolios. **This is a classical pre-screen**: the relaxation was solved on all 15 assets and
the other 7 have exactly zero weight. The coefficients are the 15-asset ones (scales frozen), P* and P_gs recomputed on the
subset (P* 3.18, practical P 0.676). Checked: (i) **the 15-asset optimum lies inside the 8-asset set** and is the 8-asset
optimum, with the identical objective (-2.0054); (ii) re-solving the relaxation on the 8 assets reproduces the 15-asset c*
to 1e-7; (iii) the second-best portfolio (Nokia for KONE, the stage E near-tie) is 2.75% of the 8-asset feasible range behind the optimum,
and 2 of the 28 portfolios are within 5% of it (the range is that of 28 portfolios, so the percentages are not comparable with the
15-asset ones).
The risk term couples every pair of the 8 assets (and so does the budget term): 28 ZZ terms.

**Sizing** (qiskit optimization level 3, native gate set {r, cz}, 20 transpiler seeds because routing is stochastic; median
(min-max); the depth counts every gate, measurement excluded). Line and 2 x 4 grid are **stand-ins**: the real IQM
topology and native gates replace them at the event.

| circuit | coupling | depth | two-qubit gates (cz) |
|---|---|---|---|
| warm start p = 0 | any | 1 | **0** (8 single-qubit gates) |
| warm start p = 1 | all-to-all (no routing) | 80 | 56 (= 2 x 28 pairs) |
| | 2 x 4 grid | 104 (94-163) | 72 (70-86) |
| | line | 149 (145-170) | 98 (95-115) |

The depth and cz count are the same for standard and warm-start QAOA at the same p (the warm start changes only single-qubit gates).

**Exact and simulated P(optimum)** (noise-free; exact = statevector, simulated = 16,384 shots; warm start eps 0.1, practical
penalty, 10 random restarts; baseline for p = 1 is **p = 0**):

| row | P(opt) exact | P(opt) shots | within 5% | within 5%, given feasible | feasible share | P(opt) given feasible |
|---|---|---|---|---|---|---|
| random feasible portfolio (1/28) | 3.6% | | 7.1% | 7.1% | 100% | 3.6% |
| uniform superposition (1/256) | 0.39% | | 0.78% | 7.1% | 10.9% | 3.6% |
| **warm start p = 0 (baseline)** | **16.5%** | | 25.1% | 68.5% | 36.6% | 45.1% |
| warm start p = 1, selected (restart 8) | **26.6%** | 26.8% | 40.7% | 69.5% | 58.6% | 45.4% |
| warm start p = 1, median of 10 | 25.7% | | 39.5% | 68.8% | 57.5% | |

7 of 10 restarts beat p = 0 on P(opt), 6 on within-5% given feasible, 5 on mean r; the other 3 restarts (P(opt) 14.9-16.5%) end just
below the p = 0 level. **p = 1 vs p = 0, stated plainly:** P(opt) rises by a factor 1.6, but it rises because the feasible share
rises (36.6% to 58.6%), not because the portfolios among the feasible ones improve: P(opt) given feasible is 45.1% at p = 0
and 45.4% at p = 1, and within 5% given feasible is 68.5% against 69.5%. With only 28 feasible portfolios the baseline is
high (3.6%) and the warm initial state alone, with no entangling gate, already puts 45% of the feasible mass on the optimum.

## Stage H2 (illustrative noise preview, 8-asset instance)

**Illustrative only, not IQM's noise.** Aer depolarising noise on cz (two-qubit error 0, 0.5%, 1%, 2%) and on r (ten times
smaller: 0, 0.05%, 0.1%, 0.2%), no readout, relaxation or crosstalk error, noise-free selected parameters (not re-optimised
under noise), 65,536 shots (P(opt) standard error 0.11-0.17 percentage points), seed 20261006, the 2 x 4 grid and the
all-to-all circuit (the transpile seed with the fewest cz out of 20: 70 and 56 cz). The real topology and error rates replace
this at the event. P(opt) (within 5% in brackets):

| circuit | two-qubit error 0 | 0.5% | 1% | 2% |
|---|---|---|---|---|
| random feasible baseline | 3.6% (7.1%) | | | |
| p = 0, all-to-all or grid (no cz) | 16.6% / 16.4% (25.0% / 24.9%) | 16.6% / 16.4% | 16.6% / 16.3% | 16.6% / 16.3% (24.9% / 24.8%) |
| p = 1, all-to-all (56 cz) | 26.7% (40.6%) | 21.4% (32.9%) | 17.5% (27.0%) | 11.3% (17.8%) |
| p = 1, 2 x 4 grid (70 cz) | 26.7% (40.8%) | 20.0% (30.8%) | **15.0%** (23.6%) | **8.9%** (14.4%) |

**What I find, including the unfavourable part.**
- **p = 1 does worse than p = 0 once the two-qubit error reaches about 1% on the grid** (15.0% vs 16.3-16.4%; the crossing is
  at about 0.9% by linear interpolation) and at about 1.1% on the all-to-all circuit (at 2% it is 11.3% vs 16.6%). At 2% on the grid P(opt) is 8.9%, about half the p = 0
  value, and the within-5% mass (14.4%) is also below p = 0 (24.8%). At 0.5% p = 1 is still ahead (20.0-21.4% vs 16.4-16.6%).
- p = 0 is essentially untouched by noise: it has no two-qubit gate, and the single-qubit error moves P(opt) by less than 0.1
  percentage points, within sampling error.
- The most likely feasible portfolio stays the exact optimum in every row, even at 2% two-qubit error and p = 1, but its
  probability can drop below the p = 0 value.
- Noise-free, the shot-based numbers agree with the statevector (16.65% vs 16.47% at p = 0, 26.65% vs 26.59% at p = 1).
- Consequence for the event plan: on real hardware the p = 0 circuit (the classical warm state, sampled) is the safe baseline,
  and p = 1 is only worth reporting if the measured two-qubit error is below roughly 1%.

## Stage H3: residual subproblem after variable fixing

**What it is: variable fixing from a classical relaxation. No advantage is claimed.** The classical relaxation of the 15-asset
MAIN problem decides 11 of the 15 variables before any quantum step, and what is left is a 4-qubit problem that brute force
solves in 16 evaluations.
- Fixed to 1 (c* >= 0.99): Elisa, Nordea, Orion, Sampo. Fixed to 0 (c* = 0): Fortum, Kemira, Metso, Neste, Outokumpu, Stora Enso, UPM.
- **Undecided**: Wartsila (c* 0.91), KONE (0.54), Nokia (0.38), Kesko (0.17); c* sums to 2.0, so K_res = 6 - 4 = 2 and there are
  C(4,2) = **6 feasible portfolios**. The random baseline is **1/6 = 16.7%** (1/16 = 6.25% for a uniform superposition).
- Coefficients: the frozen 15-asset ones. The fixed assets' contributions are folded into the undecided assets' linear terms
  and the constant (-2.625) is dropped. P* 1.09, exact penalty 1.20, practical penalty 0.676 (recomputed on the residual).
- **Checks (tested):** the exact residual optimum, KONE and Wartsila, plus the four fixed assets **is the 15-asset optimum**
  (Elisa, KONE, Nordea, Orion, Sampo, Wartsila); residual energy + the constant equals the 15-asset objective on all 6 feasible
  portfolios; the relaxation re-solved on the residual equals the 15-asset c* on those four assets to 7e-8. The rounded
  relaxation (top 2) is the optimum. The best-to-second gap is 14.8% of the residual range and only the optimum is within 5%
  (so "within 5%" equals P(opt) in this section).

**p = 0 is a product state.** The warm initial state (eps 0.1: Wartsila 0.90, KONE 0.54, Nokia 0.38, Kesko 0.17) has no
entangling gate and is **classically equivalent to four independent biased coin flips**: each qubit is 1 with probability
c_i, and every bitstring probability is the product of these. Flipping the four coins on a laptop reproduces the p = 0
distribution (tested with 200,000 draws). Any p = 0 number below is a classical number.

**Sizing** (optimization level 3, native {r, cz}, 20 transpiler seeds, median (min-max); line and 2 x 2 grid are stand-ins):

| circuit | coupling | depth | two-qubit gates (cz) |
|---|---|---|---|
| warm start p = 0 | any | 1 | **0** (4 single-qubit gates) |
| warm start p = 1 | all-to-all | 31 | 12 (= 2 x 6 pairs) |
| | 2 x 2 grid | 40 (33-46) | 18 (14-18) |
| | line | 44 (44-48) | 17 (17-19) |

**Exact and simulated P(optimum)** (noise-free; warm start eps 0.1, practical penalty, 10 random restarts; baseline for p = 1 is p = 0):

| row | P(opt) exact | P(opt) shots | feasible share | P(opt) given feasible | mean r, feasible |
|---|---|---|---|---|---|
| random feasible portfolio (1/6) | 16.7% | | 100% | 16.7% | 0.470 |
| **warm start p = 0 (baseline)** | **25.1%** | | 45.0% | 55.7% | 0.107 |
| warm start p = 1, selected (restart 6) | **34.9%** | 34.2% | 61.5% | 56.8% | 0.104 |
| warm start p = 1, median of 10 | 30.7% | | 56.6% | 53.8% | 0.111 |

8 of 10 restarts beat p = 0 on P(opt), but only 4 of 10 on P(opt) given feasible and on mean r. The restarts range from 14.0% to
43.1%: two end below the p = 0 state and one (14.0%) below the random feasible baseline. **As in H, the p = 1 gain is the feasible
share** (45.0% to 61.5%), not the choice among feasible portfolios (55.7% vs 56.8%). The most likely feasible portfolio is the
optimum in all 10 restarts and in every noise row below.

**Noise sweep** (H2 settings: depolarising error on cz in {0, 0.5%, 1%, 2%}, single-qubit error ten times smaller, 65,536 shots,
seed 20261006, noise-free parameters, the transpile seed with the fewest cz out of 20; illustrative, not IQM's noise). P(opt),
standard error about 0.17-0.19 percentage points:

| circuit | two-qubit error 0 | 0.5% | 1% | 2% |
|---|---|---|---|---|
| p = 0 (no cz), all three couplings | 24.9-25.0% | 24.9-25.0% | 24.9-25.0% | 24.9-25.0% |
| p = 1, all-to-all (12 cz) | 35.1% | 33.6% | 32.1% | 29.6% |
| p = 1, 2 x 2 grid (14 cz) | 34.9% | 33.2% | 31.5% | 28.5% |
| p = 1, line (17 cz) | 35.0% | 32.7% | 30.5% | 26.7% |

**What I find.** With 12-17 two-qubit gates, p = 1 stays above p = 0 across the whole sweep, on all three couplings, though the
margin shrinks as the error grows (line at 2%: 26.7% vs 24.9%). This differs from the 8-asset instance of H2, where 56-70 cz in the
noise runs made p = 1 fall below p = 0 at about 1%; the likely reason is the gate count, which I did not test separately. The sweep stops at 2%, and nothing is extrapolated
beyond it. What the number means: on this 4-qubit problem a p = 1 circuit that survives noise beats a coin-flip sampler by
about 2-10 percentage points of P(opt) (10 noise-free, 2-5 at 2% error), and both are far from "solving" anything that 16 brute-force evaluations do not solve.

