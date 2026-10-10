"""VeriGreen demo skeleton.

Reads only committed files in data/gold and data/silver (see loaders.py). Every number shown comes from those files at
run time. Run with the side environment, see app/README.md.
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from loaders import names, read_csv, read_json

CARBON = "data/silver/carbon_intensity.csv"
RAW_VS_TRUSTED = "data/gold/raw_vs_trusted_exact_fy2024.csv"
QUBO_EXACT = "data/gold/qubo_exact_fy2024.csv"
QAOA_SUMMARY = "data/gold/qaoa_summary_fy2024.csv"
QAOA_RELIABILITY = "data/gold/qaoa_reliability_fy2024.csv"
QAOA_BASELINES = "data/gold/qaoa_classical_baselines_fy2024.csv"
QAOA_RELAXATION = "data/gold/qaoa_relaxation_fy2024.csv"
HW_RUNS = "data/gold/hardware_runs_fy2024.csv"  # written by scripts/hardware/export_hardware_summary.py
HW_DIST = "data/gold/hardware_distribution_fy2024.csv"
H3_INSTANCE = "data/gold/qaoa_stage_h3_instance_fy2024.csv"
EX_PDFS = "data/gold/extraction_run001_pdfs.csv"  # written by scripts/extraction_eval/export_extraction_summary.py
EX_COUNTS = "data/gold/extraction_run001_counts.csv"  # counts and run facts only, long format
GOLD_INPUTS = "data/gold/qubo_inputs_fy2024.json"  # has a fiscal_year key: the year the gold files are built for

# Documented in docs/decisions_log.md: "frozen_trusted_z (main)"; the other two are sensitivity conditions.
MAIN_CONDITION = "frozen_trusted_z"
MAIN_SETTING = "MAIN_CONFIG"
MAIN_INPUTS = "main"  # input_config of the MAIN setting (docs/decisions_log.md results table: inputs "main", setting MAIN)

HARDWARE_DISPLAY = {"Wartsila": "Wärtsilä"}  # Hardware page only; the silver table spells it without umlauts
HARDWARE_RESULT = (
    "On IQM Garnet and Emerald, 1000 shots of the p=1 circuit put the exact optimum in 30 to 33% of shots, against 35% "
    "in the noiseless simulation. Both distributions differ from the ideal by more than sampling noise. Without "
    "entangling gates, Garnet matched the simulation within noise. We haven't isolated the cause."
)
EXTRACTION_RESULT = (
    "On a first frozen run over 29 reports, which cost about four cents, 57 of 119 comparable value-and-report pairs "
    "matched our hand-verified numbers. We reviewed the 33 pairs that differed or were ambiguous against the report "
    "pages. In 10 pairs a number from the wrong year column passed the checks. This is a count from one run, not an "
    "accuracy rate."
)
U_NOTE ="u is a revision-risk score, not a judgement of honesty."
BANNER = "No quantum advantage claimed. At 15 assets classical methods find the exact optimum."
RAW_VS_TRUSTED_HEADLINE = (
    "Only the two definition errors (financed emissions used as own: Nordea, Sampo) could change the portfolio."
)

load_csv = st.cache_data(read_csv)
load_json = st.cache_data(read_json)


WORDS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight", 9: "Nine"}


def pct(x: float) -> str:
    """Percent with one decimal from 1% up, two significant digits below."""
    if pd.isna(x):
        return "-"
    v = 100 * x
    return f"{v:.1f}%" if v >= 1 else f"{v:.2g}%"


def num(x: float, digits: int = 2) -> str:
    return "-" if pd.isna(x) else f"{x:.{digits}f}"


def main_exact_row() -> pd.Series:
    q = load_csv(QUBO_EXACT)
    row = q[(q["headline"] == MAIN_SETTING) & (q["input_config"] == MAIN_INPUTS)]
    if len(row) != 1:
        raise ValueError(f"expected one {MAIN_SETTING}/{MAIN_INPUTS} row in {QUBO_EXACT}, got {len(row)}")
    return row.iloc[0]


# ------------------------------------------------------------------------------------------------ pages
def page_findings() -> None:
    st.header("Findings")
    c = load_csv(CARBON)
    years = sorted(c["fiscal_year"].unique())
    st.write(
        f"{c['company_id'].nunique()} Nasdaq Helsinki companies, fiscal years {years[0]} to {years[-1]}, "
        f"{len(c)} company-years. Scope 1 and Scope 2 (market and location based) per company-year, "
        "with revenue and the resulting carbon intensity."
    )
    st.write(
        "Emission values were checked against the companies' primary reports. Source and page per value, and the "
        "quality-check flags, are not in the committed gold and silver files, so they are not shown here."
    )

    match = c["boundary_match"].astype(str).value_counts()
    st.write(
        "Revenue boundary check (does the revenue cover the same entity as the emissions): "
        + ", ".join(f"boundary_match = {k}: {v}" for k, v in match.items())
        + ". Company-years marked unknown are not guessed."
    )

    gold_year = load_json(GOLD_INPUTS)["fiscal_year"]
    year = st.selectbox("Fiscal year", years, index=years.index(gold_year) if gold_year in years else len(years) - 1)
    st.caption(f"Default: the fiscal year of the gold files ({gold_year}, from {GOLD_INPUTS}).")
    cols = ["company_name", "revenue_eur_m", "scope1_t", "scope2_market_t", "scope2_location_t",
            "intensity_market_tco2e_per_eurm", "intensity_location_tco2e_per_eurm", "boundary_match"]
    st.dataframe(c[c["fiscal_year"] == year][cols].reset_index(drop=True), hide_index=True)
    with st.expander("Full table with boundary"):
        st.dataframe(c.drop(columns=["revenue_source", "notes"]), hide_index=True)


def page_raw_vs_trusted() -> None:
    st.header("Raw vs trusted")
    st.subheader(RAW_VS_TRUSTED_HEADLINE)

    df = load_csv(RAW_VS_TRUSTED)
    conditions = [MAIN_CONDITION] + [x for x in df["condition"].unique() if x != MAIN_CONDITION]
    condition = st.radio(
        "Carbon condition", conditions, horizontal=True,
        help=f"{MAIN_CONDITION} is the documented main condition. The others are sensitivity checks.",
    )
    st.caption(f"Setting: {MAIN_SETTING}, FY2024, exact optimum by brute force. "
               f"{MAIN_CONDITION} is the documented main condition; the other conditions are a sensitivity check.")

    d = df[(df["headline"] == MAIN_SETTING) & (df["condition"] == condition)]
    is_aggregate = d["case_id"].str.startswith("all_")
    cases, aggregates = d[~is_aggregate], d[is_aggregate]

    trusted = d["trusted_selected"].unique()
    st.write("Portfolio chosen on trusted data: " + " | ".join(", ".join(names(s)) for s in trusted)
             + f". Equal-weight WACI of that portfolio: "
             + ", ".join(num(v) for v in d["waci_eq_weight_true_trusted_optimum"].unique()) + " tCO2e/EURm.")

    changed = cases[cases["selection_changed"]]
    st.subheader(f"The {len(cases)} documented FY2024 cases")
    readable = [f"{', '.join(names(co))}, {cid.split(':')[1].replace('_', ' ')}"
                for co, cid in zip(changed["companies"], changed["case_id"])]
    st.write(f"The selection changed in {len(changed)} of {len(cases)} cases: "
             + ("; ".join(readable) if readable else "none") + ".")

    view = pd.DataFrame({
        "company": cases["companies"].map(lambda s: ", ".join(names(s))),
        "case": cases["case_id"].str.split(":").str[1],
        "intensity change (tCO2e/EURm)": cases["intensity_changes"].fillna("-"),
        "verification": cases["verification_status"],
        "selection changed": cases["selection_changed"].map({True: "yes", False: "no"}),
        "entered": cases["entered"].map(lambda s: ", ".join(names(s)) if pd.notna(s) else "-"),
        "left": cases["left"].map(lambda s: ", ".join(names(s)) if pd.notna(s) else "-"),
        "WACI reported on naive data": cases["waci_eq_weight_naive_reported"].round(2),
        "true WACI of the naive portfolio": cases["waci_eq_weight_true_naive_portfolio"].round(2),
        "WACI error %": cases["waci_eq_weight_error_pct"].round(1),
        "regret, % of feasible range": cases["true_regret_pct_of_range"].round(1),
    })
    st.dataframe(view, hide_index=True)
    st.caption("WACI error = reported minus true, relative to true. Regret = true objective of the naive portfolio "
               "minus the trusted optimum, as a share of the trusted feasible range.")

    st.subheader("All cases combined")
    agg_view = pd.DataFrame({
        "combination": aggregates["case_id"],
        "selection changed": aggregates["selection_changed"].map({True: "yes", False: "no"}),
        "WACI reported on naive data": aggregates["waci_eq_weight_naive_reported"].round(2),
        "true WACI of the naive portfolio": aggregates["waci_eq_weight_true_naive_portfolio"].round(2),
        "WACI error %": aggregates["waci_eq_weight_error_pct"].round(1),
    })
    st.dataframe(agg_view, hide_index=True)
    naive = aggregates[aggregates["case_id"] == "all_naive"].iloc[0]
    n_applied = len(str(naive["applied_rows"]).split(";"))
    n_superseded = len(str(naive["superseded_rows"]).split(";")) if pd.notna(naive["superseded_rows"]) else 0
    st.caption(f"all_naive applies {n_applied} of the {len(cases)} documented errors together ({n_superseded} are "
               "superseded by a later version of the same company's error), including both definition errors, so it "
               "is not the effect of any single error.")
    with st.expander("What each case used as its raw basis"):
        st.dataframe(d[["case_id", "raw_basis", "verification_status"]], hide_index=True)


def page_frontier() -> None:
    st.header("Green frontier")
    st.write("Carbon-pressure sweep of exact optima, not an efficient frontier.")
    st.caption("No frontier file exists in data/gold. This page shows the committed grid of exact optima, one portfolio "
               "per carbon weight (lambda_carbon), everything else held at the MAIN setting.")

    q = load_csv(QUBO_EXACT)
    m = main_exact_row()
    sweep = q[(q["input_config"] == m["input_config"]) & (q["window"] == m["window"])
              & (q["carbon_method"] == m["carbon_method"]) & (q["trust_score"] == m["trust_score"])
              & (q["return_weight"] == m["return_weight"]) & (q["lambda_uncertainty"] == m["lambda_uncertainty"])]
    sweep = sweep.sort_values("lambda_carbon").reset_index(drop=True)

    st.write(f"Held fixed: inputs = {m['input_config']}, return weight = {m['return_weight']:g}, "
             f"lambda_uncertainty = {m['lambda_uncertainty']:g}. MAIN uses lambda_carbon = {m['lambda_carbon']:g}.")
    st.caption(f"MAIN does not use the trust term. {U_NOTE} Volatility and return are in-sample statistics of the "
               "estimation window, not forecasts.")

    lams = sweep["lambda_carbon"].tolist()
    lam = st.select_slider("lambda_carbon (carbon weight)", options=lams, value=m["lambda_carbon"])
    row = sweep[sweep["lambda_carbon"] == lam].iloc[0]

    entered = sorted(set(names(row["selected"])) - set(names(m["selected"])))
    left = sorted(set(names(m["selected"])) - set(names(row["selected"])))
    st.write("Exact optimum: " + ", ".join(names(row["selected"])))
    st.write("Compared with MAIN: entered " + (", ".join(entered) or "none") + "; left " + (", ".join(left) or "none") + ".")
    a, b, c = st.columns(3)
    a.metric("Equal-weight WACI (tCO2e/EURm)", num(row["waci_eq_weight_tco2e_per_eurm"]))
    b.metric("Equal-weight volatility", pct(row["eq_weight_vol"]))
    c.metric("Equal-weight return", pct(row["eq_weight_return"]))

    points = sweep.assign(shown=sweep["lambda_carbon"].map(lambda x: "selected" if x == lam else "grid point"))
    st.altair_chart(
        alt.Chart(points).mark_point(filled=True, size=90).encode(
            x=alt.X("lambda_carbon:Q", title="lambda_carbon"),
            y=alt.Y("waci_eq_weight_tco2e_per_eurm:Q", title="Equal-weight WACI (tCO2e/EURm)"),
            color=alt.Color("shown:N", title=None, scale=alt.Scale(domain=["grid point", "selected"],
                                                                  range=["#4c78a8", "#e45756"])),
            tooltip=["lambda_carbon", "waci_eq_weight_tco2e_per_eurm"],
        ),
        width="stretch",
    )
    count = WORDS.get(len(sweep), str(len(sweep)))
    st.caption(f"{count} grid points; nothing is computed between them.")
    table = sweep.assign(selected=sweep["selected"].map(lambda s: ", ".join(names(s))))[
        ["lambda_carbon", "selected", "waci_eq_weight_tco2e_per_eurm", "eq_weight_vol", "eq_weight_return"]]
    st.dataframe(table, hide_index=True)


def _merge_reliability(rows: pd.DataFrame, rel: pd.DataFrame) -> pd.DataFrame:
    keys = ["variant", "penalty_name", "p"]
    r = rel.rename(columns={"base_stage": "stage"})[["stage"] + keys + ["n_restarts", "median_p_opt", "n_beat_p_opt"]]
    return rows.merge(r, on=["stage"] + keys, how="left")


def _qaoa_view(rows: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({
        "variant": rows["variant"].str.replace("_initial_state", "", regex=False),
        "penalty": rows["penalty_name"],
        "p": rows["p"].map(lambda x: "-" if pd.isna(x) else f"{x:g}"),
        "P(optimum)": rows["sv_p_opt"].map(pct),
        "within 5% of optimum, given feasible": rows["sv_near_mass_given_feasible"].map(pct),
        "feasible share": rows["sv_feasible_share"].map(pct),
        "mean r over feasible mass": rows["sv_mean_ratio_feasible"].map(lambda x: num(x, 3)),
        "optimiser evaluations": rows["n_evals"].map(lambda x: "-" if pd.isna(x) else f"{x:g}"),
        "seconds": rows["runtime_s"].map(lambda x: num(x, 1)),
        "restarts": rows["n_restarts"].map(lambda x: "-" if pd.isna(x) else f"{x:g}"),
        "median restart P(optimum)": rows["median_p_opt"].map(pct),
        "restarts above random-feasible P(optimum)": rows["n_beat_p_opt"].map(lambda x: "-" if pd.isna(x) else f"{x:g}"),
    })
    return out


def page_quantum() -> None:
    st.header("Quantum tables")
    st.warning(BANNER)
    st.caption("Noise-free simulation (Aer), FY2024, MAIN setting. Every QAOA number is scored against the exact "
               "optimum. P(optimum) is the probability of measuring exactly the optimal portfolio.")

    exact = main_exact_row()
    s = load_csv(QAOA_SUMMARY)
    rel = load_csv(QAOA_RELIABILITY)
    base = load_csv(QAOA_BASELINES)
    relax = load_csv(QAOA_RELAXATION)
    random_row = s[(s["variant"] == "random_feasible") & (s["penalty_name"] == "exact")].iloc[0]
    uniform_row = s[(s["variant"] == "uniform_superposition") & (s["penalty_name"] == "exact")].iloc[0]
    n_feasible = int(random_row["n_feasible"])

    # ---- exact optimum
    st.subheader("Exact optimum")
    st.write(f"Brute force over all {n_feasible} feasible portfolios (choose {int(exact['n_selected'])} of {len(relax)} assets): "
             + ", ".join(names(exact["selected"])) + ".")
    st.write(f"Portfolios within 5% of the optimum (as a share of the feasible range): {int(random_row['n_near'])}. "
             f"Equal-weight WACI: {num(exact['waci_eq_weight_tco2e_per_eurm'])} tCO2e/EURm.")

    # ---- side by side
    exact_set = set(names(exact["selected"]))
    relaxed = relax[relax["rounded_top_k"] == 1]["asset"]
    relaxed_ok = set(names(";".join(relaxed))) == exact_set
    rr = s[(s["variant"] == "rounded_relaxation")].iloc[0]
    glance = [{"method": "Brute force", "finds the exact optimum": "yes, by construction",
               "cost": f"{n_feasible} evaluations", "P(optimum) of one sample": "-"}]
    for label, method in [("Greedy swap search", "greedy_swap"), ("Simulated annealing", "simulated_annealing")]:
        b = base[base["method"] == method]
        hits = b[b["hit"]]
        glance.append({
            "method": label,
            "finds the exact optimum": f"{len(hits)} of {len(b)} runs",
            "cost": (f"median {hits['first_hit_eval'].median():g} evaluations to first hit, "
                     f"max {hits['first_hit_eval'].max():g}"),
            "P(optimum) of one sample": "-",
        })
    glance.append({
        "method": "Classical relaxation, rounded",
        "finds the exact optimum": (f"{'yes' if relaxed_ok else 'no'}, rank {int(rr['rounded_rank_of_5005'])} "
                                    f"of {n_feasible}"),
        "cost": "no quantum step",
        "P(optimum) of one sample": "-",
    })
    std_sel = s[(s["stage"] == "F") & (s["variant"] == "standard")]
    warm_sel = s[(s["stage"] == "F2") & s["variant"].str.startswith("warm_eps") & ~s["variant"].str.endswith("_state")]
    std_best, warm_best = std_sel.loc[std_sel["sv_p_opt"].idxmax()], warm_sel.loc[warm_sel["sv_p_opt"].idxmax()]
    glance.append({"method": "Standard QAOA, best selected row",
                   "finds the exact optimum": "one run: see P(optimum)",
                   "cost": f"{std_best['n_evals']:g} optimiser evaluations",
                   "P(optimum) of one sample": pct(std_best["sv_p_opt"])})
    glance.append({"method": "Warm-start QAOA, best selected row",
                   "finds the exact optimum": "one run: see P(optimum)",
                   "cost": f"{warm_best['n_evals']:g} optimiser evaluations",
                   "P(optimum) of one sample": pct(warm_best["sv_p_opt"])})
    glance.append({"method": "Random feasible portfolio", "finds the exact optimum": "-", "cost": "-",
                   "P(optimum) of one sample": pct(random_row["sv_p_opt"])})
    st.subheader("Side by side")
    st.dataframe(pd.DataFrame(glance), hide_index=True)
    st.caption("A best selected row is the best of the selected restarts in the table. It is not a typical run: "
               "see the median restart columns below.")

    # ---- standard QAOA
    st.subheader("1. Standard QAOA")
    st.caption("Selected restart per row. 'exact' and 'practical' are the two budget-penalty sizes tested.")
    ref = pd.DataFrame([random_row, uniform_row]).assign(stage="F", p=float("nan"), n_evals=float("nan"),
                                                         runtime_s=float("nan"))
    std = _merge_reliability(std_sel.sort_values(["penalty_name", "p"]), rel)
    std_table = _qaoa_view(pd.concat([ref, std], ignore_index=True))
    std_table["variant"] = std_table["variant"].replace({"random_feasible": "random feasible (baseline)",
                                                         "uniform_superposition": "uniform superposition (baseline)"})
    st.dataframe(std_table, hide_index=True)

    std_rel = std.dropna(subset=["median_p_opt"])
    below = int((std_rel["median_p_opt"] < random_row["sv_p_opt"]).sum())
    st.write(f"In {below} of the {len(std_rel)} standard rows with a reliability run, the median restart's "
             f"P(optimum) is below random feasible sampling ({pct(random_row['sv_p_opt'])}).")

    # ---- warm start
    st.subheader("2. Warm-start QAOA")
    st.caption("Starts from a classical solution that already contains the optimum.")
    warm_all = s[(s["stage"] == "F2") & s["variant"].str.startswith("warm_eps")]
    blocks = []
    for variant in sorted(v for v in warm_all["variant"].unique() if not v.endswith("_initial_state")):
        start = warm_all[(warm_all["variant"] == variant + "_initial_state") & (warm_all["penalty_name"] == "exact")]
        start = start.assign(p=0.0)
        runs = _merge_reliability(warm_all[warm_all["variant"] == variant].sort_values(["penalty_name", "p"]), rel)
        blocks += [start, runs]
    warm = pd.concat(blocks, ignore_index=True)
    warm_table = _qaoa_view(warm)
    warm_table["penalty"] = warm_table["penalty"].where(warm["p"] > 0, "- (classical, no QAOA layer)")
    start_p = warm.groupby(warm["variant"].str.replace("_initial_state", "", regex=False))["sv_p_opt"].transform("first")
    warm_table["median restart / p = 0"] = (warm["median_p_opt"] / start_p).map(lambda x: num(x, 2))
    st.dataframe(warm_table, hide_index=True)
    st.caption("p = 0 is the warm starting state with no QAOA layer. The last column is the median restart's "
               "P(optimum) divided by the p = 0 value of the same variant.")


def page_hardware() -> None:
    st.header("Hardware")
    def shown(selection: str) -> list[str]:
        return [HARDWARE_DISPLAY.get(n, n) for n in names(selection)]

    runs, dist, inst = load_csv(HW_RUNS), load_csv(HW_DIST), load_csv(H3_INSTANCE)
    fixed = [a for s in inst[inst["role"] == "fixed_to_1"]["asset"] for a in shown(s)]
    undecided = list(inst[inst["role"] == "undecided"]["asset"])  # bit k of a bitstring = undecided[k], as compare_run.py
    width = len(undecided)
    # pandas reads 0101 as the integer 101: restore the leading zeros (the width is the number of undecided assets)
    runs = runs.assign(optimum_bitstring=runs["optimum_bitstring"].astype(str).str.zfill(width))
    dist = dist.assign(bitstring=dist["bitstring"].astype(str).str.zfill(width))
    cz = {c: sorted(runs[runs["circuit"] == c]["transpiled_cz"].unique()) for c in ("p0", "p1")}
    devices = " and ".join(d.capitalize() for d in runs["device"].drop_duplicates())

    st.write(
        f"The circuit is the 4-qubit residual problem: {', '.join(fixed)} are fixed in the portfolio, and the circuit "
        f"chooses 2 of {', '.join(a for s in undecided for a in shown(s))}. The angles were tuned on the simulator; "
        f"nothing was tuned on the device. Run on IQM {devices}, with p=0 (no entangling gates, "
        f"{', '.join(str(c) for c in cz['p0'])} CZ after transpiling) and p=1 ({', '.join(str(c) for c in cz['p1'])} CZ "
        "after transpiling)."
    )

    # ---- results table
    o = runs.iloc[0]["optimum_bitstring"]
    above = runs["tvd"] > runs["noise_floor_p95"]
    st.subheader("Results, one row per run")
    table = pd.DataFrame({
        "run": runs["run"],
        "device": runs["device"].str.capitalize(),
        "circuit": runs["circuit"],
        "shots": runs["shots"],
        f"{o} count": runs["optimum_count"],
        f"observed {o}": runs["observed_p_opt"].map(lambda x: num(x, 4)),
        f"simulated {o}": runs["simulated_p_opt"].map(lambda x: num(x, 4)),
        "TVD": runs["tvd"].map(lambda x: num(x, 3)),
        "noise floor (p95)": runs["noise_floor_p95"].map(lambda x: num(x, 3)),
        "above noise floor": above.map({True: "yes", False: "no"}),
        "CZ": runs["transpiled_cz"],
        "depth": runs["transpiled_depth"],
    })
    st.dataframe(table, hide_index=True, width="stretch")
    st.caption(f'"observed {o}" and "simulated {o}" are the shares of shots that gave the exact optimum on the hardware '
               "and in the noiseless simulation. The noise floor is the 95th percentile of sampling noise alone. "
               "CZ and depth are those of the transpiled circuit.")
    short = runs["shots"] == runs["shots"].min()
    if (~above[short]).all():
        st.caption(f"At {runs['shots'].min()} shots the differences are within sampling noise, so those rows are not "
                   "evidence either way.")

    # ---- per-run chart
    st.subheader("One run, all 16 bitstrings")
    labels = {int(r.run): f"Run {r.run}: {r.device.capitalize()} {r.circuit}, {r.shots} shots" for r in runs.itertuples()}
    run_no = st.selectbox("Run", list(labels), index=3, format_func=labels.get)
    d = dist[dist["run"] == run_no]
    r = runs[runs["run"] == run_no].iloc[0]
    long = pd.concat([
        d.assign(source="observed on hardware", probability=d["observed_p"]),
        d.assign(source="simulated (noiseless)", probability=d["simulated_p"]),
    ])
    mark = f"{o} *"  # short label for the exact optimum; the caption under the chart explains the star
    long["label"] = long["bitstring"].map(lambda b: mark if b == o else b)
    order = [mark if b == o else b for b in sorted(d["bitstring"])]
    bars = alt.Chart(long).mark_bar().encode(
        x=alt.X("label:N", title="bitstring", sort=order, axis=alt.Axis(labelAngle=-45, labelOverlap=False)),
        xOffset=alt.XOffset("source:N"),
        y=alt.Y("probability:Q", title="probability"),
        color=alt.Color("source:N", title=None, scale=alt.Scale(domain=["observed on hardware", "simulated (noiseless)"],
                                                                range=["#e45756", "#4c78a8"])),
        tooltip=["bitstring", "selected_assets", "source", "observed_count", alt.Tooltip("probability:Q", format=".4f")],
    )
    band = alt.Chart(pd.DataFrame({"label": [mark]})).mark_rect(opacity=0.15, color="#f2c744").encode(
        x=alt.X("label:N", sort=order))
    st.altair_chart((band + bars).properties(height=340), width="stretch")
    st.write(f"{r['shots']} shots: {r['optimum_count']} of them were {o} "
             f"({num(r['observed_p_opt'], 4)}), against {num(r['simulated_p_opt'], 4)} in the noiseless simulation. "
             f"TVD {num(r['tvd'], 3)}, noise floor {num(r['noise_floor_p95'], 3)}.")
    legend = ", ".join(f"bit {k} = {', '.join(shown(a))}" for k, a in enumerate(undecided))
    chosen = " and ".join(shown(";".join(a for k, a in enumerate(undecided) if o[::-1][k] == "1")))
    st.caption(
        f"Bitstring convention (from scripts/hardware/compare_run.py): the rightmost character is bit 0. {legend}; the "
        f"order is that of the undecided assets in {H3_INSTANCE}. A 1 means the asset is selected, so {o} selects {chosen}, "
        f"the exact optimum (marked {mark} in the chart)."
    )

    # ---- explanations
    st.subheader("How to read TVD and the noise floor")
    st.write(
        "TVD (total variation distance) compares two probability distributions over the same 16 bitstrings: 0 means "
        "they are identical, 1 means they are completely different. Here it compares the hardware counts with the "
        "noiseless simulation of the same circuit."
    )
    st.write(
        "The noise floor is what sampling noise alone would produce. With a finite number of shots, even a perfect "
        "device gives a distribution that differs a little from the ideal one. For each run it is computed as in "
        f"scripts/hardware/compare_run.py: {int(r['noise_draws'])} draws of {int(r['shots'])} shots (the shot count of "
        f"the run) are taken from the ideal distribution, seed {int(r['noise_seed'])}; the TVD of each draw to the "
        "ideal is computed; the floor shown is the 95th percentile of those TVDs. A run with a TVD above the floor "
        "differs from the ideal by more than sampling noise alone usually gives."
    )

    # ---- verbatim result
    st.info(HARDWARE_RESULT)

    st.subheader("Caveats")
    st.markdown(
        "- The p=1 circuit also has more single-qubit gates and greater depth than p=0, so the CZ gates are not proven "
        "to be the cause.\n"
        "- Emerald p0 was not run.\n"
        "- The qubits were chosen by the transpiler without calibration data.\n"
        "- We do not rank Garnet against Emerald.\n"
        "- This is a reduced 4-qubit problem, and no quantum advantage is claimed.\n"
        "- The hardware work was built at the event (commit 0f0c917 onward)."
    )
    # Source: docs/hardware_iqm_notes.md (run log, "Six jobs, 3.50 credits used"); the credits are not in the result files.
    st.caption("6 jobs, 3.50 credits used (charged per job: 0.50 on Garnet, 0.75 on Emerald)")


def page_extraction() -> None:
    st.header("Extraction")
    pdfs, counts = load_csv(EX_PDFS), load_csv(EX_COUNTS)

    def row(section: str, label: str) -> pd.Series:
        r = counts[(counts["section"] == section) & (counts["label"] == label)]
        if len(r) != 1:
            raise ValueError(f"expected one row for {section}/{label} in {EX_COUNTS}, got {len(r)}")
        return r.iloc[0]

    def c(section: str, label: str) -> int:
        return int(row(section, label)["count"])

    def of(section: str, label: str) -> str:
        r = row(section, label)
        return f"{int(r['count'])} of {int(r['denominator'])}"

    # ---- a. what it is
    st.write(
        "An LLM reads the report pages that a page finder selects. Every value it returns carries a verbatim quote, the "
        "source page and the check it passed. In the intended workflow, a person reviews the flagged values, not every "
        "number. In this run, the review was our own adjudication. This extraction run was built and run at the event; "
        "the 3-report spike earlier was pre-event."
    )

    # ---- b. run facts
    st.subheader("Run facts")
    model = row("run", "model_returned")
    a, b, d, e = st.columns(4)
    a.metric("Calls", c("run", "calls_total"), help=f"{c('run', 'extraction_calls')} extraction calls and "
                                                   f"{c('run', 'availability_calls')} availability call")
    b.metric("Cost (EUR)", f"{float(row('run', 'cost_eur')['count']):.4f}")
    d.metric("Model identifier returned", model["note"], help=f"on {of('run', 'model_returned')} calls")
    e.metric("Tokens in / out", f"{c('run', 'input_tokens'):,} / {c('run', 'output_tokens'):,}")
    st.write(f"{c('run', 'extraction_calls')} extraction calls and {c('run', 'availability_calls')} availability call. "
             f"Reasoning tokens as reported: {c('run', 'reasoning_tokens'):,}.")
    st.caption("Prices recalled from earlier notes, not re-verified; 1 USD = 1 EUR assumed.")

    # ---- c. per PDF
    st.subheader(f"Per report ({len(pdfs)} PDFs)")
    note = pdfs["spike_not_blind"].map({True: "spike, not blind", False: ""})
    note = note.where(pdfs["status"] == "completed", "no pages found")
    table = pd.DataFrame({
        "company": pdfs["company"],
        "year": pdfs["report_year"],
        "type": pdfs["pdf_type"],
        "note": note,
        "pages": pdfs["pages_sent"],
        "records": pdfs["records"],
        "nulls": pdfs["nulls"],
        "pass": pdfs["verifier_pass"],
        "fail": pdfs["verifier_fail"],
        "failing checks": pdfs["failing_checks"].fillna(""),
        "EUR": pdfs["cost_eur"].map(lambda x: f"{x:.4f}"),
        "s": pdfs["latency_s"].map(lambda x: "-" if pd.isna(x) else f"{x:.1f}"),
    })
    # Explicit pixel widths so the full note text ("spike, not blind") and every header fit at 100% zoom in wide mode.
    widths = {"company": 95, "year": 60, "type": 160, "note": 150, "pages": 65, "records": 75, "nulls": 60, "pass": 60,
              "fail": 55, "failing checks": 135, "EUR": 70, "s": 55}
    st.dataframe(table, hide_index=True, width="stretch", height=(len(table) + 1) * 35 + 3,
                 column_config={k: st.column_config.Column(width=w) for k, w in widths.items()})
    st.caption("pages = pages sent to the model. Spike reports were used in the pre-event spike and are not a blind test. "
               "The Metso 2023 annual report had no pages found, so it had no call and no cost.")

    # ---- d. verifier
    st.subheader("Verifier results")
    values = c("run", "values")
    st.write(
        f"Of {values} valued records, {c('run', 'verifier_pass')} pass and {c('run', 'verifier_fail')} fail. "
        f"Failing checks: value_parse {c('verifier_failures', 'value_parse')}; quote/page "
        f"{c('verifier_failures', 'quote_page')}; number_matches {c('verifier_failures', 'number_matches')}."
    )
    st.write(
        f"{row('verifier_failures', 'number_matches')['note']}; "
        f"{row('verifier_failures', 'quote_page')['note']}, so no failure is counted twice."
    )
    st.caption('"Pass" means the mechanical checks only (quote on the page, number matches the quote, page index, '
               "sanity), not that the value is correct and not that the year column is right.")

    # ---- e. scoring
    st.subheader("Scoring against our verified rows")
    total = c("scoring_pairs", "total")
    scoring = [
        ("verified_match", f"exact {c('scoring_pairs', 'verified_match_exact')}, near {c('scoring_pairs', 'verified_match_near')}"),
        ("ambiguous_extracted", "several extracted values, at least one matches"),
        ("ambiguous_verified", "more than one verified value for the key"),
        ("verified_mismatch", "no extracted number matches"),
        ("unit_ambiguous", f"not scored: tons {c('scoring_pairs', 'unit_ambiguous_tons')}, "
                           f"'or as indicated' {c('scoring_pairs', 'unit_ambiguous_as_indicated')}"),
        ("not_extracted", "not scored"),
        ("extracted_failed_verifier", "not scored: no candidate passed the checks"),
    ]
    st.dataframe(pd.DataFrame({
        "category": [s for s, _ in scoring] + ["total"],
        "pairs": [of("scoring_pairs", s) for s, _ in scoring] + [f"{total} of {total}"],
        "note": [n for _, n in scoring] + [""],
    }), hide_index=True, width="stretch")
    st.write(
        f"Keys: {c('keys', 'no_source_pdf') + c('keys', 'spike_only') + c('keys', 'has_main_pair')} = "
        f"{c('keys', 'no_source_pdf')} with no source PDF in the run + {c('keys', 'spike_only')} reachable only from the "
        f"spike reports + {c('keys', 'has_main_pair')} with at least one pair in the table above."
    )
    st.write(
        f"Spike reports, scored separately and not blind: {of('spike_pairs', 'verified_match')} pairs match, "
        f"{of('spike_pairs', 'ambiguous_extracted')} have several extracted values."
    )
    st.caption(f"A count, not a rate: pairs overlap on keys and {c('scoring_pairs', 'not_scorable_total')} of the "
               f"{total} were not scorable.")

    # ---- f. adjudication
    st.subheader("Adjudication")
    reviewed = c("adjudication", "pairs_reviewed")
    st.write(
        f"{reviewed} pairs that differed or were ambiguous ({c('adjudication', 'category_verified_mismatch')} mismatch, "
        f"{c('adjudication', 'category_ambiguous_verified')} several verified values, "
        f"{c('adjudication', 'category_ambiguous_extracted')} several extracted values) were reviewed against report "
        "pages by one person with suggested verdicts in front of them: a first review, not independent. The "
        f"{c('adjudication', 'matches_not_reviewed')} matches were compared by number, not reviewed by a person."
    )
    verdicts = counts[(counts["section"] == "adjudication") & counts["label"].str.startswith("verdict_")]
    tokens = ["vintage_or_restatement", "boundary_or_method", "year_column_wrong", "extraction_correct"]
    left, right = st.columns(2)
    left.dataframe(pd.DataFrame({
        "verdict as recorded": verdicts["label"].str.removeprefix("verdict_"),
        "pairs": verdicts["count"].astype(int),
    }), hide_index=True, width="stretch")
    right.dataframe(pd.DataFrame({
        "verdict token": tokens,
        "pairs": [of("adjudication", f"token_{t}") for t in tokens],
    }), hide_index=True, width="stretch")
    st.caption("A combined verdict counts once under each of its tokens, so the tokens add up to more than the "
               f"{reviewed} pairs.")
    st.write(
        f"The scorer's own labels, next to the reviewer: vintage_difference was right in "
        f"{of('scorer_labels', 'vintage_difference_right')} labelled pairs; year_mapping_suspect was a real error in "
        f"{of('scorer_labels', 'year_mapping_suspect_real_error')} labelled pairs."
    )
    st.caption("Right = the reviewer verdict contains vintage_or_restatement. Real error = the reviewer verdict contains "
               "year_column_wrong.")

    # ---- g. failure patterns
    st.subheader("Failure patterns")
    ycw = c("adjudication", "year_column_wrong_pairs")
    st.markdown(
        f"- Wrong-year column: {ycw} pairs. In {c('adjudication', 'year_column_wrong_more_than_one_candidate')} of them "
        "the correct number was also extracted, so disagreement between candidates is a signal a reviewer can use. In "
        f"{c('adjudication', 'year_column_wrong_one_candidate')} only one candidate was extracted and nothing signalled "
        "it. We have not built that flag yet.\n"
        f"- Extra row from a table with a different boundary: {c('adjudication', 'boundary_or_method_in_ambiguous_extracted')} "
        "pairs (verdict boundary_or_method among the ambiguous_extracted pairs, all Sampo). In these the extra row came "
        "from the biogenic-emissions table on p.87, which the report says is not included in the group figures "
        "(reviewer's reading of the page).\n"
        f"- Boundary or method differences among the mismatches: {c('adjudication', 'boundary_or_method_in_verified_mismatch')} "
        f"pairs, of which {c('adjudication', 'pattern_wrong_entity')} is a wrong entity (parent company table instead of "
        "the group), counted by keyword 'parent' in reviewer notes.\n"
        f"- Restated vintage: {c('adjudication', 'token_vintage_or_restatement')} pairs."
    )

    # ---- h. caveats
    st.subheader("Caveats")
    st.markdown(
        "- One run only, not repeated.\n"
        "- The page finder may have missed pages.\n"
        f"- {c('scoring_pairs', 'unit_ambiguous')} pairs are unscorable because of \"tons\" "
        f"({c('scoring_pairs', 'unit_ambiguous_tons')}) or \"or as indicated\" "
        f"({c('scoring_pairs', 'unit_ambiguous_as_indicated')}) units.\n"
        "- The verifier cannot check which year a column belongs to.\n"
        f"- {of('scoring_pairs', 'matches_also_equal_other_year').replace(' of ', ' of the ')} matches also equal another "
        "year's value.\n"
        "- One reviewer, with suggested verdicts in front of them."
    )

    # ---- i. verbatim result
    st.info(EXTRACTION_RESULT)


PAGES = {
    "Findings": page_findings,
    "Raw vs trusted": page_raw_vs_trusted,
    "Green frontier": page_frontier,
    "Quantum tables": page_quantum,
    "Hardware": page_hardware,
    "Extraction": page_extraction,
}

st.set_page_config(page_title="VeriGreen demo", layout="wide")
st.sidebar.title("VeriGreen")
choice = st.sidebar.radio("Page", list(PAGES))
st.sidebar.caption("Reads only committed files in data/gold and data/silver.")
PAGES[choice]()
