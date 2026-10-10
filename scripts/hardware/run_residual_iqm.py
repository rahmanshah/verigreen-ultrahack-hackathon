# Environment: SIDE env (outside the repo: <venvs>\verigreen-iqm; qiskit 2.1.2, iqm-client 35.0.3).
#   Do not run this in the project env: the IQM adapter is not installed there.
# What it does: loads the 4-qubit residual circuit (qasm/residual_fy2024/residual_p0.qasm or residual_p1.qasm), transpiles
#   it locally for the chosen IQM Resonance device and, ONLY with --submit AND --confirm-credits and a typed "yes",
#   submits one job. Without both flags it is a dry run: it connects (device metadata only), transpiles, validates the
#   run request without sending it, prints the summary and stops. Credits are spent only by a submitted job.
# Guards: shots default 100; more than 100 needs --max-shots N (and shots <= N). The token is read from IQM_TOKEN (loaded
#   from the repo .env) and is never printed or written. Each run writes a NEW file in data/hardware/ (never overwrites).
# Run (dry run; submits nothing):
#   $env:PYTHONDONTWRITEBYTECODE='1'
#   <venvs>\verigreen-iqm\Scripts\python.exe scripts\hardware\run_residual_iqm.py --device garnet --circuit p0
# Run (real, spends credits): add  --submit --confirm-credits  and answer "yes" at the prompt.
# Date: 2026-10-08
"""Side env: guarded IQM run of the stage H3 residual circuit. See docs/hardware_iqm_notes.md."""
import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from qiskit import qasm2
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

REPO = Path(__file__).resolve().parents[2]
QASM_DIR = REPO / "qasm" / "residual_fy2024"
OUT_DIR = REPO / "data" / "hardware"
URL = "https://resonance.meetiqm.com"
DEFAULT_SHOTS = 100
OPT_LEVEL = 3
SEEDS = range(10)  # the transpile with the fewest CZ (then the lowest depth, then the lowest seed) is submitted


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--device", required=True, choices=["garnet", "emerald"])
    p.add_argument("--circuit", required=True, choices=["p0", "p1"])
    p.add_argument("--shots", type=int, default=DEFAULT_SHOTS)
    p.add_argument("--max-shots", type=int, default=None, help=f"required to go above {DEFAULT_SHOTS} shots")
    p.add_argument("--submit", action="store_true", help="together with --confirm-credits, submit a real job")
    p.add_argument("--confirm-credits", action="store_true", help="together with --submit, accept that credits are spent")
    p.add_argument("--timeout", type=float, default=1800.0, help="seconds to wait for the result (the job keeps running)")
    return p.parse_args()


def check_args(a: argparse.Namespace) -> None:
    """Refuse bad combinations before any network contact."""
    if a.submit != a.confirm_credits:
        sys.exit("REFUSED: a real run needs BOTH --submit and --confirm-credits. Nothing was sent.")
    if a.shots < 1:
        sys.exit("REFUSED: --shots must be at least 1.")
    if a.shots > DEFAULT_SHOTS and a.max_shots is None:
        sys.exit(f"REFUSED: {a.shots} shots is above {DEFAULT_SHOTS}. Pass --max-shots <number> to allow it.")
    if a.max_shots is not None and a.shots > a.max_shots:
        sys.exit(f"REFUSED: --shots {a.shots} is above --max-shots {a.max_shots}.")


def transpile_best(qc, backend):
    """Level-3 transpile over seeds 0-9; keep the fewest CZ, then the lowest depth, then the lowest seed."""
    best = None
    for seed in SEEDS:
        pm = generate_preset_pass_manager(optimization_level=OPT_LEVEL, backend=backend, seed_transpiler=seed)
        t = pm.run(qc)
        key = (int(t.count_ops().get("cz", 0)), t.depth(), seed)
        if best is None or key < best[0]:
            best = (key, t)
    (cz, depth, seed), t = best
    used = sorted({t.find_bit(q).index for inst in t.data if inst.operation.name != "barrier" for q in inst.qubits})
    names = [backend.index_to_qubit_name(i) for i in used]
    return t, {"cz": cz, "depth": depth, "seed": seed, "physical_qubits": names}


