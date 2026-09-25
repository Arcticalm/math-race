# Problem 2 scheduler

Run from the repository root:

```bash
uv run --with-requirements src/problem2/requirements.txt python -m src.problem2.solver
```

The solver reuses Problem 1's route-energy assumptions, builds feasible per-site batches, attempts safe multi-site batch merges, then compares several deterministic job-order schedules. Aircraft and shared batteries are scheduled independently, with the battery unavailable until fully recharged. Results are written to `outputs/problem2/`, including the submission workbook, CSV audit tables, and route/resource/delivery figures.

The scheduler tries four dispatch orders (minimum slack, deadline, shortest flight, longest flight) and compares single-site grouping with a greedy sequence of pairwise, two-site merges. It evaluates balanced and energy-oriented resource-assignment heuristics for both grouping families, rejects hard-deadline violations during assignment, and selects the primary schedule from feasible balanced candidates by weighted expected-time lateness, makespan, energy and sortie count. Exact duplicate schedules are listed once with all applicable strategy labels. This is a comparison across generated candidates, not an exhaustive search: batches are not globally regrouped, merges are limited to two service areas, and the scheduler does not backtrack. Results are feasible heuristic candidates, not global optima or a certified Pareto frontier.

The audit distinguishes hard-deadline compliance from on-time performance against expected delivery times for all eligible items, including per-item-type rates. It independently replays stored leg order, payload reduction after each site, preparation/loading durations, handoff and flight timeline, return time, delivery timestamps, and resource availability. Energy feasibility is additionally reevaluated with the shared Problem 1 route physics, so it is a consistency check rather than an independent physical model. `objective_tradeoff.csv` explicitly labels the solutions as heuristic candidates, not Pareto-optimal results. Generated figures are `routes.png`, `resource_gantt.png`, and `delivery_times.png`. The output also includes `problem2_program.zip`, bundling runnable source, requirements and the submission template; it expects the project's `data/` directory to remain at the repository root.

The workbook's `开始时刻` is preparation start. Preparation and loading are serial. Delivery handoff time occurs at each service area before the next leg (or final return); it is included in the sortie's return time. The transport airframe is released upon return because no separate airframe turnaround parameter is supplied; the battery is independently occupied through flight and charged after return until 100% SOC. These are modeling assumptions recorded in `model_assumptions.json`.
