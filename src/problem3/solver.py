from __future__ import annotations

import argparse
import copy
import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import rasterio

from src.problem1.solver import Node, load_aircraft, sample_leg
from src.problem21.solver import (
    RouteEvaluator,
    _hard_deadlines,
    _charge_duration as transport_charge_duration,
    load_resources,
    solve as solve_problem2,
)
from src.problem3.physics import (
    LinkEvaluator,
    estimate_relay_mission,
    link_limits,
    load_link_parameters,
    load_relay_parameters,
)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DEFAULT = ROOT / "outputs" / "problem3"


@dataclass(frozen=True)
class TrackPhase:
    sortie: str
    name: str
    start_s: float
    end_s: float
    start_node: Node
    end_node: Node
    start_altitude_m: float
    end_altitude_m: float


def _node_at(first: Node, second: Node, fraction: float, code: str) -> Node:
    return Node(code, first.longitude + fraction * (second.longitude - first.longitude),
                first.latitude + fraction * (second.latitude - first.latitude), 0.0)


def build_trajectory(sorties, reserve: float = 0.2, energy_scale: float = 1.0) -> list[TrackPhase]:
    aircrafts = load_aircraft()
    base_evaluator = RouteEvaluator(reserve, energy_scale)
    try:
        base, sites = base_evaluator.base, base_evaluator.sites
        phases = []
        for sortie in sorties:
            aircraft = aircrafts[sortie.aircraft]
            current_node = base
            current_altitude = base.elevation_m
            current_time = sortie.takeoff_s
            for sequence, leg in enumerate(sortie.legs or [], 1):
                destination = base if leg["to"] == "O01" else sites[leg["to"]]
                destination_altitude = destination.elevation_m + (30 if destination.code != "O01" else 0)
                cruise_altitude = leg["cruise_altitude_m"]
                distance = leg["distance_m"]
                climb_s = max(0.0, cruise_altitude - current_altitude) / aircraft.climb_speed_mps
                cruise_s = distance / aircraft.cruise_speed_mps
                descent_s = max(0.0, cruise_altitude - destination_altitude) / aircraft.descent_speed_mps
                phases.append(TrackPhase(sortie.code, f"leg{sequence}-climb", current_time,
                    current_time + climb_s, current_node, current_node, current_altitude, cruise_altitude))
                current_time += climb_s
                phases.append(TrackPhase(sortie.code, f"leg{sequence}-cruise", current_time,
                    current_time + cruise_s, current_node, destination, cruise_altitude, cruise_altitude))
                current_time += cruise_s
                phases.append(TrackPhase(sortie.code, f"leg{sequence}-descent", current_time,
                    current_time + descent_s, destination, destination, cruise_altitude, destination_altitude))
                current_time += descent_s
                current_node, current_altitude = destination, destination_altitude
                if destination.code != "O01":
                    count = sum(box.site == destination.code for box in sortie.boxes)
                    handoff = aircraft.handoff_base_s + aircraft.handoff_each_s * count
                    phases.append(TrackPhase(sortie.code, f"{destination.code}-handoff", current_time,
                        current_time + handoff, destination, destination, destination_altitude, destination_altitude))
                    current_time += handoff
            if abs(current_time - sortie.return_s) > 1e-6:
                raise ValueError(f"Trajectory timeline mismatch for {sortie.code}: {current_time} != {sortie.return_s}")
        return phases
    finally:
        base_evaluator.close()


def _position(phase: TrackPhase, time_s: float) -> tuple[Node, float]:
    duration = phase.end_s - phase.start_s
    fraction = 0.0 if duration <= 0 else min(1.0, max(0.0, (time_s - phase.start_s) / duration))
    node = _node_at(phase.start_node, phase.end_node, fraction, phase.name)
    altitude = phase.start_altitude_m + fraction * (phase.end_altitude_m - phase.start_altitude_m)
    return node, altitude


