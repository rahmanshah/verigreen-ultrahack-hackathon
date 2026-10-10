"""QAOA on the Aer simulator for the FY2024 QUBO (stages F and F2). Simulator only; no claim of quantum advantage: at 15
assets the exact optimum is found by brute force in well under a second, and every QAOA number is reported against it.

Mapping: x_i = (1 - Z_i)/2, qubit i = asset i (sorted company_id). A qiskit bitstring key (qubit 0 rightmost) read as a
binary integer is sum_i x_i 2^i, i.e. the row index of `enumerate_states`, and Statevector.probabilities() uses the same
index. So every distribution here is a length-2^n probability vector over `enumerate_states` rows.

Ising form of the QUBO (J strictly upper triangular):
    E(x) = offset + sum_i a_i Z_i + sum_{i<j} b_ij Z_i Z_j
    a_i = -h_i/2 - sum_{j != i} J_ij/4,   b_ij = J_ij/4,   offset = const + sum(h)/2 + sum(J)/4
The operator given to QAOA is H / norm with norm = max |a_i|, |b_ij|, so gamma is O(1). Rescaling reorders nothing.

Penalties: "exact" = 1.1 x P* (stage D default, separates all 2^n states); "practical" = 1.1 x P_gs, the smallest P for
which the global minimum over all states is still the exact feasible optimum (see `ground_state_threshold`).

Metrics, with F_min / F_max the best / worst feasible objective and r(x) = (f(x) - F_min) / (F_max - F_min):
- p_opt: probability of the exact optimum.
- near_mass: probability of a feasible state with r <= NEAR_OPTIMAL_FRACTION (5%); near_mass_given_feasible: the same
  divided by the feasible probability (compare with the share of feasible portfolios in that set).
- feasible_share: probability of exactly K assets.
- mean_ratio_feasible: mean r over feasible probability mass; best_ratio: r of the best feasible sampled state.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from verigreen.qubo import (BUDGET_FLOOR, BUDGET_MARGIN, NEAR_OPTIMAL_FRACTION, Qubo, enumerate_states, qubo_energy,
                            qubo_with_penalty)

PENALTIES = ("exact", "practical")
REPS = (1, 2, 3)
N_RANDOM_RESTARTS = 5
MAXITER = 300
TRAIN_SHOTS = 4096
READOUT_SHOTS = 16384
SEED_BASE = 20261006


# ---------------------------------------------------------------- penalties and Ising form

def ground_state_threshold(qubo: Qubo) -> float:
    """P_gs = max_{d != 0} (F_min - m_d) / d^2: above it, every state with sum(x) - k = d has E > F_min."""
    X = enumerate_states(len(qubo.assets))
    f = qubo_energy(qubo_with_penalty(qubo, 0.0), X)
    d = X.sum(axis=1) - qubo.k
    f_min = f[d == 0].min()
    return float(max((f_min - f[d == dd].min()) / dd ** 2 for dd in np.unique(d) if dd != 0))


def penalty_variants(qubo: Qubo) -> dict[str, Qubo]:
    """{"exact": the stage D QUBO, "practical": 1.1 x P_gs}. `qubo` must carry the exact penalty."""
    p_gs = ground_state_threshold(qubo)
    return {"exact": qubo,
            "practical": qubo_with_penalty(qubo, BUDGET_MARGIN * p_gs if p_gs > 0 else BUDGET_FLOOR)}


@dataclass(frozen=True)
class IsingModel:
    linear: np.ndarray        # a_i
    quadratic: np.ndarray     # b_ij, strictly upper triangular
    offset: float
    norm: float

    @property
    def n(self) -> int:
        return len(self.linear)

    def operator(self):
        """SparsePauliOp of H / norm (qubit i = asset i)."""
        from qiskit.quantum_info import SparsePauliOp
        terms = [("Z", [i], a / self.norm) for i, a in enumerate(self.linear) if a != 0]
        terms += [("ZZ", [i, j], self.quadratic[i, j] / self.norm)
                  for i in range(self.n) for j in range(i + 1, self.n) if self.quadratic[i, j] != 0]
        return SparsePauliOp.from_sparse_list(terms, num_qubits=self.n)

    def to_qubo_units(self, normalised_energy):
        return self.offset + self.norm * np.asarray(normalised_energy)


def to_ising(qubo: Qubo) -> IsingModel:
    h, J = qubo.h, qubo.J
    Jsym = J + J.T
    linear = -h / 2 - Jsym.sum(axis=1) / 4
    quadratic = J / 4
    offset = qubo.const + h.sum() / 2 + J.sum() / 4
    norm = float(max(np.abs(linear).max(), np.abs(quadratic).max()))
    return IsingModel(linear, quadratic, float(offset), norm)


def ising_diagonal(model: IsingModel) -> np.ndarray:
    """E(x) for every `enumerate_states` row, from the Ising coefficients (used to test the mapping)."""
    Z = 1 - 2 * enumerate_states(model.n)
    return model.offset + Z @ model.linear + np.einsum("si,ij,sj->s", Z, model.quadratic, Z)


# ---------------------------------------------------------------- exact reference and metrics

@dataclass(frozen=True)
class Reference:
    """Exact enumeration of one QUBO, used to score any distribution over its states."""
    assets: tuple[str, ...]
    energy: np.ndarray        # E for every state
    feasible: np.ndarray      # bool
    ratio: np.ndarray         # r on feasible states, nan elsewhere
    near: np.ndarray          # feasible and r <= NEAR_OPTIMAL_FRACTION
    opt_index: int
    f_min: float
    f_max: float


def reference(qubo: Qubo) -> Reference:
    X = enumerate_states(len(qubo.assets))
    E = qubo_energy(qubo, X)
    feasible = X.sum(axis=1) == qubo.k
    f_min, f_max = float(E[feasible].min()), float(E[feasible].max())
    ratio = np.where(feasible, (E - f_min) / (f_max - f_min), np.nan)
    opt = np.flatnonzero(feasible & (E == f_min))
    if len(opt) != 1:
        raise ValueError(f"expected a unique feasible optimum, got {len(opt)}")
    return Reference(qubo.assets, E, feasible, ratio, feasible & (ratio <= NEAR_OPTIMAL_FRACTION), int(opt[0]),
                     f_min, f_max)


def selection(ref: Reference, index: int) -> str:
    bits = enumerate_states(len(ref.assets))[index]
    return ";".join(a for a, b in zip(ref.assets, bits) if b)


def counts_to_probs(counts: dict[str, int], n: int) -> np.ndarray:
    p = np.zeros(2 ** n)
    for key, c in counts.items():
        p[int(key, 2)] += c
    return p / p.sum()


def distribution_metrics(probs: np.ndarray, ref: Reference) -> dict:
    fmass = float(probs[ref.feasible].sum())
    near = float(probs[ref.near].sum())
    return {
        "p_opt": float(probs[ref.opt_index]),
        "near_mass": near,
        "near_mass_given_feasible": near / fmass if fmass > 0 else np.nan,
        "feasible_share": fmass,
        "mean_ratio_feasible": float(np.nansum(probs * np.nan_to_num(ref.ratio)) / fmass) if fmass > 0 else np.nan,
    }


def sample_metrics(probs: np.ndarray, ref: Reference) -> dict:
    """distribution_metrics plus the best sampled feasible state (probs from shot counts, so support = sampled)."""
    m = distribution_metrics(probs, ref)
    sampled = np.flatnonzero((probs > 0) & ref.feasible)
    if len(sampled):
        best = int(sampled[np.argmin(ref.energy[sampled])])
        m.update(best_ratio=float(ref.ratio[best]), best_gap=float(ref.energy[best] - ref.f_min),
                 best_selection=selection(ref, best), best_is_optimum=best == ref.opt_index)
    else:
        m.update(best_ratio=np.nan, best_gap=np.nan, best_selection="", best_is_optimum=False)
    m["n_distinct_states"] = int((probs > 0).sum())
    return m


def random_baselines(ref: Reference) -> dict:
    """Uniform over feasible portfolios and uniform over all bitstrings (= |+>^n, i.e. QAOA with all angles 0)."""
    n_f, n_all = int(ref.feasible.sum()), len(ref.energy)
    n_near = int(ref.near.sum())
    return {"n_feasible": n_f, "n_states": n_all, "n_near": n_near,
            "p_opt_random_feasible": 1 / n_f, "p_opt_random_bitstring": 1 / n_all,
            "near_share_of_feasible": n_near / n_f, "near_share_of_all_states": n_near / n_all,
            "feasible_share_of_all_states": n_f / n_all,
            "mean_ratio_random_feasible": float(np.nanmean(ref.ratio))}


# ---------------------------------------------------------------- circuits and runs

def restart_seed(p: int, restart: int) -> int:
    """Same seed for a given (p, restart) under every penalty and variant, so comparisons are paired."""
    return SEED_BASE + 100 * p + restart


def random_initial_point(p: int, seed: int) -> np.ndarray:
    """[beta_1..beta_p, gamma_1..gamma_p], uniform in [0, pi] (QAOAAnsatz parameter order: beta before gamma)."""
    return np.random.default_rng(seed).uniform(0, np.pi, 2 * p)


def extend_point(point: np.ndarray) -> np.ndarray:
    """Parameters of depth p -> depth p + 1, new layer at zero."""
    p = len(point) // 2
    return np.concatenate([point[:p], [0.0], point[p:], [0.0]])


def ansatz(operator, p: int, initial_state=None, mixer=None):
    from qiskit.circuit.library import QAOAAnsatz
    return QAOAAnsatz(operator, reps=p, initial_state=initial_state, mixer_operator=mixer)


def bound_circuit(operator, p: int, point, initial_state=None, mixer=None):
    """The QAOA circuit at `point` (QAOAAnsatz parameter order), no measurement."""
    a = ansatz(operator, p, initial_state, mixer)
    return a.assign_parameters(dict(zip(a.parameters, point)))


def statevector_probs(circuit) -> np.ndarray:
    from qiskit.quantum_info import Statevector
    return Statevector(circuit.decompose(reps=4)).probabilities()


def sample_probs(circuit, shots: int, seed: int) -> np.ndarray:
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
    from qiskit_aer import AerSimulator
    from qiskit_aer.primitives import SamplerV2
    qc = circuit.copy()
    qc.measure_all()
    pm = generate_preset_pass_manager(optimization_level=1, backend=AerSimulator(), seed_transpiler=seed)
    result = SamplerV2(default_shots=shots, seed=seed).run([pm.run(qc)]).result()[0]
    return counts_to_probs(result.data.meas.get_counts(), circuit.num_qubits)


# ---------------------------------------------------------------- warm start (stage F2)
# Egger, Marecek and Woerner (2021), "Warm-starting quantum optimization", Quantum 5, 479. The continuous relaxation
# relaxes the original formula f(x) = w_R x'Sigma x/s_R - w_M mu'x/s_M + lambda_c c'x/s_C + lambda_u u'x/s_U (full
# Sigma, diagonal included), not the QUBO's h + J form: on 0/1 vectors the two agree, but the off-diagonal-only J is
# indefinite. The budget enters as the equality constraint sum(x) = k, so c* does not depend on the penalty.

WARM_EPSILONS = (0.1, 0.25)
RELAXATION_STARTS = 5
PSD_TOL = 1e-10


@dataclass(frozen=True)
class Relaxation:
    c: np.ndarray             # c*, the relaxed optimum
    objective: float          # f(c*), a lower bound on F_min
    min_eig_risk: float       # smallest eigenvalue of w_R Sigma / s_R


def relaxed_objective(inputs, qubo: Qubo):
    """(f, grad) of the relaxation, from the inputs and the QUBO's scales and config."""
    cfg, s = qubo.config, qubo.scales
    Q = cfg.risk_weight * inputs.sigma / s.risk
    lin = (-cfg.return_weight * inputs.mu / s.ret + cfg.lambda_carbon * inputs.c / s.carbon
           + cfg.lambda_uncertainty * inputs.u / s.uncertainty)
    return (lambda x: float(x @ Q @ x + lin @ x)), (lambda x: 2 * Q @ x + lin), Q


