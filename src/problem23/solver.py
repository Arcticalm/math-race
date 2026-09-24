"""Time-first Problem 2 solver over reproducible grouping candidates.

When OR-Tools is available, each grouping receives a joint drone/battery CP-SAT
schedule. A deterministic audited scheduler remains available as a fallback.
"""

from __future__ import annotations

import argparse
import csv
import json
import zipfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.problem1.solver import ROOT
from src.problem21.solver import (
    RouteEvaluator, _merge_multisite, _partition_by_site, _schedule_candidates,
    _validate, load_resources, load_task_boxes, write_outputs,
)
from src.problem23.groups import exact_site_partitions, signature

OUTPUT_DEFAULT = ROOT / "outputs" / "problem23"


def solve(reserve: float = 0.2, energy_scale: float = 1.0,
          cp_sat_time_limit_s: float = 30.0):
    boxes = load_task_boxes()
    drones, batteries = load_resources()
    evaluator = RouteEvaluator(reserve, energy_scale)
    try:
        groupings = exact_site_partitions(boxes, evaluator)
        groupings["constructive"] = _partition_by_site(boxes, evaluator)
        for name, routes in list(groupings.items()):
            groupings[name + "_merged"] = _merge_multisite(routes, evaluator)
        unique = {}
        for name, routes in groupings.items():
            entry = unique.setdefault(signature(routes), {"routes": routes, "names": []})
            entry["names"].append(name)

        try:
            from ortools.sat.python import cp_model  # noqa: F401
            from src.problem23.cp_sat import solve_fixed_routes
            cp_sat_available = True
        except ImportError:
            cp_sat_available = False

        candidates = []
        for group in unique.values():
            label = " | ".join(group["names"])
            attempts = []
            if cp_sat_available:
                schedule, search = solve_fixed_routes(
                    group["routes"], drones, batteries, evaluator, cp_sat_time_limit_s,
                )
                if schedule is not None:
                    attempts.append(("cp_sat", schedule, search))
            for profile in ("balanced", "energy"):
                schedule, search = _schedule_candidates(
                    group["routes"], drones, batteries, evaluator, profile,
                )
                if schedule is not None:
                    attempts.append(("heuristic_" + profile, schedule, search))
            for method, schedule, search in attempts:
                metrics = _validate(schedule, boxes, drones, batteries, evaluator)
                if not metrics["feasible"]:
                    continue
                metrics.update({"strategy": label + "/" + method,
                                "method": method, "search": search if method == "cp_sat" else {
                                    "dispatch_order": search.get("dispatch_order"),
                                    "assignment_profile": search.get("assignment_profile"),
                                }})
                candidates.append({"sorties": schedule, "metrics": metrics})
        if not candidates:
            raise ValueError("No feasible time-first candidate")
        chosen = min(candidates, key=lambda item: (
            item["metrics"]["makespan_s"],
            item["metrics"]["weighted_all_expected_tardiness"],
            item["metrics"]["total_energy_kwh"],
            item["metrics"]["sortie_count"],
        ))
        metrics = dict(chosen["metrics"])
        metrics.update({
            "objective_profile": "makespan, weighted lateness, energy, sorties",
            "primary_candidate": [metrics["strategy"]],
            "candidate_scope": "exact per-site partitions and constructive partitions, optional two-site merges; CP-SAT or heuristic scheduling for each fixed grouping",
            "optimality_status": "best audited candidate; global Problem 2 optimum unproven",
            "cp_sat_available": cp_sat_available,
            "feasible_candidate_count": len(candidates),
            "tradeoff_candidates": {item["metrics"]["strategy"]: item["metrics"] for item in candidates},
        })
        return chosen["sorties"], metrics, boxes, candidates
    finally:
        evaluator.close()


