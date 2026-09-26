"""Run Question 3 with joint transport and relay reselection."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from final_code.problem1.solver import ROOT
from final_code.problem2.master import solve
from final_code.problem2.patterns import generate
from final_code.problem2.transport import RouteEvaluator, load_resources, load_task_boxes
from final_code.problem3.communication import build_profiles, locations
from final_code.problem3.refine import refine_joint
from final_code.problem3.physics import LinkEvaluator
from final_code.problem3.trajectory import _plot_problem3_overview, build_trajectory
from final_code.run_all import audit_and_export_joint


def run(output: Path, time_limit: float = 120.0, max_relays: int = 10, partition_groups: int = 0) -> dict:
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose an empty output directory")
    boxes = load_task_boxes()
    drones, batteries = load_resources()
    evaluator = RouteEvaluator(0.2, 1.0)
    try:
        pool, _ = generate(boxes, evaluator, batteries)
        links = LinkEvaluator()
        try:
            candidate_locations = locations(links)
        finally:
            links.close()
        q2, q2_search = solve(pool, boxes, drones, batteries, evaluator,
                              time_limit=time_limit)
        profiles = build_profiles(pool, candidate_locations)
        result, search = solve(pool, boxes, drones, batteries, evaluator,
                               time_limit=time_limit, profiles=profiles,
                               locations=candidate_locations, max_relays=max_relays,
                               hint=q2["sorties"] if q2 else None, partition_groups=partition_groups)
        if result is None:
            initial_search = search
            links = LinkEvaluator()
            try:
                candidate_locations = locations(links, expanded=True)
            finally:
                links.close()
            profiles = build_profiles(pool, candidate_locations)
            result, search = solve(pool, boxes, drones, batteries, evaluator,
                                   time_limit=time_limit, profiles=profiles,
                                   locations=candidate_locations, max_relays=max_relays,
                                   hint=q2["sorties"] if q2 else None, partition_groups=partition_groups)
            search["initial_location_search"] = initial_search
            search["expanded_location_count"] = len(candidate_locations)
        if result is None:
            raise RuntimeError(f"No Question 3 incumbent within limits: {search['status']}")
        result, refinement = refine_joint(result, profiles, evaluator, boxes, drones, batteries)
        search["continuous_refinement"] = refinement
        metrics = audit_and_export_joint(output, result, search, profiles, boxes,
                                         drones, batteries, evaluator)
        if not metrics["feasible"]:
            raise RuntimeError("Question 3 continuous-time audit failed")
        _plot_problem3_overview(output / "routes_relays.png",
                                build_trajectory(result["sorties"]), result["relays"])
        return metrics
    finally:
        evaluator.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/q3")
    parser.add_argument("--time-limit", type=float, default=120.0)
    parser.add_argument("--max-relays", type=int, default=10)
    parser.add_argument("--partition-groups", type=int, choices=(0, 2, 3), default=0)
    args = parser.parse_args()
    if not math.isfinite(args.time_limit) or args.time_limit <= 0 or args.max_relays < 0:
        parser.error("time-limit must be positive and max-relays nonnegative")
    result = run(args.output, args.time_limit, args.max_relays, args.partition_groups)
    print(json.dumps({key: result[key] for key in ("feasible", "joint_makespan_s", "total_sortie_count")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
