# IQM Resonance: connection check, local transpile and run plan

Date: 8 Oct 2026. **No job was submitted in the first session** (sections 1-6); six jobs were submitted later the same
day and are logged in section 7. The first session did: connect to Resonance for Garnet and Emerald (device metadata only),
local transpile, and write a guarded run script. Environment: side env `<venvs>\verigreen-iqm`
(iqm-client 35.0.3, qiskit 2.1.2); see `docs/hardware_prep.md`. The token is read from `IQM_TOKEN` (via `.env`) and was
never printed.

## 1. Credit and device facts (from IQM, confirm in account)

Not verified by us. Source: Shah, relaying IQM. Check each in the Resonance account before relying on it.

| | Garnet | Emerald |
|---|---|---|
| Qubits | 20 | 54 |
| Rate | 0.50 credit/s | 0.75 credit/s |
| CZ fidelity | 99.48% | 99.63% |

- Credits: 280 in total (30 Starter plus 250 extra), valid for Garnet and Emerald.
- **Credit cost per job: unknown.** Not estimated here. What the rate is charged against (QPU time, or time including
  compilation or overhead) is also unknown to us.

## 2. Connection check (8 Oct 2026)

`IQMProvider("https://resonance.meetiqm.com", quantum_computer=...).get_backend()`, one call per device.

| | Garnet | Emerald |
|---|---|---|
| Backend name | garnet | emerald |
| Qubits | 20 | 54 |
| Operations | cz, r, measure, reset, id, delay, if_else | same |
| Native gates | cz, r | cz, r |
| Coupling edges | 30 | 85 |

- The token was set in `.env` only (not in the shell environment); scripts load it with python-dotenv.
- **Credits:** these calls fetch the device architecture and create no job. I believe they cost nothing, but I could not
  confirm it: iqm-client 35.0.3 has no credit-balance call. Compare the balance in the account before and after to be sure.
- One failure on the way: a method-name typo in my own scratch script (`index_to_qb_name`, correct name
  `index_to_qubit_name`). Not an IQM error.

## 3. Local transpile of the residual circuits

Circuits: `qasm/residual_fy2024/residual_p0.qasm` and `residual_p1.qasm` (4 qubits, see `docs/hardware_prep.md`),
`measure_all()` added, transpiled against the real backend objects. Seeds 0-9, optimisation levels 1 and 3. Depth includes
the measurement layer. Min / median / max.

| Device | Circuit | Level | CZ | Depth | Physical qubits |
|---|---|---|---|---|---|
| Garnet | p0 | 1, 3 | 0 / 0 / 0 | 2 / 2 / 2 | QB17-QB20 (10 of 10) |
| Garnet | p1 | 1 | 18 / 18 / 18 | 30 / 33 / 35 | QB17-QB20 (8 of 10); plus QB7 or QB15 (1 each) |
| Garnet | p1 | 3 | 16 / 18 / 18 | 32 / 36 / 38 | QB17-QB20 (7 of 10); plus QB7, QB15 or QB4 (1 each) |
| Emerald | p0 | 1, 3 | 0 / 0 / 0 | 2 / 2 / 2 | QB1-QB4 (10 of 10) |
| Emerald | p1 | 1 | 18 / 18 / 18 | 28 / 31 / 35 | QB1-QB4 (8 of 10); plus QB30 or QB32 (1 each) |
| Emerald | p1 | 3 | 16 / 18 / 18 | 26 / 34.5 / 37 | QB1-QB4 (7 of 10); plus QB30, QB32 or QB41 (1 each) |

- **Against our estimate (about 18 CZ at p=1, 0 at p=0): matches.** p=0 is 0 CZ, p=1 is 18 CZ at level 1 and 16-18 at
  level 3 (12 logical CZ plus 2 SWAP x 3 CZ, level 3 cancels some). No difference to report.
- Garnet numbers are identical to the fake-Garnet table in `docs/hardware_prep.md` (CZ, depth ranges, qubit sets). Only the
  edge count (30) was compared with the fake, not edge-for-edge.
