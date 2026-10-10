# Hardware prep: IQM side environment and offline transpile check

Date: 7 Oct 2026. Offline only: no IQM server contact, no token, no credits, no job submitted.
Question answered: do the 4-qubit residual circuits (stage H3) transpile for IQM backends, and is the exported
OpenQASM identical in behaviour to the circuits we simulated?

## 1. Why a separate environment

`iqm-client[qiskit]` needs qiskit < 2.2. The project pins qiskit 2.5.2 (see `pyproject.toml`), so IQM cannot be
installed in the project environment. IQM work runs in a **side environment outside the repo**:

| | Project env (`.venv`) | Side env |
|---|---|---|
| Location | repo `.venv` | `<venvs>\verigreen-iqm` |
| qiskit | 2.5.2 | 2.1.2 |
| qiskit-aer | 0.17.2 | 0.17.2 |
| iqm-client | not installed | 35.0.3 |
| numpy | 2.4.4 | 2.5.3 |

The project environment, `pyproject.toml`, `uv.lock` and `requirements.txt` were not changed (SHA-256 and
`uv pip freeze` compared before and after: identical).

Exact commands (PowerShell, run from **outside** the repo so uv does not pick up the project):

```
cd <venvs>
uv venv --python 3.12 verigreen-iqm
uv pip install --dry-run --python <venvs>\verigreen-iqm\Scripts\python.exe "qiskit==2.1.2" "qiskit-aer==0.17.2" numpy "iqm-client[qiskit]"
uv pip install --python <venvs>\verigreen-iqm\Scripts\python.exe "qiskit==2.1.2" "qiskit-aer==0.17.2" numpy "iqm-client[qiskit]"
```

Run the dry run first and read the resolved versions before installing.

## 2. The resolver trap

When resolving against the **project pins** (qiskit 2.5.2), the resolver quietly settles on an old `iqm-client`
(22.x) that has **no qiskit adapter**. The install succeeds, so nothing warns you. This was observed in the earlier
compatibility session. In the **side env** (qiskit 2.1.2) the resolver picks iqm-client 35.0.3, so the trap does not
occur there. Still check after every install:

```
<side env>\Scripts\python.exe -c "import importlib.metadata as m; print(m.version('iqm-client')); from iqm.qiskit_iqm import IQMProvider; print('ok')"
```

If the import fails, stop. On 7 Oct, with the side-env pins above, the resolver chose iqm-client 35.0.3 and the
import worked.

## 3. The QASM files

Folder `qasm/residual_fy2024/` (OpenQASM 2, untracked at the time of writing). QASM 2 was chosen because
`qiskit.qasm2.loads` needs no extra package (QASM 3 import needs `qiskit_qasm3_import`).

| File | SHA-256 |
|---|---|
| `residual_p0.qasm` | `ab3f1c4b0fb00d7b9a2d1d73726b4573f478821b1c1b3bb582d624c9b4e507b9` |
| `residual_p1.qasm` | `46029f5534933eeccce10f154264f8bf844f8e53b88418e2ac8f9027a6fd8c99` |

- Instance: FY2024 MAIN trusted, 4 undecided assets (KESKOB.HE, KNEBV.HE, NOKIA.HE, WRT1V.HE), K_res = 2, from
  `build_residual()` then `sizing_circuit(res.instance, p, point)` in `verigreen/stage_gh.py`.
- p=0: warm-start initial state only, no parameters.
- p=1 point `[beta_1, gamma_1] = [3.549169, 0.238852]`: row `warm_p1_restart` with `selected == True` (restart 6, seed
  20261112), column `optimal_point`, in `data/gold/qaoa_stage_h3_simulation_fy2024.csv`. That column is rounded to
  6 decimals, so P(opt) matches the gold `sv_p_opt` to about 1e-8, not exactly.
- Note: the existing H3 sizing CSV (`qaoa_stage_h3_sizing_fy2024.csv`) used the placeholder angle 0.37 (the default of
  `sizing_circuit`), not these tuned values. Gate counts do not depend on the angles.
- Substitution: after decomposing, the circuit contains `u` and `p` gates, which `qasm2.loads` rejects (not in
  `qelib1.inc`). They were written as `u3` and `u1` with identical angles (`u(a,b,c) = u3(a,b,c)`, `p(l) = u1(l)`).
  Angles are written with 16 significant digits and reload with a maximum difference of 0. QASM 2 drops the global
  phase, which does not change probabilities.

## 4. Equivalence check

Original circuit simulated in the project env, re-loaded QASM simulated in the side env, both with Aer statevector,
all 16 probabilities compared (tolerance 1e-9, not loosened).

