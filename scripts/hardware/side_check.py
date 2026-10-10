# Environment: SIDE env (outside the repo: <venvs>\verigreen-iqm; qiskit 2.1.2, qiskit-aer 0.17.2, iqm-client 35.0.3).
#   Do not run this in the project env: the IQM adapter is not installed there.
# What it does: reloads the QASM files written by export_qasm.py, checks them against the project-env Aer probabilities
#   (tolerance 1e-9, stops on failure), then transpiles p=0 and p=1 for the offline IQM fake backends (optimisation
#   levels 1 and 3, seeds 0-9) and reports CZ, depth, SWAP and the physical qubits chosen. Offline only: no network,
#   no token. See docs/hardware_prep.md.
# Run (from outside the repo, e.g. <venvs>):
#   $env:PYTHONDONTWRITEBYTECODE='1'
#   <side env>\Scripts\python.exe <repo>\scripts\hardware\side_check.py <repo>\qasm\residual_fy2024 <reference.json> <results.json>
# Date: 2026-10-07
"""Side env: reload QASM, compare with project-env Aer probabilities, then offline IQM transpiles.

Usage: python side_check.py <qasm_dir> <reference_json> <results_json>
"""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from qiskit import qasm2, transpile
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_aer import AerSimulator

from iqm.qiskit_iqm.fake_backends import IQMFakeAdonis, IQMFakeAphrodite, IQMFakeApollo, IQMFakeDeneb
from iqm.qiskit_iqm.fake_backends.fake_garnet import IQMFakeGarnet

QASM_DIR, REF, OUT = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text()), Path(sys.argv[3])
TOL = 1e-9
feasible = np.array(REF["feasible"], bool)
opt = REF["opt_index"]


def aer_probs(circuit) -> np.ndarray:
    qc = circuit.copy()
    qc.save_statevector()
    sim = AerSimulator(method="statevector")
    return np.abs(np.asarray(sim.run(transpile(qc, sim, optimization_level=0)).result().get_statevector())) ** 2


circuits, report = {}, {"equivalence": {}, "sha256": {}, "transpile": {}}
ok = True
for p in (0, 1):
    path = QASM_DIR / f"residual_p{p}.qasm"
    report["sha256"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    qc = qasm2.loads(path.read_text(encoding="utf-8"))
    circuits[p] = qc
    probs = aer_probs(qc)
    ref = np.array(REF["probs"][str(p)])
    diff = float(np.abs(probs - ref).max())
    pof_side = float(probs[opt] / probs[feasible].sum())
    pof_ref = float(ref[opt] / ref[feasible].sum())
    gold = REF["gold_sv_p_opt"][str(p)]
    report["equivalence"][p] = {"max_abs_diff_16_probs": diff, "pass_1e-9": diff < TOL, "n_states": len(probs),
                                "P_opt_side": float(probs[opt]), "P_opt_gold": gold, "diff_vs_gold": abs(float(probs[opt]) - gold),
                                "P_opt_given_feasible_side": pof_side, "P_opt_given_feasible_project": pof_ref,
                                "diff_pof": abs(pof_side - pof_ref)}
    ok &= diff < TOL and abs(pof_side - pof_ref) < TOL
    print(f"p={p}: max|side - project| over 16 probs = {diff:.3e} ({'PASS' if diff < TOL else 'FAIL'}); "
          f"P(opt) {probs[opt]:.10f} (gold {gold:.10f}, diff {abs(probs[opt] - gold):.2e}); "
          f"P(opt|feasible) {pof_side:.10f} vs project {pof_ref:.10f}")
    print("   sha256", report["sha256"][path.name])
if not ok:
    OUT.write_text(json.dumps(report, indent=1))
    sys.exit("EQUIVALENCE FAILED - stopping before transpile")

backends = {"Adonis(5q)": IQMFakeAdonis(), "Deneb(6q)": IQMFakeDeneb(), "Apollo(20q)": IQMFakeApollo(),
            "Garnet(20q)": IQMFakeGarnet(), "Aphrodite(54q)": IQMFakeAphrodite()}


def edges(b):
    return sorted({tuple(sorted(e)) for e in b.coupling_map.get_edges()})


report["garnet_equals_apollo_edges"] = edges(backends["Garnet(20q)"]) == edges(backends["Apollo(20q)"])
report["garnet_qubit_names_equal_apollo"] = (
    [backends["Garnet(20q)"].index_to_qubit_name(i) for i in range(20)] == [backends["Apollo(20q)"].index_to_qubit_name(i) for i in range(20)])
report["backends"] = {n: {"qubits": b.num_qubits, "edges": len(edges(b)), "ops": sorted(b.operation_names)} for n, b in backends.items()}


def run_one(circuit, backend, level, seed):
    qc = circuit.copy()
    qc.measure_all()
    pm = generate_preset_pass_manager(optimization_level=level, backend=backend, seed_transpiler=seed)
    swaps = [0]

    def cb(**kw):
        swaps[0] = max(swaps[0], kw["dag"].count_ops().get("swap", 0))

    t = pm.run(qc, callback=cb)
    ops = t.count_ops()
    active = sorted({t.find_bit(q).index for i in t.data if i.operation.name != "barrier" for q in i.qubits})
    return {"cz": int(ops.get("cz", 0)), "depth": t.depth(), "swaps": swaps[0], "other_2q": {k: v for k, v in ops.items() if k not in ("r", "cz", "measure", "barrier")},
            "qubits": active}


for name, b in backends.items():
    for p in (0, 1):
        for level in (1, 3):
            rows = [run_one(circuits[p], b, level, s) for s in range(10)]
            cz, dp, sw = (np.array([r[k] for r in rows]) for k in ("cz", "depth", "swaps"))
            sets = Counter(tuple(r["qubits"]) for r in rows)
            names = lambda qs: " ".join(b.index_to_qubit_name(i) for i in qs)
            report["transpile"][f"{name}|p{p}|L{level}"] = {
                "cz": [int(cz.min()), float(np.median(cz)), int(cz.max())], "depth": [int(dp.min()), float(np.median(dp)), int(dp.max())],
                "swaps": [int(sw.min()), float(np.median(sw)), int(sw.max())],
                "other_2q_ops": sorted({k for r in rows for k in r["other_2q"]}),
                "qubit_sets": [{"n_seeds": n, "indices": list(s), "names": names(s)} for s, n in sets.most_common()],
                "per_seed": rows}
            print(f"{name:15s} p={p} L{level}: CZ {cz.min()}/{np.median(cz):g}/{cz.max()}  depth {dp.min()}/{np.median(dp):g}/{dp.max()}  "
                  f"SWAP {sw.min()}/{np.median(sw):g}/{sw.max()}  distinct qubit sets {len(sets)}  e.g. {names(sets.most_common(1)[0][0])}")
OUT.write_text(json.dumps(report, indent=1))
print("garnet edges == apollo edges:", report["garnet_equals_apollo_edges"], "; qubit names equal:", report["garnet_qubit_names_equal_apollo"])