def solve_relaxation(inputs, qubo: Qubo, starts: int = RELAXATION_STARTS, seed: int = SEED_BASE) -> Relaxation:
    """SLSQP on x in [0,1]^n, sum(x) = k. Asserts convexity and that every start reaches the same optimum."""
    from scipy.optimize import minimize
    f, grad, Q = relaxed_objective(inputs, qubo)
    n, k = len(qubo.assets), qubo.k
    min_eig = float(np.linalg.eigvalsh(Q).min())
    if min_eig < -PSD_TOL:
        raise ValueError(f"risk term is not PSD (min eigenvalue {min_eig})")
    if np.linalg.eigvalsh(np.ones((n, n))).min() < -PSD_TOL:          # budget penalty matrix 11'
        raise ValueError("budget penalty matrix is not PSD")
    rng = np.random.default_rng(seed)
    x0s = [np.full(n, k / n)] + [rng.dirichlet(np.ones(n)) * k for _ in range(starts - 1)]
    sols = []
    for x0 in x0s:
        r = minimize(f, np.clip(x0, 0, 1), jac=grad, method="SLSQP", bounds=[(0, 1)] * n,
                     constraints=[{"type": "eq", "fun": lambda x: x.sum() - k, "jac": lambda x: np.ones(n)}],
                     options={"ftol": 1e-12, "maxiter": 1000})
        if not r.success:
            raise RuntimeError(f"SLSQP failed: {r.message}")
        sols.append(r)
    best = min(sols, key=lambda r: r.fun)
    if max(r.fun for r in sols) - best.fun > 1e-7:
        raise RuntimeError("SLSQP starts disagree on a convex problem")
    c = np.clip(best.x, 0, 1)
    return Relaxation(c, f(c), min_eig)