def screen_direct_links(sorties, phases: list[TrackPhase], step_s: float = 10.0) -> tuple[list[dict], list[dict]]:
    params = load_link_parameters()
    evaluator = LinkEvaluator(params)
    base, _ = evaluator.base, evaluator.sites
    gateway = Node("G01", base.longitude, base.latitude, base.elevation_m + 20)
    threshold = link_limits(params)["transport_gateway_db"]
    samples = []
    try:
        for phase in phases:
            if phase.end_s <= phase.start_s:
                continue
            sample_count = max(1, math.ceil((phase.end_s - phase.start_s) / step_s))
            for index in range(sample_count + 1):
                time_s = phase.start_s + (phase.end_s - phase.start_s) * index / sample_count
                if index == sample_count and phase.end_s == phase.start_s:
                    continue
                position, altitude = _position(phase, time_s)
                link = evaluator.evaluate(position, altitude, gateway, gateway.elevation_m, threshold)
                samples.append({
                    "sortie": phase.sortie, "phase": phase.name, "time_s": time_s,
                    "longitude": position.longitude, "latitude": position.latitude,
                    "altitude_m": altitude, **asdict(link),
                })
    finally:
        evaluator.close()
    samples.sort(key=lambda item: (item["sortie"], item["time_s"], item["phase"]))
    intervals = []
    for sortie in sorties:
        selected = [item for item in samples if item["sortie"] == sortie.code]
        if not selected:
            continue
        start = previous = selected[0]
        for current in selected[1:]:
            if current["available"] != previous["available"] or current["reason"] != previous["reason"]:
                intervals.append({
                    "sortie": sortie.code, "start_s": start["time_s"], "end_s": previous["time_s"],
                    "direct_available": previous["available"], "reason": previous["reason"],
                })
                start = current
            previous = current
        intervals.append({
            "sortie": sortie.code, "start_s": start["time_s"], "end_s": previous["time_s"],
            "direct_available": previous["available"], "reason": previous["reason"],
        })
    intervals.sort(key=lambda item: (item["start_s"], item["sortie"]))
    return samples, intervals


def _peak_gap_load(intervals: list[dict]) -> tuple[int, float]:
    events = []
    for item in intervals:
        if item["direct_available"] or item["end_s"] <= item["start_s"]:
            continue
        events.append((item["start_s"], 1))
        events.append((item["end_s"], -1))
    events.sort(key=lambda item: (item[0], item[1]))
    active = peak = 0
    previous = None
    squared_load = 0.0
    for time_s, change in events:
        if previous is not None and time_s > previous:
            squared_load += (time_s - previous) * active * active
        active += change
        peak = max(peak, active)
        previous = time_s
    return peak, squared_load


def _transport_schedule_resource_feasible(sorties, batteries) -> bool:
    by_drone: dict[str, list[tuple[float, float]]] = {}
    by_battery: dict[str, list[tuple[float, float]]] = {}
    battery_by_id = {item.code: item for item in batteries}
    aircrafts = load_aircraft()
    for sortie in sorties:
        by_drone.setdefault(sortie.drone, []).append((sortie.prep_start_s, sortie.return_s))
        battery = battery_by_id[sortie.battery]
        soc = 1 - sortie.energy_kwh / aircrafts[sortie.aircraft].usable_energy_kwh
        available = sortie.return_s + transport_charge_duration(battery.full_charge_s, soc)
        by_battery.setdefault(sortie.battery, []).append((sortie.prep_start_s, available))
    for intervals in (*by_drone.values(), *by_battery.values()):
        intervals.sort()
        if any(previous[1] > current[0] + 1e-7 for previous, current in zip(intervals, intervals[1:])):
            return False
    return True


def _changed_sortie_resource_feasible(sortie, schedule, batteries) -> bool:
    battery_by_id = {item.code: item for item in batteries}
    aircrafts = load_aircraft()
    peers = [item for item in schedule if item.code != sortie.code]
    same_drone = sorted((item for item in peers if item.drone == sortie.drone),
                        key=lambda item: item.prep_start_s)
    if any(item.prep_start_s < sortie.return_s - 1e-7
           and item.return_s > sortie.prep_start_s + 1e-7 for item in same_drone):
        return False
    battery = battery_by_id[sortie.battery]
    soc = 1 - sortie.energy_kwh / aircrafts[sortie.aircraft].usable_energy_kwh
    available = sortie.return_s + transport_charge_duration(battery.full_charge_s, soc)
    same_battery = [item for item in peers if item.battery == sortie.battery]
    for item in same_battery:
        item_battery = battery_by_id[item.battery]
        item_soc = 1 - item.energy_kwh / aircrafts[item.aircraft].usable_energy_kwh
        item_available = item.return_s + transport_charge_duration(item_battery.full_charge_s, item_soc)
        if item.prep_start_s < available - 1e-7 and item_available > sortie.prep_start_s + 1e-7:
            return False
    return True


