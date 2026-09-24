# Problem 3 implementation

Run the current communication screening from the repository root:

```bash
uv run --with-requirements src/problem3/requirements.txt python -m src.problem3.solver
```

The first implementation stage reuses the audited Problem 2 transport schedule, reconstructs each sortie's climb/cruise/descent/handoff timeline, calculates bidirectional radio thresholds from the supplied workbook, screens direct transport-to-G01 links against the DSM, generates sampled relay hover/energy candidates, and attempts a greedy relay-airframe/component assignment. It writes diagnostic `link_samples.csv`, `direct_link_intervals.csv`, `relay_candidates.csv`, `relay_schedule.csv`, `node_dsm_elevation_audit.csv`, and `screening.json` to `outputs/problem3/`.

This stage does not yet produce final Q3 template sheets or a feasible joint schedule. Current relay dispatch is greedy and can leave direct-link gaps uncovered; fixed-step link sampling does not certify continuous communication. Results explicitly report uncovered intervals and must not be treated as a feasible Problem 3 solution until transport start times can be adjusted, all relay/energy resources are jointly scheduled, and final event-driven/adaptive link replay passes.

Tests:

```bash
uv run --with-requirements src/problem3/requirements.txt python -m unittest tests.test_problem3 -v
```
