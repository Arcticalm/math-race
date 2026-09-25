# Independent Problem 3 solve path

This entry point does not read `outputs/problem23`, any Q2 schedule, or any
saved sortie/audit CSV. It rebuilds transport schedules from the source task,
aircraft, battery and DEM workbooks, then runs the Problem 3 trajectory,
communication, delay-coordination and relay-resource model.

Run from the repository root:

```bash
uv run --with-requirements src/problem3/requirements.txt \
  python -m src.problem3.independent \
  --output outputs/problem3/independent \
  --sample-step 10 --relay-candidate-step 10 \
  --max-iterations 3 --time-limit 180 --objective delay \
  --max-relay-sorties 8 --max-transport-delay 2400
```

The transport seed uses the repository's constructive route generator on raw
inputs. It evaluates its single-site and pairwise merged candidates, then
independently reschedules each fixed route grouping with CP-SAT and chooses the
quickest audited result. It does not load any saved Problem 2 schedule. This is
not a global joint optimizer over every box partition and route. Problem 3 then
delays those generated sorties as needed and recomputes trajectories and relay
coverage after each delay iteration.

`screening.json` reports feasibility, objective metrics, communication
certification and resource audits. CSVs retain the transport schedule,
trajectory phases, direct-link intervals, relay schedule, two-hop link checks,
and checkpoint/continuous communication audits. Coarser sampling reduces
runtime but can change candidate availability; all reported solutions still
require the continuous communication certification to pass.

The independently rebuilt run currently stored at
`outputs/problem3/independent/` is feasible: 25 transport sorties and 7 relay
missions (32 total), with a 10192.567 s makespan. This is 225.089 s below the
Q2-seeded final schedule's 10417.656 s. All 46 hard-deadline checks pass,
continuous communication has zero uncovered seconds, and the relay resource
audit reports no conflicts. This is the best certified result from the finite
raw-input route candidates and stated solver limits, not a global optimality
proof. The 2400 s maximum transport delay is an explicit constraint used to
keep the joint completion time below the comparison result.