| | p=0 | p=1 |
|---|---|---|
| Max difference over 16 probabilities | 0 | 1.1e-16 |
| P(opt) | 0.2510686555 | 0.3494985944 |
| Difference vs gold `sv_p_opt` (limit 1e-5) | 4.8e-11 | 5.7e-9 |
| P(opt given feasible), side env vs project env | 0.5573478104 (identical) | 0.5680662176 (identical) |

## 5. Offline IQM transpile

Backends are the fake ones shipped in `iqm.qiskit_iqm.fake_backends` (Garnet is the factory `IQMFakeGarnet()` in
`fake_garnet.py`). `generate_preset_pass_manager(optimization_level=L, backend=fake, seed_transpiler=s)`, seeds 0-9,
`measure_all()` added first. p=0 gives 0 CZ, 0 SWAP and depth 2 everywhere. Table is p=1, min / median / max over
10 seeds; depth includes the measurement layer.

| Backend | Level | CZ | Depth | SWAP |
|---|---|---|---|---|
| Garnet 20q (Apollo identical) | 1 | 18 / 18 / 18 | 30 / 33 / 35 | 2 / 2 / 2 |
| Garnet 20q | 3 | 16 / 18 / 18 | 33 / 36 / 38 | 2 / 2 / 2 |
| Adonis 5q | 1 | 18 / 18 / 18 | 33 / 33.5 / 35 | 2 / 2 / 2 |
| Adonis 5q | 3 | 16 / 18 / 18 | 32 / 36 / 37 | 2 / 2 / 2 |
| Aphrodite 54q | 1 | 18 / 18 / 18 | 28 / 31 / 35 | 2 / 2 / 2 |
| Aphrodite 54q | 3 | 16 / 18 / 18 | 26 / 35 / 38 | 2 / 2 / 2 |
| Deneb 6q (star) | 1 | 12 / 12 / 12 | 32 / 32 / 32 | 0 (12 MOVE) |
| Deneb 6q (star) | 3 | 12 / 12 / 12 | 45 / 45 / 45 | 0 (22 MOVE) |

- SWAP = highest SWAP count in the circuit after any transpiler pass (the routed circuit before CZ translation).
  12 logical CZ + 2 SWAP x 3 CZ = 18; level 3 cancels some, giving 16.
- Garnet vs Crystal 20: the fake Garnet reuses the Apollo architecture; edges (30) and qubit names are identical to
  Apollo's, and the package's own demo calls Apollo "Crystal-20".
- Physical qubits on Garnet: QB17-QB20 in 8 of 10 seeds (level 1) and 7 of 10 (level 3); the rest add one more qubit
  (QB7, QB15 or QB4).
- Versus the IBM stand-in maps (gold sizing, level 3, 20 seeds, no measurement layer): p=1 12 CZ all-to-all, 14-18
  (median 18) on a 2 x 2 grid, 17-19 (median 17) on a line. Garnet at level 3 (16-18, median 18) is comparable to the
  2 x 2 grid, not better. Seed counts differ (10 vs 20).

## 6. Caveats

- These are **fake backends**: a fixed topology and a baked-in error profile. Live qubit selection and calibration
  can only happen on the real device. I did not check whether the fake error profile influenced qubit choice.
- **Deneb numbers are not a hardware number.** The fake treats the central resonator (CR1) as an ordinary qubit and the
  transpiler inserts MOVE gates. I did not check that against how the real Deneb works.
- **No fake Emerald exists** in iqm-client 35.0.3. Aphrodite (54 qubits) is the only 54-qubit fake; that it matches
  Emerald is recalled, not verified.
- Whether the real Garnet's live coupling map equals the fake's needs the device.

## 7. Verified vs not verified

Verified (run on 7 Oct 2026): side env versions and the `IQMProvider` import; fake backends present; Garnet and
Apollo edge-for-edge identical; QASM equivalence (section 4); both SHA-256 hashes; the transpile table; unchanged
project environment.

Verified in an earlier session on 7 Oct 2026: Observed in the earlier compatibility session
(resolver output, resolving against the project pins, qiskit 2.5.2): the resolver silently picked iqm-client 22.4 with
no qiskit extra. Not re-run in this session, because the side env uses different pins.

Not verified: Emerald equivalence; the real devices' coupling maps, calibration and qubit choice; Deneb resonator
semantics; any actual hardware run (none was made).

## 8. Reproduce

Scripts in `scripts/hardware/` (headers say which environment each runs in):
`export_qasm.py` in the project env, then `side_check.py` in the side env. Use `PYTHONDONTWRITEBYTECODE=1` so no
`__pycache__` is written into the repo.