- This is the first transpile against Emerald; no fake Emerald exists in the package.
- **Qubit choice is probably not calibration-aware.** `get_backend()` defaults to `use_metrics=False`, so no calibration
  data goes into the transpile target. The chosen qubits (QB17-QB20 on Garnet, QB1-QB4 on Emerald) look like a
  connectivity choice. Whether they are good qubits on the day is unknown. `get_backend(use_metrics=True)` exists, but its
  docstring says quality metrics are not yet available on the Resonance API; not tried.
- The run script submits the level-3 transpile with the fewest CZ over seeds 0-9 (then lowest depth, lowest seed).
- Not checked: the full transpiled circuits were not simulated for equivalence (the QASM itself was checked in
  `docs/hardware_prep.md`); live calibration set; which qubit pairs the 4-qubit layout uses and their individual fidelities.

## 4. Run script

`scripts/hardware/run_residual_iqm.py` (side env). Written, parsed and its shot guard exercised; **not run past the
argument checks in the first session** (runs 1-6 in section 7 used it).

- Submits nothing unless `--submit` and `--confirm-credits` are both given (one without the other is refused).
- `--device garnet|emerald`, `--circuit p0|p1`, `--shots` (default 100). Above 100 shots needs `--max-shots N` with
  shots <= N.
- Without the two flags it is a dry run: connects (metadata only), transpiles, validates the run request without sending
  it, prints the summary.
- Before submitting it prints device, circuit, shots and CZ count and waits for a typed `yes`.
- Each run writes a new file `data/hardware/<UTC time>_<device>_<circuit>_<shots>shots.json` (created with mode `x`, so it
  cannot overwrite an earlier run). The job id is written as soon as the job is submitted, so it survives a timeout. The
  final file holds raw counts, job id, wall-clock seconds from submit to result, date, qasm hash, transpile details and
  library versions.
- Credit balance: the 35.0.3 client offers none, so the script prints "Check the credit balance in the Resonance account."
- `data/hardware/` is not git-ignored and nothing was committed.

## 5. Planned run order

100 shots each, one job at a time, reading the credit balance in the account between jobs:

1. p0 on Garnet
2. p1 on Garnet
3. p1 on Emerald

Check the balance after job 1 and use it to decide whether to continue. p0 has no CZ gate, so it is the cheapest test
of the whole path (submit, queue, counts, file saved).

Status: these three jobs were run on 2026-10-08 in this order (runs 1-3), followed by three 1000-shot jobs (runs 4-6;
section 7).

## 6. Open questions

- **Cost per job in credits.** Measured for six short jobs (0.50, 0.50, 0.75, 0.50, 0.75, 0.50; section 7); not known for longer jobs.
- Whether the 250 extra credits expire, and when.
- Queue times on Garnet and Emerald at the time of the run.
- Whether `IQM_TOKEN` needs the shell environment for any other tool (only `.env` is set).
- Whether `use_metrics=True` works on Resonance, and whether it would pick better qubits.
- Whether the minimum job charge is per job or per second of QPU time, including compilation or overhead.
- Whether the live Garnet and Emerald coupling maps match what the transpile used (it used the maps the backend returned,
  so this should hold; edge-for-edge comparison with the fake was not made).

## 7. Run log

Comparison tool: `scripts/hardware/compare_run.py <run json>` (project env, read-only, prints only). It checks the QASM
hash, simulates the QASM exactly, and compares per bit, by total variation distance (TVD) and against a seeded shot-noise
floor (20,000 draws of the same number of shots from the ideal distribution).

### Run 1: Garnet, p0, 100 shots

| | |
|---|---|
| Date | 2026-10-08 (record `data/hardware/20261008T173033Z_garnet_p0_100shots.json`) |
| Device, circuit, shots | Garnet, p0, 100 |
| Physical qubits | QB17, QB18, QB19, QB20 |
| CZ | 0 (depth 2, level 3, seed 0) |
| Job id | 01a11c91-1de9-70ca-ad85-8a92260a0ecc |
| Device execution | about 0.1 s (timeline: `execution_started` to `execution_ended`, 0.099 s) |
| Wall clock | 5.9 s (submit to result in the client) |
| Cost | 0.50 credit (from Shah, read from the Resonance account) |
| Credits left | about 279.5 (unconfirmed: 280 from IQM minus 0.50; not read back from the account) |

Cost note: 0.50 credit/s (from IQM, confirm in account) times 0.1 s of execution would be about 0.05 credit, so the charge
is not simply execution time. It equals 1 s at the Garnet rate. That could be a minimum per job; one job cannot show it (see the cost summary after run 6).