def write_time_comparison(output_dir: Path, candidates: list[dict], selected: str) -> None:
    columns = ["strategy", "method", "sortie_count", "makespan_s",
               "weighted_all_expected_tardiness", "total_energy_kwh", "selected"]
    rows = []
    for item in candidates:
        metrics = item["metrics"]
        rows.append({key: metrics.get(key, "") for key in columns[:-1]} | {
            "selected": metrics["strategy"] == selected,
        })
    with (output_dir / "time_priority_candidates.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
    for row in rows:
        color = "#c0392b" if row["selected"] else "#2878b5"
        size = 90 if row["selected"] else 45
        axes[0].scatter(row["sortie_count"], row["makespan_s"], c=color, s=size)
        axes[1].scatter(row["weighted_all_expected_tardiness"], row["makespan_s"], c=color, s=size)
    axes[0].set(xlabel="Sorties", ylabel="Completion time (s)", title="Completion time and sorties")
    axes[1].set(xlabel="Weighted tardiness (priority × s)", ylabel="Completion time (s)",
                title="Completion time and delivery timeliness")
    for axis in axes:
        axis.grid(alpha=0.25)
        axis.scatter([], [], c="#c0392b", label="Selected")
        axis.scatter([], [], c="#2878b5", label="Other feasible candidate")
        axis.legend(fontsize=8)
    fig.savefig(output_dir / "time_priority_tradeoff.png", dpi=180)
    plt.close(fig)


def write_bundle(output_dir: Path) -> None:
    paths = [
        "src/problem1/__init__.py", "src/problem1/solver.py",
        "src/problem21/__init__.py", "src/problem21/solver.py",
        "src/problem21/requirements.txt",
        "src/problem23/groups.py",
        "src/problem23/__init__.py",
        "src/problem23/solver.py", "src/problem23/README.md",
        "src/problem23/requirements.txt", "docs/结果提交模板.xlsx",
    ]
    if (ROOT / "src/problem23/cp_sat.py").exists():
        paths.append("src/problem23/cp_sat.py")
    with zipfile.ZipFile(output_dir / "problem2_program.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in paths:
            archive.write(ROOT / relative, relative)


def main() -> None:
    parser = argparse.ArgumentParser(description="Minimize completion time among audited Problem 2 candidates")
    parser.add_argument("--reserve", type=float, default=0.2)
    parser.add_argument("--energy-scale", type=float, default=1.0)
    parser.add_argument("--cp-sat-time-limit", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    args = parser.parse_args()
    if not 0 <= args.reserve < 1 or args.energy_scale <= 0 or args.cp_sat_time_limit <= 0:
        parser.error("reserve must be in [0,1); other parameters must be positive")
    sorties, metrics, boxes, candidates = solve(
        args.reserve, args.energy_scale, args.cp_sat_time_limit,
    )
    try:
        write_outputs(sorties, metrics, boxes, args.output, args.reserve, args.energy_scale)
    except FileNotFoundError as error:
        # The moved problem21 writer still names its old code bundle paths.
        if "src/problem2/" not in str(error):
            raise
        (args.output / "validation.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        (args.output / "model_assumptions.json").write_text(
            json.dumps({"reserve_fraction": args.reserve,
                        "horizontal_energy_scale": args.energy_scale},
                       ensure_ascii=False, indent=2), encoding="utf-8",
        )
    assumptions_path = args.output / "model_assumptions.json"
    assumptions = json.loads(assumptions_path.read_text(encoding="utf-8"))
    assumptions["solver"] = metrics["candidate_scope"]
    assumptions["optimality_status"] = metrics["optimality_status"]
    assumptions["cp_sat_available"] = metrics["cp_sat_available"]
    assumptions_path.write_text(json.dumps(assumptions, ensure_ascii=False, indent=2), encoding="utf-8")
    write_time_comparison(args.output, candidates, metrics["strategy"])
    write_bundle(args.output)
    (args.output / "problem23_summary.json").write_text(json.dumps({
        key: metrics[key] for key in (
            "feasible", "sortie_count", "makespan_s", "total_energy_kwh",
            "weighted_all_expected_tardiness", "strategy", "method",
            "optimality_status", "cp_sat_available", "feasible_candidate_count",
        )
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: metrics[key] for key in (
        "feasible", "sortie_count", "makespan_s", "total_energy_kwh",
        "weighted_all_expected_tardiness", "strategy", "method", "cp_sat_available",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
