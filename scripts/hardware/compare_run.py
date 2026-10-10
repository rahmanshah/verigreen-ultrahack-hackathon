# Environment: PROJECT env (.venv, qiskit 2.5.2). Read-only: prints to the terminal, writes nothing.
# What it does: compares one hardware run record (data/hardware/*.json) with the exact statevector simulation of the QASM
#   named in the record: sha256 check, P(opt) against the gold sv_p_opt, per-bit P(1) with differences in standard
#   errors, total variation distance (TVD) over the full distribution, a seeded shot-noise floor, and how often the exact
#   optimum bitstring appeared. Does not contact IQM, needs no token, submits nothing.
# Run (from the repo root, no bytecode written):
#   $env:PYTHONDONTWRITEBYTECODE='1'
#   .venv\Scripts\python.exe scripts\hardware\compare_run.py data\hardware\<run>.json
# Date: 2026-10-08
"""Project env, read-only: compare a hardware run record with the exact simulation of its circuit.

Usage: python compare_run.py <hardware_run_json>
"""
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from qiskit import qasm2
from qiskit.quantum_info import Statevector

REPO = Path(__file__).resolve().parents[2]
QASM_DIR = REPO / "qasm" / "residual_fy2024"
GOLD_SIM = REPO / "data" / "gold" / "qaoa_stage_h3_simulation_fy2024.csv"
GOLD_INSTANCE = REPO / "data" / "gold" / "qaoa_stage_h3_instance_fy2024.csv"
SV_TOL = {"p0": 1e-8, "p1": 1e-5}  # p1 angles are rounded to 6 decimals in the QASM (docs/hardware_prep.md)
DRAWS, SEED = 20_000, 0


def gold_row(circuit: str) -> tuple[dict, str]:
    """The gold row that describes this circuit, and a sentence saying which one it is."""
    with open(GOLD_SIM, newline="") as f:
        rows = list(csv.DictReader(f))
    if circuit == "p0":
        match = [r for r in rows if r["row"] == "warm_p0"]
        why = "row 'warm_p0'"
    elif circuit == "p1":
        match = [r for r in rows if r["row"] == "warm_p1_restart" and r["selected"] == "True"]
        why = "row 'warm_p1_restart' with selected == True (the restart the exported angles come from)"
    else:
        sys.exit(f"STOP: no gold row rule for circuit {circuit!r}.")
    if len(match) != 1:
        sys.exit(f"STOP: expected exactly one gold row for {circuit}, found {len(match)}.")
    return match[0], why


