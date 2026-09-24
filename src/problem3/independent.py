"""Problem 3 entry point that builds transport sorties from source inputs.

Unlike solver.py, this path never reads outputs/problem23. It constructs its
own transport candidates from the raw task, aircraft, battery and terrain data,
then jointly coordinates the selected candidate with relay service windows.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from src.problem1.solver import ROOT
from src.problem21.solver import (
    RouteEvaluator, _validate, load_resources,
    solve as construct_transport_candidates,
)
from src.problem3.audit import audit_checkpoints, audit_communication, audit_relay_resources
from src.problem3.solver import _hard_deadline_audit
from src.problem3.timeline import coordinate_timeline


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        fieldnames = list(dict.fromkeys(key for row in rows for key in row))
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _select_transport_candidate(candidates: list[dict]) -> dict:
    """Prefer the quickest independently constructed raw-input schedule."""
    return min(candidates, key=lambda item: (
        item["metrics"]["makespan_s"],
        item["metrics"]["weighted_all_expected_tardiness"],
        item["metrics"]["sortie_count"],
        item["metrics"]["total_energy_kwh"],
    ))


def _reschedule_raw_candidates(candidates, boxes, drones, batteries, time_limit_s):
    """Reassign each raw route grouping without loading a saved Q2 schedule."""
    from src.problem23.cp_sat import solve_fixed_routes

    scheduled = []
    evaluator = RouteEvaluator(0.2, 1.0)
    try:
        for candidate in candidates:
            routes, search = solve_fixed_routes(
                candidate["sorties"], drones, batteries, evaluator, time_limit_s,
                num_search_workers=1, random_seed=11,
            )
            if routes is None:
                continue
            metrics = _validate(routes, boxes, drones, batteries, evaluator)
            if not metrics["feasible"]:
                continue
            scheduled.append({
                **candidate, "sorties": routes, "metrics": metrics,
                "transport_scheduler": search,
            })
    finally:
        evaluator.close()
    return scheduled


def run(output_dir: Path, sample_step_s: float = 30.0,
        relay_candidate_step_s: float = 30.0, max_iterations: int = 4,
        time_limit_s: float = 60.0, objective: str = "delay",
        max_relay_sorties: int | None = None,
        maximum_transport_delay_s: float = 10800.0) -> dict:
    """Build and solve a Q3 schedule without consuming any Q2 result files."""
    sorties, _, boxes, candidates = construct_transport_candidates(return_candidates=True)
    if not candidates:
        raise RuntimeError("The raw-input transport constructor returned no feasible schedule")
    drones, batteries = load_resources()
    candidates = _reschedule_raw_candidates(
        candidates, boxes, drones, batteries, min(30.0, time_limit_s)
    )
    if not candidates:
        raise RuntimeError("No raw-input route grouping passed independent CP-SAT scheduling")
    chosen = _select_transport_candidate(candidates)
    seed_sorties = chosen["sorties"]

    timeline = coordinate_timeline(
        seed_sorties, sample_step_s, relay_candidate_step_s, max_iterations,
        time_limit_s, objective, max_relay_sorties, maximum_transport_delay_s,
        relay_objective="robust",
    )
    final_sorties = timeline["sorties"]
    evaluator = RouteEvaluator(0.2, 1.0)
    try:
        transport_metrics = _validate(final_sorties, boxes, drones, batteries, evaluator)
    finally:
        evaluator.close()

    communication_rows, communication_metrics, link_rows = audit_checkpoints(
        timeline["samples"], timeline["intervals"], timeline["selected"]
    )
    continuous_rows, continuous_metrics = audit_communication(
        timeline["phases"], timeline["selected"], step_s=30.0, minimum_step_s=1.0
    )
    relay_metrics = audit_relay_resources(timeline["selected"])
    deadline_metrics = _hard_deadline_audit(final_sorties)
    schedule = timeline["schedule"]
    feasible = all((
        transport_metrics["feasible"], deadline_metrics["passed"],
        schedule["feasible_cover"], communication_metrics["certified"],
        continuous_metrics["certified"], relay_metrics["feasible"],
    ))
    result = {
        "feasible": feasible,
        "status": "feasible independently constructed Q3 schedule" if feasible else "no certified feasible schedule",
        "transport_source": "raw workbook inputs; independently rebuilt single-site and merged route candidates",
        "transport_candidate_labels": chosen["labels"],
        "transport_candidate_count": len(candidates),
        "transport_seed_makespan_s": chosen["metrics"]["makespan_s"],
        "transport_seed_scheduler": chosen["transport_scheduler"],
        "transport_sortie_count": len(final_sorties),
        "relay_sortie_count": len(schedule["selected"]),
        "total_sortie_count": len(final_sorties) + len(schedule["selected"]),
        "joint_makespan_s": max(
            [item.return_s for item in final_sorties]
            + [item["return_o01_s"] for item in schedule["selected"]]
        ),
        "transport_validation": transport_metrics,
        "hard_deadline_audit": deadline_metrics,
        "communication_validation": communication_metrics,
        "continuous_communication_validation": continuous_metrics,
        "relay_validation": relay_metrics,
        "relay_schedule": {key: value for key, value in schedule.items() if key != "selected"},
        "coordination": timeline["coordination"],
        "candidate_history": timeline["history"],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "transport_schedule.csv", [{
        "sortie": item.code, "drone": item.drone, "aircraft": item.aircraft,
        "battery": item.battery, "preparation_start_s": item.prep_start_s,
        "takeoff_s": item.takeoff_s, "return_s": item.return_s,
        "route": "->".join(item.route), "box_count": len(item.boxes),
        "energy_kwh": item.energy_kwh, "return_soc_percent": item.battery_soc_return_percent,
    } for item in final_sorties])
    _write_csv(output_dir / "trajectory_phases.csv", [{
        "sortie": phase.sortie, "phase": phase.name, "start_s": phase.start_s,
        "end_s": phase.end_s, "start_longitude": phase.start_node.longitude,
        "start_latitude": phase.start_node.latitude, "end_longitude": phase.end_node.longitude,
        "end_latitude": phase.end_node.latitude, "start_altitude_m": phase.start_altitude_m,
        "end_altitude_m": phase.end_altitude_m,
    } for phase in timeline["phases"]])
    _write_csv(output_dir / "direct_link_intervals.csv", timeline["intervals"])
    _write_csv(output_dir / "relay_schedule.csv", schedule["selected"])
    _write_csv(output_dir / "two_hop_link_audit.csv", link_rows)
    _write_csv(output_dir / "communication_audit.csv", communication_rows)
    _write_csv(output_dir / "continuous_communication_audit.csv", continuous_rows)
    (output_dir / "screening.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Solve Problem 3 from raw inputs without Q2 output")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/problem3/independent")
    parser.add_argument("--sample-step", type=float, default=30.0)
    parser.add_argument("--relay-candidate-step", type=float, default=30.0)
    parser.add_argument("--max-iterations", type=int, default=4)
    parser.add_argument("--time-limit", type=float, default=60.0)
    parser.add_argument("--objective", choices=("sorties", "delay"), default="delay")
    parser.add_argument("--max-relay-sorties", type=int)
    parser.add_argument("--max-transport-delay", type=float, default=10800.0)
    args = parser.parse_args()
    if (min(args.sample_step, args.relay_candidate_step, args.time_limit,
            args.max_transport_delay) <= 0 or args.max_iterations < 1
            or (args.max_relay_sorties is not None and args.max_relay_sorties < 0)):
        parser.error("time steps, time limit and maximum transport delay must be positive")
    result = run(args.output, args.sample_step, args.relay_candidate_step,
                 args.max_iterations, args.time_limit, args.objective,
                 args.max_relay_sorties, args.max_transport_delay)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["feasible"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
