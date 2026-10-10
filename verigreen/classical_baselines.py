"""Classical heuristics on the same K-of-N QUBO, as the reference any QAOA result is read against (stage F).

Both search feasible portfolios only (swap one held asset for one not held), so the budget penalty never enters.
One "evaluation" = one computation of f(x) for one portfolio; the budget caps evaluations, and a run "hits" the
optimum when it first evaluates the exact optimal portfolio. Brute force over all states remains the exact solver.

- greedy_swap: best-improvement swap local search. Each step evaluates all k (n - k) swap neighbours (truncated at
  the budget), moves to the best if it improves, otherwise restarts from a new random feasible portfolio.
- simulated_annealing: one random swap per evaluation, Metropolis acceptance, geometric cooling from T0 to
  T0 * SA_FINAL_FRACTION over the budget. T0 = std of f(y) - f(x) over SA_CALIBRATION_SWAPS random swaps from random
  feasible portfolios (fixed seed, not counted in any run's budget).
"""
from __future__ import annotations

import numpy as np

from verigreen.qubo import Qubo

BUDGET = 50_000
N_RUNS = 100
SA_FINAL_FRACTION = 1e-3
SA_CALIBRATION_SWAPS = 1_000
SA_CALIBRATION_SEED = 0


class Objective:
    """f(x) = obj_h.x + x' obj_J x on 0/1 vectors, with an evaluation counter."""

    def __init__(self, qubo: Qubo):
        self.h, self.J = qubo.obj_h, qubo.obj_J
        self.n, self.k = len(qubo.assets), qubo.k
        self.evals = 0

    def __call__(self, X: np.ndarray) -> np.ndarray:
        X = np.atleast_2d(X)
        self.evals += len(X)
        return X @ self.h + np.einsum("si,ij,sj->s", X, self.J, X)


def _random_portfolio(rng, n: int, k: int) -> np.ndarray:
    x = np.zeros(n)
    x[rng.choice(n, k, replace=False)] = 1
    return x


def _swap_neighbours(x: np.ndarray) -> np.ndarray:
    held, out = np.flatnonzero(x == 1), np.flatnonzero(x == 0)
    Y = np.repeat(x[None, :], len(held) * len(out), axis=0)
    rows = np.arange(len(Y))
    Y[rows, np.repeat(held, len(out))] = 0
    Y[rows, np.tile(out, len(held))] = 1
    return Y


def greedy_swap(qubo: Qubo, x_opt: np.ndarray, seed: int, budget: int = BUDGET) -> dict:
    rng, f = np.random.default_rng(seed), Objective(qubo)
    first_hit, best, restarts = None, np.inf, 0

    def check(X, before):
        nonlocal first_hit
        if first_hit is None:
            hits = np.flatnonzero((X == x_opt).all(axis=1))
            if len(hits):
                first_hit = before + int(hits[0]) + 1

    while f.evals < budget:
        restarts += 1
        x = _random_portfolio(rng, f.n, f.k)
        before = f.evals
        fx = float(f(x)[0])
        check(x[None, :], before)
        best = min(best, fx)
        while f.evals < budget:
            Y = _swap_neighbours(x)[: budget - f.evals]
            before = f.evals
            fy = f(Y)
            check(Y, before)
            i = int(np.argmin(fy))
            if fy[i] < fx - 1e-12:
                x, fx = Y[i], float(fy[i])
                best = min(best, fx)
            else:
                break
    return {"first_hit_eval": first_hit, "best_f": best, "evals": f.evals, "restarts": restarts}


def calibrate_temperature(qubo: Qubo, swaps: int = SA_CALIBRATION_SWAPS, seed: int = SA_CALIBRATION_SEED) -> float:
    rng, f = np.random.default_rng(seed), Objective(qubo)
    deltas = []
    for _ in range(swaps):
        x = _random_portfolio(rng, f.n, f.k)
        y = x.copy()
        y[rng.choice(np.flatnonzero(x == 1))] = 0
        y[rng.choice(np.flatnonzero(x == 0))] = 1
        deltas.append(float(f(y)[0] - f(x)[0]))
    return float(np.std(deltas))


def simulated_annealing(qubo: Qubo, x_opt: np.ndarray, seed: int, t0: float, budget: int = BUDGET) -> dict:
    rng, f = np.random.default_rng(seed), Objective(qubo)
    x = _random_portfolio(rng, f.n, f.k)
    fx = float(f(x)[0])
    first_hit = 1 if (x == x_opt).all() else None
    best = fx
    temps = t0 * SA_FINAL_FRACTION ** (np.arange(1, budget) / (budget - 1))
    for t in temps:
        held, out = np.flatnonzero(x == 1), np.flatnonzero(x == 0)
        i, j = rng.choice(held), rng.choice(out)
        y = x.copy()
        y[i], y[j] = 0, 1
        fy = float(f(y)[0])
        if first_hit is None and (y == x_opt).all():
            first_hit = f.evals
        if fy <= fx or rng.random() < np.exp(-(fy - fx) / t):
            x, fx = y, fy
            best = min(best, fx)
    return {"first_hit_eval": first_hit, "best_f": best, "evals": f.evals, "restarts": 1}
