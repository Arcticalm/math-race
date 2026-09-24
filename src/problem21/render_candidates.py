"""Render per-candidate figures for Problem 2.

Re-runs the deterministic candidate construction from ``solver.solve``, keeps the
*unique* schedules (two strategy labels can collapse onto one identical schedule),
and emits a separate routes / resource-gantt / delivery-times figure per candidate
under ``outputs/problem2/``. The existing primary-candidate figures are untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.problem21.solver import (
    OUTPUT_DEFAULT,
    Sortie,
    TaskBox,
    _merge_multisite,
    _partition_by_site,
    _schedule_candidates,
    _schedule_signature,
    load_aircraft,
    load_nodes,
    load_resources,
    load_task_boxes,
    RouteEvaluator,
)


_EN_LABEL = {
    "不跨区/balanced": "Single-site · balanced",
    "不跨区/energy": "Single-site · energy",
    "多点合并/balanced": "Multi-site merge · balanced",
    "多点合并/energy": "Multi-site merge · energy",
}


def _slug(labels: list[str]) -> str:
    # ASCII-safe, deterministic filenames. Both multi-site labels collapse onto
    # one identical schedule, so collapse them to a single readable slug.
    if len(labels) == 1:
        grouping, profile = labels[0].split("/")
        prefix = "single-site" if grouping == "不跨区" else "multisite"
        return f"{prefix}_{profile}"
    return "multisite_balanced_energy"


def _title(labels: list[str]) -> str:
    return "  /  ".join(_EN_LABEL[label] for label in labels)


def _plot_routes(sorties: list[Sortie], output_path: Path, label: str) -> None:
    base, sites = load_nodes()
    figure, axis = plt.subplots(figsize=(9, 7), layout="constrained")
    aircraft_colors = {"A": "#2878b5", "B": "#e07a24", "C": "#37966f"}
    for sortie in sorties:
        nodes = [base, *(sites[site] for site in sortie.route), base]
        color = aircraft_colors[sortie.aircraft]
        axis.plot([node.longitude for node in nodes], [node.latitude for node in nodes],
                  color=color, linewidth=1.0, alpha=0.42, marker="o", markersize=2.0)
    axis.scatter([base.longitude], [base.latitude], marker="*", s=180, color="#d1495b", label="O01")
    axis.scatter([node.longitude for node in sites.values()], [node.latitude for node in sites.values()],
                 marker="s", s=18, color="#2364aa", label="Service area")
    for aircraft_code, color in aircraft_colors.items():
        axis.plot([], [], color=color, linewidth=2, label=f"Aircraft type {aircraft_code}")
    axis.set_xlabel("Longitude (deg)")
    axis.set_ylabel("Latitude (deg)")
    axis.set_title(f"Problem 2 transport routes — {label}")
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def _plot_resource_gantt(sorties: list[Sortie], output_path: Path, label: str) -> None:
    drones, batteries = load_resources()
    aircraft_ids = sorted(item.code for item in drones)
    battery_ids = sorted(item.code for item in batteries)
    figure, axes = plt.subplots(2, 1, figsize=(12, max(6, 0.3 * (len(aircraft_ids) + len(battery_ids)))),
                                sharex=True, layout="constrained")
    color_map = plt.get_cmap("tab20")
    for axis, resource_ids, kind in ((axes[0], aircraft_ids, "aircraft"), (axes[1], battery_ids, "battery")):
        for row_index, resource_id in enumerate(resource_ids):
            assigned = [item for item in sorties if (item.drone if kind == "aircraft" else item.battery) == resource_id]
            for item in assigned:
                color = color_map(int(item.code[-3:]) % 20)
                axis.broken_barh([(item.prep_start_s, item.return_s - item.prep_start_s)],
                                 (row_index - 0.35, 0.7), facecolors=color, edgecolors="black", linewidth=0.3)
                if kind == "battery":
                    battery = next(value for value in batteries if value.code == item.battery)
                    soc = 1 - item.energy_kwh / load_aircraft()[item.aircraft].usable_energy_kwh
                    charge_end = item.return_s + _charge_duration(battery.full_charge_s, soc)
                    axis.broken_barh([(item.return_s, charge_end - item.return_s)],
                                     (row_index - 0.35, 0.7), facecolors="#a8dadc", edgecolors="#457b9d", linewidth=0.3)
                axis.text((item.prep_start_s + item.return_s) / 2, row_index,
                          item.code, ha="center", va="center", fontsize=6)
        axis.set_yticks(range(len(resource_ids)), resource_ids)
        axis.set_ylabel("Aircraft" if kind == "aircraft" else "Battery")
        axis.grid(axis="x", alpha=0.25)
    axes[0].set_title(f"Resource schedule — {label}")
    axes[1].set_xlabel("Time (s)")
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def _plot_delivery_times(sorties: list[Sortie], boxes: list[TaskBox], output_path: Path, label: str) -> None:
    delivery = {box.code: time for sortie in sorties for box in sortie.boxes
                for time in [(sortie.deliveries or {}).get(box.code, 0)]}
    eligible = [box for box in boxes if box.due_s is not None]
    sites = sorted({box.site for box in eligible})
    figure, axis = plt.subplots(figsize=(11, 6), layout="constrained")
    palette = {site: plt.get_cmap("tab20")(index % 20) for index, site in enumerate(sites)}
    for index, box in enumerate(eligible):
        actual = delivery[box.code]
        axis.scatter(box.due_s, index, marker="|", s=55, color="#d1495b")
        axis.scatter(actual, index, s=16, color=palette[box.site])
        axis.plot([box.due_s, actual], [index, index], color=palette[box.site], alpha=0.45, linewidth=0.7)
    axis.set_yticks(range(len(eligible)), [box.code for box in eligible], fontsize=6)
    axis.set_xlabel("Delivery time (s); red tick = expected time")
    axis.set_title(f"Actual and expected delivery times — {label}")
    axis.grid(axis="x", alpha=0.25)
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def _charge_duration(full_charge_s: float, soc: float) -> float:
    if soc < 0.9:
        return full_charge_s * (0.65 * (0.9 - soc) / 0.9 + 0.35)
    return full_charge_s * 0.35 * (1 - soc) / 0.1


def main() -> None:
    output_dir = OUTPUT_DEFAULT
    boxes = load_task_boxes()
    drones, batteries = load_resources()
    evaluator = RouteEvaluator(0.2, 1.0)
    try:
        initial = _partition_by_site(boxes, evaluator)
        merged = _merge_multisite(initial, evaluator)
        grouping_options = (("不跨区", initial), ("多点合并", merged))
        unique: dict[tuple, dict] = {}
        for grouping, routes in grouping_options:
            for profile in ("balanced", "energy"):
                schedule, metrics = _schedule_candidates(routes, drones, batteries, evaluator, profile)
                if schedule is None:
                    continue
                signature = _schedule_signature(schedule)
                candidate = unique.setdefault(signature, {"sorties": schedule, "metrics": metrics, "labels": []})
                label = f"{grouping}/{profile}"
                if label not in candidate["labels"]:
                    candidate["labels"].append(label)

        summary = []
        for index, candidate in enumerate(unique.values(), 1):
            labels = candidate["labels"]
            sorties = candidate["sorties"]
            slug = _slug(labels)
            _plot_routes(sorties, output_dir / f"routes__{slug}.png", _title(labels))
            _plot_resource_gantt(sorties, output_dir / f"resource_gantt__{slug}.png", _title(labels))
            _plot_delivery_times(sorties, boxes, output_dir / f"delivery_times__{slug}.png", _title(labels))
            summary.append({
                "candidate": " | ".join(labels),
                "slug": slug,
                "sorties": len(sorties),
                "makespan_s": candidate["metrics"]["makespan_s"],
                "total_energy_kwh": candidate["metrics"]["total_energy_kwh"],
                "on_time_rate": candidate["metrics"]["all_expected_on_time_rate"],
            })
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        evaluator.close()


if __name__ == "__main__":
    main()
