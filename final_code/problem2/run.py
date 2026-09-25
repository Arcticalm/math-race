"""Run Question 2 independently with the shared finite pattern library."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from final_code.problem1.solver import ROOT
from final_code.problem2.master import solve
from final_code.problem2.patterns import generate
from final_code.problem2.terrain_audit import audit_clearance
from final_code.problem2.transport import (
    RouteEvaluator, _validate, load_resources, load_task_boxes, write_outputs,
)


def run(output: Path, time_limit: float = 120.0) -> dict:
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose an empty output directory")
    boxes = load_task_boxes()
    drones, batteries = load_resources()
    evaluator = RouteEvaluator(0.2, 1.0)
    try:
        pool, _ = generate(boxes, evaluator, batteries)
        result, search = solve(pool, boxes, drones, batteries, evaluator,
                               time_limit=time_limit)
        if result is None:
            raise RuntimeError(f"No Question 2 incumbent within limits: {search['status']}")
        metrics = _validate(result["sorties"], boxes, drones, batteries, evaluator)
        metrics["terrain_clearance"] = audit_clearance(result["sorties"], evaluator)
        metrics.update(search=search, global_optimal=False,
                       objective_profile="makespan, weighted lateness, energy, sorties")
        if not metrics["feasible"] or not metrics["terrain_clearance"]["feasible"]:
            raise RuntimeError("Question 2 continuous-time audit failed")
        write_outputs(result["sorties"], metrics, boxes, output, 0.2, 1.0)
        assumptions = output / "model_assumptions.json"
        data = json.loads(assumptions.read_text(encoding="utf-8"))
        data.update(solver="shared patterns, CP-SAT exact cover and scheduling",
                    global_optimal=False)
        assumptions.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return metrics
    finally:
        evaluator.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/problem2/final_code")
    parser.add_argument("--time-limit", type=float, default=120.0)
    args = parser.parse_args()
    if args.time_limit <= 0:
        parser.error("time-limit must be positive")
    result = run(args.output, args.time_limit)
    print(json.dumps({key: result[key] for key in ("feasible", "makespan_s", "sortie_count")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