Comparison with the exact simulation of `residual_p0.qasm` (hash matches the record; simulated P(opt) = 0.2510686555
equals the gold `sv_p_opt` of row `warm_p0` to 4.8e-11):

| Bit | Asset | Hardware P(1) | Simulated P(1) | Difference | Std errors |
|---|---|---|---|---|---|
| 0 | KESKOB.HE | 0.21 | 0.1678 | +0.042 | +1.13 |
| 1 | KNEBV.HE | 0.58 | 0.5414 | +0.039 | +0.78 |
| 2 | NOKIA.HE | 0.52 | 0.3808 | +0.139 | +2.87 |
| 3 | WRT1V.HE | 0.90 | 0.9000 | 0.000 | 0.00 |

- TVD over all 16 states: 0.170. Shot-noise floor for 100 shots: mean 0.125, 95th percentile 0.177. So the TVD is inside
  the floor.
- Exact optimum `1010` (KNEBV + WRT1V): 20 of 100 shots, simulated 25.1%.
- Four bits were checked, so one large gap is less surprising than it looks.
- One bit (NOKIA) looked high in one 100-shot run; this does not show why. (Not repeated in run 6.)
- This run cannot separate hardware error from sampling noise, and it does not show that the hardware matches the
  simulation either.

### Run 2: Garnet, p1, 100 shots

| | |
|---|---|
| Date | 2026-10-08 (record `data/hardware/20261008T174237Z_garnet_p1_100shots.json`) |
| Device, circuit, shots | Garnet, p1, 100 |
| Physical qubits | QB17, QB18, QB19, QB20 |
| CZ | 16 (depth 33, level 3) |
| Job id | 01a11c9c-29b8-770d-bff0-a8f5b1b29942 |
| Device execution | about 0.14 s (timeline: 0.139 s) |
| Wall clock | 6.5 s |
| Cost | 0.50 credit (from Shah, read from the Resonance account) |

Comparison with the exact simulation of `residual_p1.qasm` (hash matches the record; simulated P(opt) = 0.3494985944,
gold `sv_p_opt` of row `warm_p1_restart` with `selected == True` = 0.3494986001, difference 5.7e-9):

| Bit | Asset | Hardware P(1) | Simulated P(1) | Difference | Std errors |
|---|---|---|---|---|---|
| 0 | KESKOB.HE | 0.15 | 0.0801 | +0.070 | +2.58 |
| 1 | KNEBV.HE | 0.46 | 0.4370 | +0.023 | +0.46 |
| 2 | NOKIA.HE | 0.24 | 0.2459 | -0.006 | -0.14 |
| 3 | WRT1V.HE | 0.85 | 0.9031 | -0.053 | -1.79 |

- Exact optimum `1010`: 31 of 100 shots against 0.3495 simulated.
- TVD 0.123. Shot-noise floor for 100 shots: mean 0.103, 95th percentile 0.155. The TVD is inside the floor.
- Largest single-bit gap is KESKOB (+2.58 standard errors); four bits were checked.

### Run 3: Emerald, p1, 100 shots

| | |
|---|---|
| Date | 2026-10-08 (record `data/hardware/20261008T174724Z_emerald_p1_100shots.json`) |
| Device, circuit, shots | Emerald, p1, 100 |
| Physical qubits | QB1, QB2, QB3, QB4 |
| CZ | 16 (depth 26, level 3) |
| Job id | 01a11ca0-8d4f-741f-890e-431364578fc6 |
| Device execution | about 0.37 s (timeline: `execution_started` to `execution_ended`) |
| Wall clock | 5.7 s |
| Cost | 0.75 credit (from Shah, read from the Resonance account) |

Comparison with the same simulation of `residual_p1.qasm` (same hash and gold row as run 2):

| Bit | Asset | Hardware P(1) | Simulated P(1) | Difference | Std errors |
|---|---|---|---|---|---|
| 0 | KESKOB.HE | 0.09 | 0.0801 | +0.010 | +0.37 |
| 1 | KNEBV.HE | 0.48 | 0.4370 | +0.043 | +0.87 |
| 2 | NOKIA.HE | 0.29 | 0.2459 | +0.044 | +1.02 |
| 3 | WRT1V.HE | 0.83 | 0.9031 | -0.073 | -2.47 |

