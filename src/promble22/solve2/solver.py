"""An auditable second-question solver with exact single-site grouping.

The per-site set partitions are exact for their stated lexicographic objectives.
The subsequent multi-site merges and resource schedules are heuristic, so the
complete second-question result has no global optimality certificate.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import zipfile
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.problem1.solver import ROOT
from src.problem21.solver import (
    RouteEvaluator,
    Sortie,
    TaskBox,
    _merge_multisite,
    _partition_by_site,
    _schedule_candidates,
    load_resources,
    load_task_boxes,
    write_outputs,
)

OUTPUT_DEFAULT = ROOT / "outputs" / "promble2" / "solve2"


def exact_site_partitions(
    boxes: list[TaskBox], evaluator: RouteEvaluator,
) -> dict[str, list[Sortie]]:
    """Find exact one-site partitions for three finite lexicographic policies."""
    by_site: dict[str, list[TaskBox]] = defaultdict(list)
    for box in boxes:
        by_site[box.site].append(box)
    policies = {
        "minimum_sorties": (0, 1, 2),
        "minimum_work_time": (2, 0, 1),
        "minimum_energy": (1, 0, 2),
    }
    results: dict[str, list[Sortie]] = {name: [] for name in policies}
    for site, site_boxes in sorted(by_site.items()):
        count = len(site_boxes)
        full = (1 << count) - 1
        by_first: list[list[tuple[int, Sortie, tuple[float, float, float]]]] = [[] for _ in site_boxes]
        for mask in range(1, full + 1):
            group = [site_boxes[index] for index in range(count) if mask & (1 << index)]
            mass = sum(box.mass_kg for box in group)
            volume = sum(box.volume_m3 for box in group)
            for kind, aircraft in evaluator.aircrafts.items():
                if mass > aircraft.max_payload_kg + 1e-9 or volume > aircraft.volume_m3 + 1e-12:
                    continue
                sortie = evaluator.evaluate(group, [site], kind)
                if sortie is None:
                    continue
                duration = (aircraft.prep_s + aircraft.load_each_s * len(group)
                            + sortie.flight_s + aircraft.handoff_base_s
                            + aircraft.handoff_each_s * len(group))
                values = (1.0, sortie.energy_kwh, duration)
                for index in range(count):
                    if mask & (1 << index):
                        by_first[index].append((mask, sortie, values))

        for name, order in policies.items():
            @lru_cache(maxsize=None)
            def best(remaining: int) -> tuple[tuple[float, float, float], tuple[Sortie, ...]] | None:
                if remaining == 0:
                    return (0.0, 0.0, 0.0), ()
                first = (remaining & -remaining).bit_length() - 1
                incumbent = None
                for mask, sortie, values in by_first[first]:
                    if mask & remaining != mask:
                        continue
                    tail = best(remaining ^ mask)
                    if tail is None:
                        continue
                    score = tuple(values[index] + tail[0][index] for index in range(3))
                    key = tuple(score[index] for index in order)
                    if incumbent is None or key < incumbent[0]:
                        incumbent = key, score, (sortie, *tail[1])
                return None if incumbent is None else (incumbent[1], incumbent[2])

            optimum = best(full)
            if optimum is None:
                raise ValueError(f"No feasible single-site partition for {site}")
            results[name].extend(copy.deepcopy(sortie) for sortie in optimum[1])
    return results


def _signature(sorties: list[Sortie]) -> tuple:
    return tuple(sorted((tuple(sorted(box.code for box in sortie.boxes)),
                         tuple(sortie.route), sortie.aircraft) for sortie in sorties))


def _dominates(left: dict, right: dict) -> bool:
    fields = ("weighted_all_expected_tardiness", "makespan_s", "total_energy_kwh", "sortie_count")
    return (all(left[field] <= right[field] + 1e-7 for field in fields)
            and any(left[field] < right[field] - 1e-7 for field in fields))


def solve(reserve: float = 0.2, energy_scale: float = 1.0) -> tuple[list[Sortie], dict, list[TaskBox], list[dict]]:
    boxes = load_task_boxes()
    drones, batteries = load_resources()
    evaluator = RouteEvaluator(reserve, energy_scale)
    try:
        groupings = exact_site_partitions(boxes, evaluator)
        groupings["constructive"] = _partition_by_site(boxes, evaluator)
        original = list(groupings.items())
        for name, routes in original:
            groupings[name + "_merged"] = _merge_multisite(routes, evaluator)

        candidate_groups = {}
        for name, routes in groupings.items():
            candidate_groups.setdefault(_signature(routes), {"routes": routes, "labels": []})["labels"].append(name)

        schedules = []
        failed = []
        for group in candidate_groups.values():
            for profile in ("balanced", "energy"):
                schedule, metrics = _schedule_candidates(group["routes"], drones, batteries, evaluator, profile)
                label = " | ".join(group["labels"]) + "/" + profile
                if schedule is None:
                    failed.append({"strategy": label, "reason": metrics.get("reason", "infeasible")})
                    continue
                metrics = dict(metrics)
                metrics["strategy"] = label
                schedules.append({"sorties": schedule, "metrics": metrics})
        if not schedules:
            raise ValueError("No feasible schedule among generated grouping and dispatch candidates")
        for candidate in schedules:
            candidate["metrics"]["nondominated_among_candidates"] = not any(
                _dominates(other["metrics"], candidate["metrics"])
                for other in schedules if other is not candidate
            )
        primary = min(schedules, key=lambda item: (
            item["metrics"]["weighted_all_expected_tardiness"],
            item["metrics"]["makespan_s"],
            item["metrics"]["total_energy_kwh"],
            item["metrics"]["sortie_count"],
        ))
        metrics = dict(primary["metrics"])
        metrics.update({
            "objective_profile": "weighted lateness, makespan, energy, sorties",
            "primary_candidate": [primary["metrics"]["strategy"]],
            "candidate_scope": "exact single-site partitions for three lexicographic policies; greedy two-site merges; four dispatch orders and two local assignment profiles",
            "optimality_status": "feasible heuristic for complete Problem 2; global optimum unproven",
            "single_site_partition_status": "exact within each site's complete feasible subset enumeration",
            "generated_grouping_count": len(groupings),
            "unique_grouping_count": len(candidate_groups),
            "feasible_schedule_count": len(schedules),
            "failed_candidates": failed,
            "tradeoff_candidates": {item["metrics"]["strategy"]: item["metrics"] for item in schedules},
        })
        return primary["sorties"], metrics, boxes, schedules
    finally:
        evaluator.close()


def _write_comparison(output_dir: Path, schedules: list[dict], selected: str) -> None:
    fields = ["strategy", "sortie_count", "total_energy_kwh", "makespan_s",
              "weighted_all_expected_tardiness", "all_expected_on_time_count",
              "nondominated_among_candidates", "selected"]
    rows = []
    for candidate in schedules:
        metrics = candidate["metrics"]
        rows.append({field: metrics.get(field, "") for field in fields[:-1]} | {
            "selected": metrics["strategy"] == selected,
        })
    with (output_dir / "candidate_comparison.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
    for row in rows:
        color = "#c0392b" if row["selected"] else ("#2878b5" if row["nondominated_among_candidates"] else "#aaaaaa")
        axes[0].scatter(row["sortie_count"], row["weighted_all_expected_tardiness"],
                        s=80 if row["selected"] else 45, color=color, alpha=0.8)
        axes[1].scatter(row["total_energy_kwh"], row["makespan_s"],
                        s=80 if row["selected"] else 45, color=color, alpha=0.8)
    axes[0].set(xlabel="Sorties", ylabel="Weighted tardiness (priority × s)",
                title="Timeliness versus sortie count")
    axes[1].set(xlabel="Total energy (kWh)", ylabel="Completion time (s)",
                title="Energy versus completion time")
    from matplotlib.lines import Line2D
    legend = [
        Line2D([], [], marker="o", linestyle="None", color="#c0392b", label="Selected"),
        Line2D([], [], marker="o", linestyle="None", color="#2878b5", label="Nondominated among candidates"),
        Line2D([], [], marker="o", linestyle="None", color="#aaaaaa", label="Dominated candidate"),
    ]
    for ax in axes:
        ax.grid(alpha=0.25)
        ax.legend(handles=legend, loc="best", fontsize=8)
    fig.savefig(output_dir / "candidate_tradeoff.png", dpi=180)
    plt.close(fig)


def _write_bundle(output_dir: Path) -> None:
    paths = [
        "src/problem1/__init__.py", "src/problem1/solver.py",
        "src/problem2/__init__.py", "src/problem2/solver.py",
        "src/promble2/__init__.py", "src/promble2/solve2/__init__.py",
        "src/promble2/solve2/solver.py", "src/promble2/solve2/README.md",
        "src/problem2/requirements.txt", "docs/结果提交模板.xlsx",
    ]
    with zipfile.ZipFile(output_dir / "problem2_program.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in paths:
            archive.write(ROOT / relative, relative)


def main() -> None:
    parser = argparse.ArgumentParser(description="Solve Problem 2 with exact single-site partitions and audited scheduling")
    parser.add_argument("--reserve", type=float, default=0.2)
    parser.add_argument("--energy-scale", type=float, default=1.0)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    args = parser.parse_args()
    if not 0 <= args.reserve < 1 or args.energy_scale <= 0:
        parser.error("reserve must be in [0,1), energy-scale must be positive")
    sorties, metrics, boxes, schedules = solve(args.reserve, args.energy_scale)
    write_outputs(sorties, metrics, boxes, args.output, args.reserve, args.energy_scale)
    assumptions_path = args.output / "model_assumptions.json"
    assumptions = json.loads(assumptions_path.read_text(encoding="utf-8"))
    assumptions["solver"] = metrics["candidate_scope"]
    assumptions["optimality_status"] = metrics["optimality_status"]
    assumptions["single_site_partition_status"] = metrics["single_site_partition_status"]
    assumptions_path.write_text(json.dumps(assumptions, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_comparison(args.output, schedules, metrics["strategy"])
    _write_bundle(args.output)
    (args.output / "solve2_summary.json").write_text(json.dumps({
        key: metrics[key] for key in (
            "feasible", "sortie_count", "total_energy_kwh", "makespan_s",
            "weighted_all_expected_tardiness", "strategy", "optimality_status",
            "single_site_partition_status", "generated_grouping_count",
            "unique_grouping_count", "feasible_schedule_count",
        )
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: metrics[key] for key in (
        "feasible", "sortie_count", "total_energy_kwh", "makespan_s",
        "weighted_all_expected_tardiness", "strategy", "optimality_status",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