def _weighted_expected_lateness(sorties, boxes) -> float:
    delivered = {code: time_s for sortie in sorties for code, time_s in (sortie.deliveries or {}).items()}
    return sum(box.priority * max(0.0, delivered.get(box.code, 0.0) - box.due_s)
               for box in boxes if box.due_s is not None)


def _shift_sortie(sortie, delay_s: float) -> None:
    sortie.prep_start_s += delay_s
    sortie.prep_end_s += delay_s
    sortie.loading_end_s += delay_s
    sortie.takeoff_s += delay_s
    sortie.return_s += delay_s
    sortie.deliveries = {code: time_s + delay_s for code, time_s in (sortie.deliveries or {}).items()}


def coordinate_transport_starts(sorties, boxes, intervals: list[dict], batteries,
                                step_s: float = 60.0, maximum_delay_s: float = 1800.0) -> tuple[list, dict]:
    schedule = copy.deepcopy(sorties)
    gaps_by_sortie: dict[str, list[dict]] = {}
    for interval in intervals:
        if not interval["direct_available"] and interval["end_s"] > interval["start_s"]:
            gaps_by_sortie.setdefault(interval["sortie"], []).append(dict(interval))
    max_delay = {}
    for sortie in schedule:
        slack = min((deadline_s - sortie.deliveries[box.code]
                     for box in sortie.boxes for _, deadline_s in _hard_deadlines(box)),
                    default=maximum_delay_s)
        if not math.isfinite(slack):
            slack = maximum_delay_s
        max_delay[sortie.code] = max(0.0, min(maximum_delay_s, slack))

    delays = {sortie.code: 0.0 for sortie in schedule}
    current_gaps = [item for values in gaps_by_sortie.values() for item in values]
    current_peak, current_load = _peak_gap_load(current_gaps)
    current_lateness = _weighted_expected_lateness(schedule, boxes)
    for _ in range(3):
        improved = False
        ordered = sorted(schedule, key=lambda sortie: (
            -sum(item["end_s"] - item["start_s"] for item in gaps_by_sortie.get(sortie.code, [])),
            sortie.prep_start_s,
        ))
        for sortie in ordered:
            original_delay = delays[sortie.code]
            best = (current_peak, current_load, current_lateness, sum(delays.values()), original_delay)
            best_delay = original_delay
            delay_values = [original_delay]
            delay_values.extend(value for value in range(0, int(max_delay[sortie.code]) + 1, int(step_s)))
            if max_delay[sortie.code] > 0:
                delay_values.append(max_delay[sortie.code])
            for candidate_delay in sorted(set(delay_values)):
                offset = candidate_delay - original_delay
                if abs(offset) < 1e-7:
                    continue
                candidate_schedule = copy.deepcopy(schedule)
                candidate_sortie = next(item for item in candidate_schedule if item.code == sortie.code)
                _shift_sortie(candidate_sortie, offset)
                if not _changed_sortie_resource_feasible(candidate_sortie, candidate_schedule, batteries):
                    continue
                candidate_gaps = []
                for code, values in gaps_by_sortie.items():
                    shift = candidate_delay if code == sortie.code else delays[code]
                    candidate_gaps.extend({**item, "start_s": item["start_s"] + shift,
                                           "end_s": item["end_s"] + shift} for item in values)
                peak, load = _peak_gap_load(candidate_gaps)
                lateness = _weighted_expected_lateness(candidate_schedule, boxes)
                score = (peak, load, lateness, sum(delays.values()) + offset, candidate_delay)
                if score < best:
                    best, best_delay = score, candidate_delay
            if best_delay != original_delay:
                offset = best_delay - original_delay
                _shift_sortie(sortie, offset)
                delays[sortie.code] = best_delay
                current_gaps = [
                    {**item, "start_s": item["start_s"] + delays[code],
                     "end_s": item["end_s"] + delays[code]}
                    for code, values in gaps_by_sortie.items() for item in values
                ]
                current_peak, current_load = _peak_gap_load(current_gaps)
                current_lateness = _weighted_expected_lateness(schedule, boxes)
                improved = True
        if not improved:
            break
    return schedule, {
        "method": "three-pass coordinate search over delayed sortie starts",
        "maximum_delay_s": maximum_delay_s,
        "step_s": step_s,
        "delays_s": {code: delay for code, delay in delays.items() if delay > 0},
        "peak_simultaneous_direct_gaps": current_peak,
        "integrated_squared_gap_load_s": current_load,
        "weighted_expected_lateness_s": current_lateness,
        "resource_schedule_feasible": _transport_schedule_resource_feasible(schedule, batteries),
    }