def rounded_relaxation(c: np.ndarray, k: int) -> np.ndarray:
    """Top-k of c* as a 0/1 vector (ties broken by asset order)."""
    x = np.zeros(len(c))
    x[np.argsort(-c, kind="stable")[:k]] = 1
    return x


def regularise(c: np.ndarray, eps: float) -> np.ndarray:
    return np.clip(c, eps, 1 - eps)


def warm_thetas(c: np.ndarray) -> np.ndarray:
    return 2 * np.arcsin(np.sqrt(c))


def warm_initial_state(c: np.ndarray):
    """prod_i RY(theta_i)|0>, so P(x_i = 1) = sin^2(theta_i / 2) = c_i."""
    from qiskit import QuantumCircuit
    qc = QuantumCircuit(len(c))
    for i, t in enumerate(warm_thetas(c)):
        qc.ry(t, i)
    return qc


def warm_mixer(c: np.ndarray):
    """Per qubit the unitary RY(theta_i) RZ(-2 beta) RY(-theta_i): in circuit order RY(-theta), RZ(-2 beta), RY(theta).
    = exp(-i beta H_M) with H_M = -RY(theta) Z RY(-theta), whose ground state is the warm initial state."""
    from qiskit import QuantumCircuit
    from qiskit.circuit import Parameter
    beta = Parameter("beta")
    qc = QuantumCircuit(len(c))
    for i, t in enumerate(warm_thetas(c)):
        qc.ry(-t, i)
        qc.rz(-2 * beta, i)
        qc.ry(t, i)
    return qc


