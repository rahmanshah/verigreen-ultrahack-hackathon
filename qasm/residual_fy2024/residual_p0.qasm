// VeriGreen stage H3 residual subproblem, FY2024 MAIN trusted, warm-start QAOA p=0
// assets (qubit 0..3): KESKOB.HE KNEBV.HE NOKIA.HE WRT1V.HE; K_res = 2; exact optimum index 10 (little-endian)
// source: build_residual() -> sizing_circuit(res.instance, 0)
// p=0: warm-start initial state only, no parameters
// global phase is dropped by QASM 2 (does not affect probabilities)
OPENQASM 2.0;
include "qelib1.inc";
qreg q[4];
ry(0.8442242943810582) q[0];
ry(1.6536069507883844) q[1];
ry(1.3299904754204441) q[2];
ry(2.498091544796509) q[3];