def search_relay_candidates(sorties, phases: list[TrackPhase], gaps: list[dict],
                            sample_step_s: float = 30.0) -> list[dict]:
    params = load_link_parameters()
    relay = load_relay_parameters()
    evaluator = LinkEvaluator(params)
    base = evaluator.base
    gateway = Node("G01", base.longitude, base.latitude, base.elevation_m + 20)
    limits = link_limits(params)
    time_step_s = min(30.0, sample_step_s)
    offsets = (-0.01, 0.0, 0.01)
    results = []
    phases_by_sortie: dict[str, list[TrackPhase]] = {}
    sorties_by_code = {sortie.code: sortie for sortie in sorties}
    for phase in phases:
        phases_by_sortie.setdefault(phase.sortie, []).append(phase)
    try:
        gap_groups = []
        for gap_id, gap in enumerate(sorted(gaps, key=lambda item: (item["start_s"], item["sortie"])), 1):
            gap["gap_id"] = gap_id
            if not gap_groups or gap["start_s"] > max(item["end_s"] for item in gap_groups[-1]) + 1e-7:
                gap_groups.append([gap])
            else:
                gap_groups[-1].append(gap)

        for group_index, group in enumerate(gap_groups, 1):
            demand_by_gap = {}
            target_nodes = []
            for gap in group:
                sortie_phases = phases_by_sortie[gap["sortie"]]
                demand_by_gap[gap["sortie"]] = []
                sample_count = max(1, math.ceil((gap["end_s"] - gap["start_s"]) / time_step_s))
                for sample_index in range(sample_count + 1):
                    time_s = gap["start_s"] + (gap["end_s"] - gap["start_s"]) * sample_index / sample_count
                    phase = next((item for item in sortie_phases
                                  if item.start_s - 1e-7 <= time_s <= item.end_s + 1e-7), None)
                    if phase is None:
                        continue
                    transport_node, transport_altitude = _position(phase, time_s)
                    demand_by_gap[gap["sortie"]].append((time_s, transport_node, transport_altitude))
                for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
                    time_s = gap["start_s"] + (gap["end_s"] - gap["start_s"]) * fraction
                    phase = next(item for item in sortie_phases
                                 if item.start_s - 1e-7 <= time_s <= item.end_s + 1e-7)
                    target_nodes.append(_position(phase, time_s)[0])
            locations = {(round(node.longitude + lon_offset, 7), round(node.latitude + lat_offset, 7))
                         for node in target_nodes for lon_offset in offsets for lat_offset in offsets}
            candidate_rows = []
            for longitude, latitude in locations:
                row, col = rasterio.transform.rowcol(evaluator.dem.transform, longitude, latitude)
                if not (0 <= row < evaluator.dem.height and 0 <= col < evaluator.dem.width):
                    continue
                ground_m = float(evaluator.dem_values[row, col])
                if not math.isfinite(ground_m) or math.isclose(ground_m, -32767.0):
                    continue
                for agl_m in (50.0, 150.0, 250.0, relay.maximum_agl_m):
                    if agl_m > relay.maximum_agl_m:
                        continue
                    hover = Node("H", longitude, latitude, ground_m)
                    hover_altitude = ground_m + agl_m
                    backhaul = evaluator.evaluate(hover, hover_altitude, gateway,
                                                   gateway.elevation_m, limits["relay_gateway_db"])
                    if not backhaul.available:
                        continue
                    outbound_max_ground, outbound_distance = sample_leg(evaluator.dem, base, hover)
                    return_max_ground, return_distance = sample_leg(evaluator.dem, hover, base)
                    covered = []
                    for gap in group:
                        access_ok = all(
                            evaluator.evaluate(transport_node, transport_altitude, hover,
                                               hover_altitude, limits["transport_relay_db"]).available
                            for _, transport_node, transport_altitude in demand_by_gap[gap["sortie"]]
                        )
                        if access_ok:
                            covered.append(gap)
                    if not covered:
                        continue
                    for service_start in sorted({item["start_s"] for item in covered}):
                        service_subset = [item for item in covered if item["start_s"] >= service_start - 1e-7]
                        if not service_subset:
                            continue
                        service_end = max(item["end_s"] for item in service_subset)
                        service_s = service_end - service_start
                        mission = estimate_relay_mission(
                            service_s, outbound_distance, outbound_max_ground, hover_altitude,
                            return_distance, return_max_ground, base.elevation_m, relay,
                        )
                        prepare_start = service_start - relay.preparation_s - mission.outbound_flight_s - relay.link_setup_s
                        if prepare_start < -1e-7 or not mission.feasible_energy:
                            continue
                        subset_ids = [item["gap_id"] for item in service_subset]
                        candidate_rows.append({
                            "covered_gap_ids": subset_ids,
                            "covered_sorties": ",".join(sorted(item["sortie"] for item in service_subset)),
                            "service_start_s": service_start, "service_end_s": service_end,
                            "preparation_start_s": max(0.0, prepare_start),
                            "longitude": longitude, "latitude": latitude,
                            "ground_dsm_m": ground_m, "hover_altitude_m": hover_altitude,
                            "agl_m": agl_m, "energy_kwh": mission.energy_kwh,
                            "return_soc_percent": mission.return_soc_percent,
                            "return_o01_s": service_end + mission.return_flight_s,
                            "outbound_flight_s": mission.outbound_flight_s,
                            "return_flight_s": mission.return_flight_s,
                        })
            best_by_coverage = {}
            for candidate in candidate_rows:
                coverage_key = tuple(candidate["covered_gap_ids"])
                current = best_by_coverage.get(coverage_key)
                if current is None or (candidate["energy_kwh"], candidate["return_o01_s"]) < (
                    current["energy_kwh"], current["return_o01_s"]
                ):
                    best_by_coverage[coverage_key] = candidate
            candidate_rows = sorted(best_by_coverage.values(), key=lambda item: (
                -len(item["covered_gap_ids"]), item["energy_kwh"], item["return_o01_s"],
            ))
            results.append({
                "group": group_index, "covered_sorties": ",".join(sorted({item["sortie"] for item in group})),
                "gap_count": len(group), "gap_start_s": min(item["start_s"] for item in group),
                "gap_end_s": max(item["end_s"] for item in group),
                "gap_start_by_id": {str(item["gap_id"]): item["start_s"] for item in group},
                "gaps": [{"gap_id": item["gap_id"], "sortie": item["sortie"],
                          "start_s": item["start_s"], "end_s": item["end_s"]} for item in group],
                "candidate_count": len(candidate_rows), "candidates": candidate_rows,
            })
    finally:
        evaluator.close()
    return results


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _node_elevation_audit(evaluator: LinkEvaluator) -> list[dict]:
    nodes = [evaluator.base, *evaluator.sites.values()]
    audit = []
    for node in nodes:
        row, col = rasterio.transform.rowcol(evaluator.dem.transform, node.longitude, node.latitude)
        valid = 0 <= row < evaluator.dem.height and 0 <= col < evaluator.dem.width
        dsm = float(evaluator.dem_values[row, col]) if valid else math.nan
        valid = valid and math.isfinite(dsm) and not math.isclose(dsm, -32767.0)
        audit.append({
            "node": node.code, "node_table_ground_m": node.elevation_m,
            "dsm_pixel_m": dsm if valid else "", "dsm_minus_node_m": dsm - node.elevation_m if valid else "",
            "valid": valid,
        })
    return audit


