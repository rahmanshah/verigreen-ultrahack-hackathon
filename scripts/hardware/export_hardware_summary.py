# Environment: PROJECT env (.venv, qiskit 2.5.2). Does not contact IQM, needs no token, submits nothing.
# What it does: runs compare_run.analyse() on every data/hardware/*.json record (sorted by file name = run order) and
#   writes two derived files for the demo app, at full precision (no rounding):
#     data/gold/hardware_runs_fy2024.csv          one row per run
#     data/gold/hardware_distribution_fy2024.csv  one row per run and bitstring (observed count and probability, simulated)
#   The app environment has no qiskit, so it reads these two files instead of simulating. Deterministic: same input gives
#   byte-identical files (the noise floor uses compare_run's seeded draws).
# Run (from the repo root, no bytecode written):
#   $env:PYTHONDONTWRITEBYTECODE='1'
#   .venv\Scripts\python.exe scripts\hardware\export_hardware_summary.py
# Date: 2026-10-09
"""Project env: export the six hardware runs, compared with their exact simulation, to data/gold for the app."""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_run import DRAWS, REPO, SEED, analyse  # noqa: E402

HW_DIR = REPO / "data" / "hardware"
OUT_RUNS = REPO / "data" / "gold" / "hardware_runs_fy2024.csv"
OUT_DIST = REPO / "data" / "gold" / "hardware_distribution_fy2024.csv"


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def main() -> None:
    files = sorted(HW_DIR.glob("*.json"))
    if not files:
        sys.exit(f"STOP: no records in {HW_DIR}.")
    run_rows, dist_rows = [], []
    for run, path in enumerate(files, start=1):
        r = analyse(path)
        rec, n, shots = r["rec"], r["n"], r["shots"]
        if rec.get("status") != "completed":
            sys.exit(f"STOP: {path.name} has status {rec.get('status')!r}.")
        tp = rec["transpile"]
        opt = r["opt_idx"]
        run_rows.append([
            run, rec["device"], r["circuit"], shots, r["opt_bits"], r["counts"].get(r["opt_bits"], 0),
            float(r["hw"][opt]), float(r["sim"][opt]), float(r["tvd"]), r["p95"], r["floor_mean"], DRAWS, SEED,
            tp["cz"], tp["depth"], ";".join(tp["physical_qubits"]), path.name, r["qasm_name"],
        ])
        for i in range(2**n):
            bits = format(i, f"0{n}b")
            selected = ";".join(a for k, a in enumerate(r["names"]) if (i >> k) & 1)
            dist_rows.append([run, bits, selected, r["counts"].get(bits, 0), float(r["hw"][i]), float(r["sim"][i])])

    write_csv(OUT_RUNS, [
        "run", "device", "circuit", "shots", "optimum_bitstring", "optimum_count", "observed_p_opt", "simulated_p_opt",
        "tvd", "noise_floor_p95", "noise_floor_mean", "noise_draws", "noise_seed", "transpiled_cz", "transpiled_depth",
        "physical_qubits", "source_file", "qasm_file",
    ], run_rows)
    write_csv(OUT_DIST, ["run", "bitstring", "selected_assets", "observed_count", "observed_p", "simulated_p"], dist_rows)
    print(f"wrote {OUT_RUNS.relative_to(REPO)} ({len(run_rows)} rows) and {OUT_DIST.relative_to(REPO)} ({len(dist_rows)} rows)")


if __name__ == "__main__":
    main()