def analyse(path: Path) -> dict:
    """Everything compare_run prints, as numbers. Reads files only; exits with a STOP message on any mismatch.

    Imported by export_hardware_summary.py so the app files and this script share one computation.
    """
    rec = json.loads(path.read_text())
    counts, shots, circuit = rec["counts"], rec["shots"], rec["circuit"]
    if not counts or sum(counts.values()) != shots:
        sys.exit(f"STOP: counts missing or do not add up to shots={shots} (status: {rec.get('status')}).")

    # 1. QASM identity
    qasm_path = QASM_DIR / rec["qasm_file"]
    sha = hashlib.sha256(qasm_path.read_text().encode()).hexdigest()
    if sha != rec["qasm_sha256"]:
        sys.exit(f"STOP: sha256 of {qasm_path.name} is {sha}, the record says {rec['qasm_sha256']}. Not comparing.")

    # 2. Exact simulation (no measurement needed); index i has bit k = (i >> k) & 1, i.e. rightmost character = bit 0
    qc = qasm2.loads(qasm_path.read_text())
    n = qc.num_qubits
    sim = Statevector(qc).probabilities()
    row, why = gold_row(circuit)
    gold_p_opt = float(row["sv_p_opt"])
    exact_sel = set(row["exact_selection"].split(";"))
    with open(GOLD_INSTANCE, newline="") as f:
        names = [r["asset"] for r in csv.DictReader(f) if r["role"] == "undecided"]
    if len(names) != n:
        sys.exit(f"STOP: {len(names)} undecided assets in the gold instance, but the circuit has {n} qubits.")
    opt_idx = sum(1 << k for k, a in enumerate(names) if a in exact_sel)
    opt_bits = format(opt_idx, f"0{n}b")
    diff = abs(sim[opt_idx] - gold_p_opt)

    # hardware distribution; int(key, 2) puts the rightmost character at bit 0
    hw = np.zeros(2**n)
    for key, c in counts.items():
        if len(key) != n or set(key) - {"0", "1"}:
            sys.exit(f"STOP: unexpected counts key {key!r} for a {n}-bit circuit.")
        hw[int(key, 2)] += c / shots

    # 3. per bit
    h_bit, s_bit, zs = [], [], []
    for b in range(n):
        h = hw[[i for i in range(2**n) if (i >> b) & 1]].sum()
        s = sim[[i for i in range(2**n) if (i >> b) & 1]].sum()
        se = np.sqrt(s * (1 - s) / shots)
        h_bit.append(h)
        s_bit.append(s)
        zs.append((h - s) / se if se > 0 else float("nan"))

    # 4. TVD
    tvd = 0.5 * np.abs(hw - sim).sum()

    # 5. shot-noise floor
    rng = np.random.default_rng(SEED)
    floor = np.array([0.5 * np.abs(rng.multinomial(shots, sim) / shots - sim).sum() for _ in range(DRAWS)])
    p95 = float(np.percentile(floor, 95))

    return dict(rec=rec, counts=counts, shots=shots, circuit=circuit, qasm_name=qasm_path.name, n=n, sim=sim, hw=hw,
                names=names, exact_sel=exact_sel, opt_idx=opt_idx, opt_bits=opt_bits, gold_p_opt=gold_p_opt, diff=diff,
                why=why, h_bit=h_bit, s_bit=s_bit, zs=zs, tvd=tvd, floor_mean=float(floor.mean()), p95=p95)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    path = Path(sys.argv[1])
    r = analyse(path)
    rec, counts, shots, circuit, n = r["rec"], r["counts"], r["shots"], r["circuit"], r["n"]
    sim, hw, names, zs = r["sim"], r["hw"], r["names"], r["zs"]
    opt_idx, opt_bits, tvd, p95 = r["opt_idx"], r["opt_bits"], r["tvd"], r["p95"]

    print(f"run:      {path.name}  ({rec['device']}, {circuit}, {shots} shots)")
    print(f"qasm:     {r['qasm_name']}  sha256 matches the record")
    print(f"\nexact optimum: {sorted(r['exact_sel'])} -> bitstring {opt_bits} (index {opt_idx})")
    print(f"P(opt) simulated = {sim[opt_idx]:.10f}")
    print(f"gold sv_p_opt    = {r['gold_p_opt']:.10f}  [{r['why']}]")
    diff = r["diff"]
    print(f"difference {diff:.1e} -> " + (f"matches (tolerance {SV_TOL[circuit]:.0e})" if diff <= SV_TOL[circuit]
                                         else f"DOES NOT MATCH (tolerance {SV_TOL[circuit]:.0e})"))

    print("\nbit  asset        hardware P(1)  simulated P(1)  diff     diff in std errors")
    for b in range(n):
        h, s, z = r["h_bit"][b], r["s_bit"][b], zs[b]
        print(f" {b}   {names[b]:11s}  {h:.2f}           {s:.4f}          {h - s:+.4f}   {z:+.2f}")

    print(f"\nTVD(hardware, simulated), all {2**n} states = {tvd:.4f}")
    print(f"shot-noise floor ({DRAWS} draws of {shots} shots from the ideal distribution, seed {SEED}): "
          f"mean {r['floor_mean']:.3f}, 95th percentile {p95:.3f}")

    print(f"\nexact optimum {opt_bits}: hardware {counts.get(opt_bits, 0)} of {shots} "
          f"({hw[opt_idx]:.2f}) vs simulated {sim[opt_idx]:.4f}")

    # 7. what the data can and cannot show
    big = int(np.nanargmax(np.abs(zs)))
    if tvd <= p95:
        verdict = (f"TVD {tvd:.3f} is inside the shot-noise floor (95th percentile {p95:.3f}), so this run cannot "
                   f"separate hardware error from sampling noise, and it does not show that the hardware matches the "
                   f"simulation either")
    else:
        verdict = (f"TVD {tvd:.3f} is above the shot-noise floor (95th percentile {p95:.3f}), so the distribution "
                   f"differs from the ideal by more than sampling noise alone usually gives, but the data do not show why")
    print(f"\n{verdict}; the largest single-bit gap is {names[big]} ({zs[big]:+.2f} standard errors), and because "
          f"{n} bits were checked, one large gap is less surprising than it looks.")


if __name__ == "__main__":
    main()