def _charge_duration(full_charge_s: float, soc: float) -> float:
    if soc < 0.9:
        return full_charge_s * (0.65 * (0.9 - soc) / 0.9 + 0.35)
    return full_charge_s * 0.35 * (1 - soc) / 0.1


def select_relay_schedule(candidate_groups: list[dict], gap_count: int, search_limit: int = 50000) -> dict:
    relay = load_relay_parameters()
    candidates = []
    for group in candidate_groups:
        for original in group["candidates"]:
            candidate = dict(original)
            candidate["candidate_group"] = group["group"]
            candidates.append(candidate)
    for candidate in candidates:
        if isinstance(candidate["covered_gap_ids"], str):
            candidate["covered_gap_ids"] = json.loads(candidate["covered_gap_ids"])
        for key in ("longitude", "latitude", "hover_altitude_m", "service_start_s", "service_end_s",
                    "preparation_start_s", "return_o01_s", "return_soc_percent", "energy_kwh"):
            candidate[key] = float(candidate[key])
    unique = {}
    for candidate in candidates:
        key = (tuple(candidate["covered_gap_ids"]), round(candidate["longitude"], 7),
               round(candidate["latitude"], 7), round(candidate["hover_altitude_m"], 2),
               round(candidate["service_start_s"], 3), round(candidate["service_end_s"], 3))
        unique.setdefault(key, candidate)
    candidates = list(unique.values())
    uncovered = set(range(1, gap_count + 1))
    gap_start = {int(gap_id): float(start_s) for group in candidate_groups
                 for gap_id, start_s in group["gap_start_by_id"].items()}
    gap_candidates = {gap_id: [] for gap_id in uncovered}
    for candidate in candidates:
        for gap_id in candidate["covered_gap_ids"]:
            if gap_id in gap_candidates:
                gap_candidates[gap_id].append(candidate)
    drone_codes = ("R01", "R02")
    battery_codes = tuple(f"RE-{index:02d}" for index in range(1, relay.battery_count + 1))
    selected = []
    nodes = 0
    stopped_at_limit = False

    def conflicts(candidate, drone_code, battery_code) -> bool:
        start = candidate["preparation_start_s"]
        drone_end = candidate["return_o01_s"] + relay.turnaround_s
        battery_soc = candidate["return_soc_percent"] / 100
        battery_end = candidate["return_o01_s"] + _charge_duration(relay.full_charge_s, battery_soc)
        for previous in selected:
            previous_start = previous["preparation_start_s"]
            if previous["relay_drone"] == drone_code:
                previous_end = previous["return_o01_s"] + relay.turnaround_s
                if start < previous_end - 1e-7 and drone_end > previous_start + 1e-7:
                    return True
            if previous["energy_component"] == battery_code:
                previous_soc = previous["return_soc_percent"] / 100
                previous_end = previous["return_o01_s"] + _charge_duration(relay.full_charge_s, previous_soc)
                if start < previous_end - 1e-7 and battery_end > previous_start + 1e-7:
                    return True
        return False

    def search(remaining: set[int]) -> bool:
        nonlocal nodes, stopped_at_limit
        if not remaining:
            return True
        if nodes >= search_limit:
            stopped_at_limit = True
            return False
        nodes += 1
        earliest_gap = min(remaining, key=lambda gap_id: gap_start.get(gap_id, math.inf))
        options = [candidate for candidate in gap_candidates.get(earliest_gap, ())
                   if set(candidate["covered_gap_ids"]) & remaining]
        options.sort(key=lambda candidate: (
            -len(set(candidate["covered_gap_ids"]) & remaining), candidate["energy_kwh"],
            candidate["return_o01_s"], candidate["preparation_start_s"],
        ))
        for candidate in options:
            newly_covered = set(candidate["covered_gap_ids"]) & remaining
            for drone_code in drone_codes:
                for battery_code in battery_codes:
                    if conflicts(candidate, drone_code, battery_code):
                        continue
                    assigned = dict(candidate)
                    assigned["relay_sortie"] = f"R3-{len(selected) + 1:03d}"
                    assigned["relay_drone"] = drone_code
                    assigned["energy_component"] = battery_code
                    selected.append(assigned)
                    if search(remaining - newly_covered):
                        return True
                    selected.pop()
                    if stopped_at_limit:
                        return False
        return False

    feasible = search(uncovered)
    selected.sort(key=lambda item: (item["preparation_start_s"], item["relay_sortie"]))
    for index, item in enumerate(selected, 1):
        item["relay_sortie"] = f"R3-{index:03d}"
    covered = {gap_id for item in selected for gap_id in item["covered_gap_ids"]}
    uncovered -= covered
    drone_ready = {code: max((item["return_o01_s"] + relay.turnaround_s for item in selected
                              if item["relay_drone"] == code), default=0.0) for code in drone_codes}
    battery_ready = {code: max((item["return_o01_s"] + _charge_duration(
        relay.full_charge_s, item["return_soc_percent"] / 100)
        for item in selected if item["energy_component"] == code), default=0.0) for code in battery_codes}
    return {
        "feasible_cover": feasible and not uncovered,
        "selected_count": len(selected),
        "selected": selected,
        "uncovered_gap_ids": sorted(uncovered),
        "search_nodes": nodes,
        "search_limit": search_limit,
        "search_limit_reached": stopped_at_limit,
        "drone_ready_times": drone_ready,
        "energy_component_ready_times": battery_ready,
        "method": "bounded backtracking over sampled candidates; earliest gap first, then broader coverage and energy, with exact relay-airframe turnaround and battery-recharge interval conflicts",
    }


