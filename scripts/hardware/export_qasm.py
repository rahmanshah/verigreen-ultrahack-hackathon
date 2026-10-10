# Environment: PROJECT env (.venv, qiskit 2.5.2). Read-only on the repo apart from writing the QASM files.
# What it does: builds the stage H3 residual (4-qubit) warm-start QAOA circuits p=0 and p=1 with build_residual() and
#   sizing_circuit(), exports them as OpenQASM 2 (u -> u3 and p -> u1, same angles) and saves the Aer probability vectors
#   to a reference JSON for side_check.py. p=1 uses the rounded point from restart 6 in
#   data/gold/qaoa_stage_h3_simulation_fy2024.csv. See docs/hardware_prep.md.
# Run (from the repo root, no bytecode written):
#   $env:PYTHONDONTWRITEBYTECODE='1'; $env:PYTHONPATH=<repo root>
#   .venv\Scripts\python.exe scripts\hardware\export_qasm.py qasm\residual_fy2024 <reference.json>
# Date: 2026-10-07
"""Project env, read-only: build residual p=0/p=1 circuits, export QASM 2, save reference probabilities.

Usage: python export_qasm.py <qasm_dir> <reference_json>
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from qiskit import qasm2, transpile
from qiskit_aer import AerSimulator

from verigreen.qaoa import penalty_variants, reference
from verigreen.stage_gh import build_residual, sizing_circuit

QASM_DIR, REF_JSON = Path(sys.argv[1]), Path(sys.argv[2])
POINT = np.array([3.549169, 0.238852])     # [beta_1, gamma_1], selected restart 6 in qaoa_stage_h3_simulation_fy2024.csv
GOLD = {0: 0.2510686555, 1: 0.3494986001}  # sv_p_opt in the same file (warm_p0; selected warm_p1_restart)

res = build_residual()
inst = res.instance
q = penalty_variants(inst.qubo)["practical"]
ref = reference(q)
print("assets", inst.assets, "k", q.k, "opt_index", ref.opt_index, "n_feasible", int(ref.feasible.sum()))


def aer_probs(circuit) -> np.ndarray:
    qc = circuit.copy()
    qc.save_statevector()
    sim = AerSimulator(method="statevector")
    sv = sim.run(transpile(qc, sim, optimization_level=0)).result().get_statevector()
    return np.abs(np.asarray(sv)) ** 2


def flat(circuit):
    from qiskit.circuit import QuantumCircuit
    from qiskit.circuit.library import U3Gate
    c = circuit
    for _ in range(12):
        if all(i.operation.name in {"h", "x", "ry", "rx", "rz", "rzz", "cx", "cz", "p", "u", "u1", "u2", "u3", "id", "sx"}
               for i in c.data):
            break
        c = c.decompose()
    else:
        raise RuntimeError(f"could not reduce to standard gates: {dict(c.count_ops())}")
    # `u` and `p` are not in qelib1.inc; u(a, b, c) == u3(a, b, c) and p(l) == u1(l) exactly, same angles
    out = QuantumCircuit(*c.qregs, *c.cregs, name=c.name, global_phase=c.global_phase)
    from qiskit.circuit.library import U1Gate
    for i in c.data:
        name = i.operation.name
        op = (U3Gate(*i.operation.params) if name == "u" else U1Gate(*i.operation.params) if name == "p" else i.operation)
        out.append(op, i.qubits, i.clbits)
    return out


def param_values(circuit):
    return np.array([float(p) for i in circuit.data for p in i.operation.params])


out = {"assets": list(inst.assets), "k": q.k, "opt_index": ref.opt_index, "feasible": ref.feasible.astype(int).tolist(),
       "point": POINT.tolist(), "gold_sv_p_opt": GOLD, "probs": {}}
QASM_DIR.mkdir(parents=True, exist_ok=True)
for p in (0, 1):
    orig = sizing_circuit(inst, p, POINT if p else None)
    f = flat(orig)
    probs = aer_probs(orig)
    probs_flat = aer_probs(f)
    text = qasm2.dumps(f)
    header = (f"// VeriGreen stage H3 residual subproblem, FY2024 MAIN trusted, warm-start QAOA p={p}\n"
              f"// assets (qubit 0..3): {' '.join(inst.assets)}; K_res = {q.k}; exact optimum index {ref.opt_index} (little-endian)\n"
              f"// source: build_residual() -> sizing_circuit(res.instance, {p}"
              + (", point=[3.549169, 0.238852])" if p else ")") + "\n"
              + ("// point = [beta_1, gamma_1], selected warm_p1_restart (restart 6) in data/gold/qaoa_stage_h3_simulation_fy2024.csv\n"
                 if p else "// p=0: warm-start initial state only, no parameters\n")
              + "// global phase is dropped by QASM 2 (does not affect probabilities)\n")
    path = QASM_DIR / f"residual_p{p}.qasm"
    path.write_bytes((header + text).encode("utf-8"))
    back = qasm2.loads(path.read_text(encoding="utf-8"))
    pv_f, pv_b = param_values(f), param_values(back)
    angle_diff = float(np.abs(pv_f - pv_b).max()) if len(pv_f) else 0.0
    probs_back = aer_probs(back)
    feas = ref.feasible
    pof = probs[ref.opt_index] / probs[feas].sum()
    print(f"p={p}: gates {dict(f.count_ops())}; n_angles {len(pv_f)}; max |angle(flat) - angle(reloaded in project env)| = {angle_diff:.3e}")
    print(f"   max|orig - decomposed| = {np.abs(probs - probs_flat).max():.3e}; max|orig - reloaded(project env)| = {np.abs(probs - probs_back).max():.3e}")
    print(f"   P(opt) = {probs[ref.opt_index]:.10f}  gold {GOLD[p]:.10f}  diff {abs(probs[ref.opt_index] - GOLD[p]):.2e};  "
          f"P(opt|feasible) = {pof:.10f};  feasible share {probs[feas].sum():.6f}")
    print("   sha256", hashlib.sha256(path.read_bytes()).hexdigest())
    out["probs"][str(p)] = probs.tolist()
REF_JSON.write_text(json.dumps(out, indent=1), encoding="utf-8")
