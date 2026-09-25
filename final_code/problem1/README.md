# Problem 1 solver

Run from the repository root (Python 3.10+):

```bash
.venv/bin/python -m final_code.problem1.solver
```

Sensitivity scenarios append common reserve fractions and horizontal-energy calibration multipliers to the default baseline:

```bash
.venv/bin/python -m final_code.problem1.solver --reserve 0.10 0.15 0.25 0.30 --energy-scale 0.8 1.2
```

Outputs are written to `outputs/problem1/` (ignored as generated results): JSON details, template-aligned `problem1_submission.xlsx` and `batches.csv`, a detailed batch table with leg energies and return SOC, site summaries, safe-payload/sensitivity tables, trade-off table, and PNG figures. The baseline always uses the return-SOC lower bound in the aircraft workbook (20% for A/B/C); any `--reserve` and `--energy-scale` values are appended as sensitivity scenarios. Scenarios that cannot deliver all boxes are explicitly marked infeasible, with affected sites listed.

Three representative objective priority policies are compared: sorties → energy → cumulative work time, energy → sorties → time, and time → sorties → energy. `objective_tradeoff.csv` lists these solutions and indicates nondominance among the sampled policies only; it is not claimed to be the complete Pareto frontier. Cumulative work time is preparation + loading + flight + single-stop handoff, summed over sorties; it is not a fleet makespan.

## Energy model caveat

The problem statement defines payload-adjusted standard range, flight time, and the return reserve constraint, but does not provide an explicit formula for transport horizontal energy or climb-efficiency units. The baseline calibrates horizontal energy as `usable battery energy (kWh) / empty standard range (m)` (kWh/m), then scales that rate by `empty range / payload-adjusted range`. Climb energy uses `mass (kg) × g (m/s²) × climb height (m) / (3.6×10⁶ × efficiency)`, interpreting the workbook's efficiency as a dimensionless propulsion efficiency. It checks each one-way leg against the payload-adjusted outbound range or empty return range. These are explicit modeling assumptions, not fully specified source formulas; numerical optima are conditional on them and should be accompanied by alternative energy-rate/efficiency sensitivity analysis in the paper.

The GeoTIFF metadata declares EPSG:4326 and 1/3600-degree cells. Flight leg distances use a great-circle calculation; route terrain is sampled along the coordinate-linear path at intervals no greater than 30 m. Service-area and O01 tabular elevations are used for operating heights, while DEM samples determine the prescribed route cruise clearance. The DEM is a surface model; this implementation does not model obstacle clearance beyond the problem's specified 50 m above sampled maximum.
