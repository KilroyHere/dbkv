# sim: KV simulator (G1) and open-loop capacity simulator

- `kvsim.py`: G1 iteration-level simulator of N SQL agents sharing one GPU's KV pool, with retention policies (pin TTLs).
- `g1_grid.py`: the G1 grid (policy × offload × context × sessions × pause mix × seed) and the oracle gap. G1 is closed: D3 was ruled out (`results/g1v2b_gap.csv`).
- `refit_costs.py`: fits the simulator's GPU cost parameters to G3 measurements (`results/g3_costs.json`).
- `fidelity.py`: re-runs the G3 cells in the simulator and compares p95s (`results/g1_fidelity.csv`).
- `openloop.py` / `openloop_rates.py`: open-loop extension with Poisson arrivals of the real explore agent's tasks. They predicted Phase 2's capacity (~190/min) and a >80% p95 cut (`results/openloop_sim_summary.md`).
- `pauses.py`: SQL pause-duration distributions shared by the simulator and `harness/replay.py`.
