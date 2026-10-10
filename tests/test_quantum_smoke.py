"""Smoke test for the quantum stack: imports, then a 4-asset toy QAOA on the Aer simulator.

Not a model of the real problem. It only proves the toolchain runs end to end and that QAOA
finds the exact optimum of a toy QUBO that is solved exactly by brute force.
"""
import itertools
import time

import numpy as np

TOY_MU = np.array([0.10, 0.07, 0.12, 0.05])
TOY_SIGMA = np.array([[0.10, 0.02, 0.04, 0.00],
                      [0.02, 0.08, 0.01, 0.01],
                      [0.04, 0.01, 0.12, 0.02],
                      [0.00, 0.01, 0.02, 0.06]])
TOY_K = 2
TOY_RISK_AVERSION = 1.0


def toy_program():
    from qiskit_optimization import QuadraticProgram
    qp = QuadraticProgram("toy_portfolio")
    for i in range(len(TOY_MU)):
        qp.binary_var(f"x{i}")
    qp.minimize(linear=-TOY_MU, quadratic=TOY_RISK_AVERSION * TOY_SIGMA)
    qp.linear_constraint({f"x{i}": 1 for i in range(len(TOY_MU))}, "==", TOY_K, "budget")
    return qp


def brute_force():
    best = None
    for bits in itertools.product([0, 1], repeat=len(TOY_MU)):
        x = np.array(bits)
        if x.sum() != TOY_K:
            continue
        obj = float(-TOY_MU @ x + TOY_RISK_AVERSION * x @ TOY_SIGMA @ x)
        if best is None or obj < best[0]:
            best = (obj, bits)
    return best


def run_toy_qaoa(reps=2, seed=7):
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
    from qiskit_aer import AerSimulator
    from qiskit_aer.primitives import SamplerV2
    from qiskit_algorithms.minimum_eigensolvers import QAOA
    from qiskit_algorithms.optimizers import COBYLA
    from qiskit_algorithms.utils import algorithm_globals
    from qiskit_optimization.algorithms import MinimumEigenOptimizer

    algorithm_globals.random_seed = seed
    backend = AerSimulator(seed_simulator=seed)
    sampler = SamplerV2(default_shots=4096, seed=seed)
    # Aer does not know the composite QAOA gate; the circuit must be transpiled to basis gates.
    transpiler = generate_preset_pass_manager(optimization_level=1, backend=backend, seed_transpiler=seed)
    qaoa = QAOA(sampler=sampler, optimizer=COBYLA(maxiter=100), reps=reps, transpiler=transpiler)
    t0 = time.perf_counter()
    result = MinimumEigenOptimizer(qaoa).solve(toy_program())
    return result, time.perf_counter() - t0


def test_four_packages_import():
    import qiskit
    import qiskit_aer
    import qiskit_algorithms
    import qiskit_optimization
    for mod in (qiskit, qiskit_aer, qiskit_algorithms, qiskit_optimization):
        assert mod.__version__


def test_toy_qaoa_on_aer_finds_brute_force_optimum():
    best_obj, best_bits = brute_force()
    result, seconds = run_toy_qaoa()
    got = tuple(int(round(v)) for v in result.x)
    assert result.status.name == "SUCCESS"
    assert sum(got) == TOY_K
    assert got == best_bits, f"QAOA picked {got}, exact optimum is {best_bits}"
    assert abs(result.fval - best_obj) < 1e-9
    print(f"  toy QAOA: picked {got}, fval {result.fval:.4f}, exact {best_obj:.4f}, {seconds:.2f}s")


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(tests)} passed")
