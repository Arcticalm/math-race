# Problem 1 solver

Run from the repository root (Python 3.11+):

```bash
uv run --with-requirements src/problem1/requirements.txt python -m src.problem1.solver
```

Sensitivity scenarios use a common reserve fraction for A/B/C:

```bash
uv run --with-requirements src/problem1/requirements.txt python -m src.problem1.solver --reserve 0.10 0.15 0.20 0.25 0.30
```

Outputs are written to `outputs/problem1/` (ignored as generated results): JSON details and CSV tables for baseline safe payloads, batches, and sensitivity totals. The optimizer applies the documented lexicographic objective: minimum flight count, then energy, then cumulative work time. Cumulative work time is preparation + loading + flight + single-stop handoff, summed over sorties; it is not a fleet makespan.

## Energy model caveat

The problem statement defines payload-adjusted standard range, flight time, and the return reserve constraint, but does not provide an explicit formula for transport horizontal energy or climb-energy efficiency units. The initial implementation therefore calibrates a baseline horizontal energy rate as `usable battery energy / empty standard range`, and scales energy per distance inversely with the payload-adjusted range. It checks each one-way leg against the payload-adjusted outbound range or empty return range. Climb energy is computed from takeoff mass, climb height, gravity, and the workbook's climb-efficiency value interpreted as propulsion efficiency. These are explicit modeling assumptions, not fully specified source formulas; replace `load_energy_per_meter` / `leg_flight` when a prescribed energy law becomes available. Numerical optima must be interpreted conditionally on these assumptions.

The GeoTIFF metadata declares EPSG:4326 and 1/3600-degree cells. Flight leg distances use a great-circle calculation; route terrain is sampled along the coordinate-linear path at intervals no greater than 30 m. Service-area and O01 tabular elevations are used for operating heights, while DEM samples determine the prescribed route cruise clearance. The DEM is a surface model; this implementation does not model obstacle clearance beyond the problem's specified 50 m above sampled maximum.

## Git scope

Track `src/problem1/`, `tests/test_problem1.py`, and this documentation. Generated `outputs/` and Python caches are ignored via the repository `.gitignore`; do not add editor-local `.vscode/` files to this feature.