def run(output_dir: Path = OUTPUT_DEFAULT, sample_step_s: float = 10.0,
        relay_candidate_step_s: float = 30.0) -> dict:
    sorties, transport_metrics, boxes = solve_problem2()
    phases = build_trajectory(sorties)
    samples, intervals = screen_direct_links(sorties, phases, sample_step_s)
    gaps = sorted((item for item in intervals if not item["direct_available"]),
                  key=lambda item: (item["start_s"], item["sortie"]))
    drones, batteries = load_resources()
    coordinated_sorties, coordination = coordinate_transport_starts(
        sorties, boxes, gaps, batteries, step_s=60.0,
    )
    if coordination["delays_s"]:
        sorties = coordinated_sorties
        phases = build_trajectory(sorties)
        samples, intervals = screen_direct_links(sorties, phases, sample_step_s)
        gaps = sorted((item for item in intervals if not item["direct_available"]),
                      key=lambda item: (item["start_s"], item["sortie"]))
    relay_candidates = search_relay_candidates(sorties, phases, gaps, relay_candidate_step_s)
    flat_candidates = [
        {"candidate_group": group["group"], **candidate}
        for group in relay_candidates for candidate in group["candidates"]
    ]
    relay_schedule = select_relay_schedule(relay_candidates, len(gaps))
    audit_evaluator = LinkEvaluator()
    try:
        elevation_audit = _node_elevation_audit(audit_evaluator)
    finally:
        audit_evaluator.close()
    metrics = {
        "status": "relay candidate/partial schedule diagnostic; not a feasible Q3 solution",
        "transport_feasible": transport_metrics["feasible"],
        "box_count": len(boxes),
        "sortie_count": len(sorties),
        "direct_link_threshold_db": link_limits(load_link_parameters())["transport_gateway_db"],
        "sample_step_s": sample_step_s,
        "transport_start_coordination": coordination,
        "sample_count": len(samples),
        "direct_gap_sample_count": sum(not item["available"] for item in samples),
        "direct_gap_interval_count": len(gaps),
        "relay_candidate_step_s": relay_candidate_step_s,
        "relay_candidates_saved_per_group": "best representative for each distinct gap-coverage subset",
        "relay_candidate_summary": [
            {key: gap[key] for key in ("group", "covered_sorties", "gap_count", "gap_start_s", "gap_end_s", "candidate_count")}
            for gap in relay_candidates
        ],
        "gap_groups_with_relay_candidate": sum(item["candidate_count"] > 0 for item in relay_candidates),
        "relay_candidate_feasibility": "candidates are screened for sampled simultaneous relay-access coverage of subsets within overlapping direct-gap components; final continuous communication is not certified",
        "relay_schedule_feasibility": relay_schedule["method"],
        "relay_schedule": {key: value for key, value in relay_schedule.items() if key != "selected"},
        "DSM_node_elevation_audit_count": len(elevation_audit),
        "continuity_certified": False,
        "note": "Fixed-step direct-link screening is diagnostic only; failed intervals require relay coverage and final adaptive audit.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "link_samples.csv", samples)
    _write_csv(output_dir / "direct_link_intervals.csv", intervals)
    _write_csv(output_dir / "relay_candidates.csv", flat_candidates)
    _write_csv(output_dir / "relay_schedule.csv", relay_schedule["selected"])
    _write_csv(output_dir / "node_dsm_elevation_audit.csv", elevation_audit)
    _write_csv(output_dir / "relay_uncovered_gaps.csv", [
        {"gap_id": gap_id, **next(gap for group in relay_candidates for gap in group["gaps"]
                                 if gap["gap_id"] == gap_id)}
        for gap_id in relay_schedule["uncovered_gap_ids"]
    ])
    _write_csv(output_dir / "gap_id_map.csv", [
        gap for group in relay_candidates for gap in group["gaps"]
    ])
    (output_dir / "screening.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Problem 3 communication and relay scheduler")
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    parser.add_argument("--sample-step", type=float, default=10.0)
    parser.add_argument("--relay-candidate-step", type=float, default=30.0)
    args = parser.parse_args()
    if args.sample_step <= 0 or args.relay_candidate_step <= 0:
        parser.error("sampling steps must be positive")
    print(json.dumps(run(args.output, args.sample_step, args.relay_candidate_step), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