- Exact optimum `1010`: 33 of 100 shots against 0.3495 simulated.
- TVD 0.111. Same floor as run 2 (mean 0.103, 95th percentile 0.155). The TVD is inside the floor.
- Largest single-bit gap is WRT1V (-2.47 standard errors); four bits were checked.

### Run 4: Garnet, p1, 1000 shots

| | |
|---|---|
| Date | 2026-10-08 (record `data/hardware/20261008T180009Z_garnet_p1_1000shots.json`) |
| Device, circuit, shots | Garnet, p1, 1000 |
| Physical qubits | QB17, QB18, QB19, QB20 |
| CZ | 16 (depth 33, level 3) |
| Job id | 01a11cac-377e-74de-a377-8dc4c57befdf |
| Device execution | about 0.40 s (timeline: 0.397 s) |
| Wall clock | 8.0 s |
| Cost | 0.50 credit (balance 278.25 to 277.75, read by Shah in the Resonance account) |

Comparison with the exact simulation of `residual_p1.qasm` (same hash and gold row as run 2):

| Bit | Asset | Hardware P(1) | Simulated P(1) | Difference | Std errors |
|---|---|---|---|---|---|
| 0 | KESKOB.HE | 0.11 | 0.0801 | +0.028 | +3.26 |
| 1 | KNEBV.HE | 0.45 | 0.4370 | +0.009 | +0.57 |
| 2 | NOKIA.HE | 0.30 | 0.2459 | +0.053 | +3.90 |
| 3 | WRT1V.HE | 0.87 | 0.9031 | -0.034 | -3.64 |

- Exact optimum `1010`: 302 of 1000 shots against 0.3495 simulated.
- TVD 0.083. Shot-noise floor for 1000 shots: mean 0.033, 95th percentile 0.049. The TVD is above the floor.

### Run 5: Emerald, p1, 1000 shots

| | |
|---|---|
| Date | 2026-10-08 (record `data/hardware/20261008T180504Z_emerald_p1_1000shots.json`) |
| Device, circuit, shots | Emerald, p1, 1000 |
| Physical qubits | QB1, QB2, QB3, QB4 |
| CZ | 16 (depth 26, level 3) |
| Job id | 01a11cb0-b8af-76a2-a1f1-ba34ac40bb89 |
| Device execution | about 0.72 s (timeline: 0.718 s) |
| Wall clock | 27.6 s |
| Cost | 0.75 credit (balance 277.75 to 277.00, read by Shah in the Resonance account) |

Comparison with the same simulation of `residual_p1.qasm`:

| Bit | Asset | Hardware P(1) | Simulated P(1) | Difference | Std errors |
|---|---|---|---|---|---|
| 0 | KESKOB.HE | 0.08 | 0.0801 | +0.004 | +0.46 |
| 1 | KNEBV.HE | 0.50 | 0.4370 | +0.059 | +3.76 |
| 2 | NOKIA.HE | 0.29 | 0.2459 | +0.041 | +3.02 |
| 3 | WRT1V.HE | 0.82 | 0.9031 | -0.079 | -8.46 |

- Exact optimum `1010`: 333 of 1000 shots against 0.3495 simulated.
- TVD 0.112 (0.1125). Same floor as run 4 (mean 0.033, 95th percentile 0.049). The TVD is above the floor.

### Run 6: Garnet, p0, 1000 shots

| | |
|---|---|
| Date | 2026-10-08 (record `data/hardware/20261008T180857Z_garnet_p0_1000shots.json`) |
| Device, circuit, shots | Garnet, p0, 1000 |
| Physical qubits | QB17, QB18, QB19, QB20 |
| CZ | 0 (depth 2, level 3) |
| Job id | 01a11cb4-480a-7047-86cb-6eb744bb11c3 |
| Device execution | about 0.39 s (timeline: 0.390 s) |
| Wall clock | 5.6 s |
| Cost | 0.50 credit (balance 277.00 to 276.50, read by Shah in the Resonance account) |

Comparison with the exact simulation of `residual_p0.qasm` (same hash and gold row as run 1):

