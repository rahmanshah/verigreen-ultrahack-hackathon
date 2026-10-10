// VeriGreen stage H3 residual subproblem, FY2024 MAIN trusted, warm-start QAOA p=1
// assets (qubit 0..3): KESKOB.HE KNEBV.HE NOKIA.HE WRT1V.HE; K_res = 2; exact optimum index 10 (little-endian)
// source: build_residual() -> sizing_circuit(res.instance, 1, point=[3.549169, 0.238852])
// point = [beta_1, gamma_1], selected warm_p1_restart (restart 6) in data/gold/qaoa_stage_h3_simulation_fy2024.csv
// global phase is dropped by QASM 2 (does not affect probabilities)
OPENQASM 2.0;
include "qelib1.inc";
qreg q[4];
u3(0.8442242943810582,0,0) q[0];
u1(-0.4659830511830311) q[0];
u3(1.6536069507883844,0,0) q[1];
u1(-0.36322608423452774) q[1];
cx q[0],q[1];
rz(0.4332736905629501) q[1];
cx q[0],q[1];
u3(1.3299904754204441,0,0) q[2];
u1(-0.4027561635652075) q[2];
cx q[0],q[2];
rz(0.42717755048423484) q[2];
cx q[0],q[2];
cx q[1],q[2];
rz(0.442734172049416) q[2];
cx q[1],q[2];
u3(2.498091544796509,0,0) q[3];
u1(-0.23265059202085608) q[3];
cx q[0],q[3];
rz(0.4370116734234774) q[3];
cx q[0],q[3];
u3(-0.8442242943810582,0,0) q[0];
u3(0,0,-7.098338) q[0];
u3(0.8442242943810582,0,0) q[0];
cx q[1],q[3];
rz(0.477704) q[3];
cx q[1],q[3];
u3(-1.6536069507883844,0,0) q[1];
u3(0,0,-7.098338) q[1];
u3(1.6536069507883844,0,0) q[1];
cx q[2],q[3];
rz(0.4723767267725472) q[3];
cx q[2],q[3];
u3(-1.3299904754204441,0,0) q[2];
u3(0,0,-7.098338) q[2];
u3(1.3299904754204441,0,0) q[2];
u3(-2.498091544796509,0,0) q[3];
u3(0,0,-7.098338) q[3];
u3(2.498091544796509,0,0) q[3];