def product_probs(c: np.ndarray) -> np.ndarray:
    """Distribution of the warm initial state (p = 0) over `enumerate_states` rows."""
    X = enumerate_states(len(c))
    return np.prod(np.where(X == 1, c, 1 - c), axis=1)


def run_qaoa(operator, p: int, initial_point, seed: int, initial_state=None, mixer=None,
             maxiter: int = MAXITER, shots: int = TRAIN_SHOTS) -> dict:
    """One COBYLA run of qiskit-algorithms QAOA on Aer. Energies are in units of the normalised operator."""
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
    from qiskit_aer import AerSimulator
    from qiskit_aer.primitives import SamplerV2
    from qiskit_algorithms.minimum_eigensolvers import QAOA
    from qiskit_algorithms.optimizers import COBYLA
    from qiskit_algorithms.utils import algorithm_globals

    algorithm_globals.random_seed = seed
    n_evals = [0]

    def count(*_):
        n_evals[0] += 1

    # Aer does not know the composite QAOA gate; the circuit must be transpiled to basis gates.
    transpiler = generate_preset_pass_manager(optimization_level=1, backend=AerSimulator(), seed_transpiler=seed)
    qaoa = QAOA(sampler=SamplerV2(default_shots=shots, seed=seed), optimizer=COBYLA(maxiter=maxiter), reps=p,
                initial_state=initial_state, mixer=mixer, initial_point=np.asarray(initial_point, float),
                transpiler=transpiler, callback=count)
    t0 = time.perf_counter()
    res = qaoa.compute_minimum_eigenvalue(operator)
    seconds = time.perf_counter() - t0
    return {"optimal_point": np.asarray(res.optimal_point, float), "optimal_value": float(np.real(res.optimal_value)),
            "n_evals": int(res.cost_function_evals or n_evals[0]), "runtime_s": seconds,
            "optimizer_time_s": float(res.optimizer_time)}