| Bit | Asset | Hardware P(1) | Simulated P(1) | Difference | Std errors |
|---|---|---|---|---|---|
| 0 | KESKOB.HE | 0.18 | 0.1678 | +0.011 | +0.94 |
| 1 | KNEBV.HE | 0.52 | 0.5414 | -0.020 | -1.29 |
| 2 | NOKIA.HE | 0.38 | 0.3808 | -0.002 | -0.11 |
| 3 | WRT1V.HE | 0.91 | 0.9000 | +0.010 | +1.05 |

- Exact optimum `1010`: 236 of 1000 shots against 0.2511 simulated.
- TVD 0.031. Shot-noise floor for 1000 shots from this distribution: mean 0.039, 95th percentile 0.056. The TVD is inside
  the floor.

My numbers for runs 4-6 equal the hand check (302/1000 and TVD 0.083; 333/1000 and 0.112; 236/1000 and 0.031).

### Cost summary after six jobs

- Six jobs, 3.50 credits used: 0.50 + 0.50 + 0.75 (runs 1-3, balance 278.25) and 0.50 + 0.75 + 0.50 (runs 4-6). Balance
  276.50 (from 280, from IQM). The balances after runs 4, 5 and 6 were read by Shah in the Resonance account.
- A flat one-second charge at each device's rate (Garnet 0.50 credit/s, Emerald 0.75 credit/s, both from IQM, confirm in
  account) fits all six jobs. This is an assumption, and it rests on short jobs only: device execution 0.1-0.72 s, 100 or
  1000 shots, 4 qubits. The six jobs do not show how the charge grows for longer or larger ones.

### Observation: p0 matched within noise, p1 did not

- WRT1V read below the simulated value in all four p1 runs (0.85 and 0.83 at 100 shots; 0.87 on Garnet and 0.82 on Emerald
  at 1000 shots; simulated 0.903) but matched in the Garnet p0 run at 1000 shots (0.91; simulated 0.9000).
- The NOKIA reading in run 1 (0.52 against 0.3808) was not repeated in run 6 (0.38 against 0.3808), and run 1 sat inside
  its shot-noise floor. The run 1 reading is consistent with shot noise (run 1 TVD was inside its noise floor and run 6 did
  not repeat the reading).
- Per bit at 1000 shots, in standard errors with the simulated probability as the base: in run 4 (Garnet, p1) KESKOB is
  +3.26, NOKIA +3.90, WRT1V -3.64 and KNEBV +0.57; in run 5 (Emerald, p1) KNEBV is +3.76, NOKIA +3.02, WRT1V -8.46 and
  KESKOB +0.46. In each 1000-shot p1 run three of the four bits are off by about 3 standard errors or more; which bit
  stays close differs by device, so no single asset is singled out. The WRT1V bit is the only one low in all four, and
  the deviations are not confined to it.
- p0 matched the ideal within noise on Garnet (run 6, TVD 0.031 inside the floor 0.056).
- p1 differed by more than noise on both devices (TVD 0.083 on Garnet and 0.112 on Emerald, against a 95th percentile of
  0.049).
- The cause is not isolated. p1 has CZ gates (16), more single-qubit gates and a longer depth (33 on Garnet, 26 on
  Emerald) than p0, and the runs do not separate these. Emerald p0 was not run.
- No claim about which device is better: the two p1 jobs used different circuits after transpiling (different depths) and
  different physical qubits, with one job each at 1000 shots. The transpiler chose the qubits without calibration data
  (`use_metrics=False`, section 3), so the qubit choice was not checked against device quality.

### Planned runs: all done

| Planned | Done as |
|---|---|
| p0 Garnet, 100 shots | run 1 |
| p1 Garnet, 100 shots | run 2 |
| p1 Emerald, 100 shots | run 3 |
| p1 Garnet, 1000 shots | run 4 |
| p1 Emerald, 1000 shots | run 5 |
| p0 Garnet, 1000 shots | run 6 |

No further runs are planned. Stop if one job costs more than about 5 credits.

### Open questions (additional to section 6)

- Do the 250 credits expire?
- Is 0.50 credit a minimum per job? (Six short jobs fit a flat one-second charge, see the cost summary.)
- What separates p1 from p0 on the hardware: CZ gates, single-qubit gates or depth? (Not isolated.)
