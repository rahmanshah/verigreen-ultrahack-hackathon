"""Stage G0: exact optimum on naive-pipeline vs trusted FY2024 carbon intensity (see verigreen/raw_vs_trusted.py).

Reads only committed files (gold JSON, carbon_intensity.csv, emissions_naive_vs_trusted.csv) and writes
data/gold/raw_vs_trusted_exact_fy2024.csv. Exact classical solver only: no QAOA, no claim of quantum advantage.
The footprint metric is the equal-weight WACI (mean tCO2e/EURm of the selected assets).

Run: uv run python scripts/report_raw_vs_trusted.py
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verigreen.qubo import GOLD_EXACT_PATH, LOW_PRESSURE_CONFIG, load_gold_inputs  # noqa: E402
from verigreen.raw_vs_trusted import (CONDITIONS, GOLD_RAW_VS_TRUSTED_PATH, HEADLINES,  # noqa: E402
                                      HEAVY_EMITTER_MIN, raw_vs_trusted_rows, trusted_fy)


def short(sel: str) -> str:
    return " ".join(s.split(".")[0][:5] for s in sel.split(";")) if sel else "-"


def main() -> None:
    df = raw_vs_trusted_rows(load_gold_inputs())
    df.to_csv(GOLD_RAW_VS_TRUSTED_PATH, index=False, float_format="%.10g", lineterminator="\n")
    print(f"wrote {GOLD_RAW_VS_TRUSTED_PATH.relative_to(ROOT)} ({len(df)} rows: {df.case_id.nunique()} cases x "
          f"{len(CONDITIONS)} conditions x {len(HEADLINES)} settings); every naive QUBO separated\n")

    print("=== benchmark: equal-weight WACI of all 15 assets (tCO2e/EURm) ===")
    b = df.drop_duplicates("case_id")
    for _, r in b.iterrows():
        print(f"{r.case_id:32s} {r.verification_status:24s} trusted {r.waci_eq_weight_benchmark_trusted:7.2f}  "
              f"naive {r.waci_eq_weight_benchmark_naive:7.2f}  error {r.waci_eq_weight_benchmark_error_pct:+8.2f}%   "
              f"[{r.intensity_changes or 'no market-based change'}]")

    for condition in CONDITIONS:
        print(f"\n=== condition {condition}: equal-weight WACI, naive-reported vs true, of the naive portfolio ===")
        g = df[df.condition == condition]
        for label in HEADLINES:
            h = g[g.headline == label]
            print(f"{label}: trusted optimum {short(h.trusted_selected.iloc[0])} "
                  f"(true WACI {h.waci_eq_weight_true_trusted_optimum.iloc[0]:.2f})")
            for _, r in h.iterrows():
                move = (f"-{short(r.left)} +{short(r.entered)}" if r.selection_changed else "same portfolio")
                print(f"  {r.case_id:32s} {move:24s} reported {r.waci_eq_weight_naive_reported:8.2f}  true "
                      f"{r.waci_eq_weight_true_naive_portfolio:6.2f}  error {r.waci_eq_weight_error_pct:+9.2f}%  "
                      f"regret {r.true_regret_pct_of_range:5.2f}% of range")

    print(f"\n=== heavy emitters (intensity >= {HEAVY_EMITTER_MIN:g}) ===")
    t = df[(df.condition == "frozen_trusted_z") & (df.case_id == "all_naive")]
    for _, r in t.iterrows():
        print(f"{r.headline}: trusted optimum holds {short(r.heavy_emitters_trusted_optimum)}")
    trusted = trusted_fy()
    heavy = sorted(trusted.index[trusted.intensity_market_tco2e_per_eurm >= HEAVY_EMITTER_MIN])
    grid = pd.read_csv(GOLD_EXACT_PATH)
    g = grid[(grid.input_config == "main") & (grid.return_weight == LOW_PRESSURE_CONFIG.return_weight)
             & (grid.lambda_uncertainty == LOW_PRESSURE_CONFIG.lambda_uncertainty)]
    for _, r in g.iterrows():
        held = [a for a in r.selected.split(";") if a in heavy]
        print(f"  grid, main inputs, return_weight 1, lambda_u 0, lambda_carbon {r.lambda_carbon:g}: "
              f"{short(';'.join(held))}")


if __name__ == "__main__":
    main()