def main() -> None:
    a = parse_args()
    check_args(a)

    load_dotenv(REPO / ".env")
    if not os.environ.get("IQM_TOKEN"):
        sys.exit("IQM_TOKEN is not set (checked the environment and the repo .env). Nothing was sent.")
    print("IQM_TOKEN: set")

    # Imported late so that the argument guards above run without the IQM stack.
    from iqm.qiskit_iqm import IQMProvider

    qasm_path = QASM_DIR / f"residual_{a.circuit}.qasm"
    qasm_text = qasm_path.read_text()
    qc = qasm2.loads(qasm_text)
    qc.measure_all()

    backend = IQMProvider(URL, quantum_computer=a.device).get_backend()  # metadata only, no job
    t, info = transpile_best(qc, backend)
    # Builds and validates the run request WITHOUT sending it (no job is created).
    backend.create_run_request(t, shots=a.shots)

    print()
    print(f"device:           {a.device} ({backend.num_qubits} qubits)")
    print(f"circuit:          {a.circuit} ({qasm_path.name})")
    print(f"shots:            {a.shots}")
    print(f"transpiled CZ:    {info['cz']}  (depth {info['depth']}, seed {info['seed']}, level {OPT_LEVEL})")
    print(f"physical qubits:  {', '.join(info['physical_qubits'])}")
    print()

    if not (a.submit and a.confirm_credits):
        print("DRY RUN: nothing was submitted. Add --submit --confirm-credits for a real run.")
        return

    print("This will submit ONE job and spend credits. The cost per job is not known in advance.")
    try:
        answer = input("Type yes to submit: ").strip()
    except EOFError:
        answer = ""
    if answer != "yes":
        sys.exit("Not confirmed. Nothing was submitted.")

    # Claim a new output file BEFORE submitting ("x" fails if it exists), so a finished job's record can never overwrite
    # an earlier one and the job id is on disk before we wait.
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = OUT_DIR / f"{stamp}_{a.device}_{a.circuit}_{a.shots}shots.json"
    record = {
        "status": "claimed_not_yet_submitted",
        "date_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "device": a.device,
        "circuit": a.circuit,
        "qasm_file": qasm_path.name,
        "qasm_sha256": hashlib.sha256(qasm_text.encode()).hexdigest(),
        "shots": a.shots,
        "transpile": {**info, "optimization_level": OPT_LEVEL},
        "versions": _versions(),
        "bit_order": "Qiskit counts keys: rightmost character is classical bit 0 (logical qubit 0 of the residual).",
    }
    with open(out, "x") as f:
        json.dump(record, f, indent=1)

    t0 = time.time()
    job = backend.run(t, shots=a.shots)
    job_id = job.job_id()
    record.update(status="submitted_waiting", job_id=job_id)
    _rewrite(out, record)
    print(f"Submitted. Job id: {job_id}")
    print(f"Record: {out}")

    try:
        result = job.result(timeout=a.timeout)
    except Exception as e:  # the job may still be running on the server; the id is already saved
        record.update(status="result_not_retrieved", error=f"{type(e).__name__}: {str(e)[:300]}",
                      seconds_waited=round(time.time() - t0, 1))
        _rewrite(out, record)
        sys.exit(f"Result not retrieved ({type(e).__name__}). The job id is saved in {out}; check the Resonance account.")

    elapsed = time.time() - t0
    record.update(
        status="completed" if result.success else "job_not_successful",
        seconds_submit_to_result=round(elapsed, 1),
        counts=dict(result.get_counts()) if result.success else None,
        timeline=_timeline(result),
    )
    _rewrite(out, record)
    print(f"Done in {elapsed:.1f} s (submit to result, wall clock). Saved: {out}")
    # The 35.0.3 client has no credit-balance call, so there is nothing to read here.
    print("Check the credit balance in the Resonance account.")


def _rewrite(path: Path, record: dict) -> None:
    """Update this run's own file (it was created with mode 'x' in this run)."""
    path.write_text(json.dumps(record, indent=1, default=str))


def _timeline(result):
    try:
        return result._metadata.get("timeline")  # server-side timestamps, if the client provides them
    except Exception:
        return None


def _versions() -> dict:
    import importlib.metadata as m

    return {p: m.version(p) for p in ("iqm-client", "qiskit")}


if __name__ == "__main__":
    main()
