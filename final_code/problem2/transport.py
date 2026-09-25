from __future__ import annotations

import argparse
import copy
import csv
import itertools
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from openpyxl import load_workbook

from final_code.problem1.solver import (
    Aircraft,
    Box,
    DEM_PATH,
    ROOT,
    leg_flight,
    load_aircraft,
    load_energy_per_meter,
    load_nodes,
    sample_leg,
)

BASE_DATA = ROOT / "data" / "无人机应急物资运输基础数据"
OUTPUT_DEFAULT = ROOT / "outputs" / "problem2"


@dataclass(frozen=True)
class TaskBox(Box):
    first_batch: bool
    first_deadline_s: float | None
    due_s: float | None
    priority: float


@dataclass(frozen=True)
class Drone:
    code: str
    aircraft: str


@dataclass(frozen=True)
class Battery:
    code: str
    aircraft: str
    full_charge_s: float


@dataclass
class Sortie:
    code: str
    aircraft: str
    boxes: list[TaskBox]
    route: list[str]
    mass_kg: float
    volume_m3: float
    energy_kwh: float
    flight_s: float
    prep_start_s: float = 0.0
    prep_end_s: float = 0.0
    loading_end_s: float = 0.0
    takeoff_s: float = 0.0
    return_s: float = 0.0
    drone: str = ""
    battery: str = ""
    battery_soc_return_percent: float = 0.0
    deliveries: dict[str, float] | None = None
    legs: list[dict] | None = None


def _rows(path: Path, sheet: str | None = None) -> list[tuple]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    worksheet = workbook[sheet] if sheet else workbook.active
    try:
        return [tuple(row) for row in worksheet.iter_rows(values_only=True)]
    finally:
        workbook.close()


def load_task_boxes() -> list[TaskBox]:
    rows = _rows(BASE_DATA / "物资需求与配送时限.xlsx", "逐箱货箱清单")
    result = []
    for row in rows[1:]:
        if not row[0]:
            continue
        result.append(TaskBox(
            code=str(row[0]), site=str(row[1]), item_type=str(row[2]),
            mass_kg=float(row[3]), volume_m3=float(row[4]),
            first_batch=str(row[5]).strip() in {"是", "1", "True"},
            first_deadline_s=float(row[6]) if row[6] is not None else None,
            due_s=float(row[7]) if row[7] is not None else None,
            priority=float(row[8] or 1),
        ))
    if len(result) != 80 or len({box.code for box in result}) != len(result):
        raise ValueError("Expected 80 unique task boxes")
    return result


def load_resources() -> tuple[list[Drone], list[Battery]]:
    rows = _rows(BASE_DATA / "运输无人机数据.xlsx")
    drones = [Drone(str(row[0]), str(row[1])) for row in rows if row[0] and str(row[0]).startswith("U")]
    batteries = []
    for row in rows:
        if row[0] in {"A", "B", "C"} and isinstance(row[1], (int, float)):
            aircraft = str(row[0])
            count, full_charge = int(row[1]), float(row[2])
            batteries.extend(Battery(f"{aircraft}-B{index:02d}", aircraft, full_charge) for index in range(1, count + 1))
    if len(drones) != 8 or len(batteries) != 14:
        raise ValueError(f"Unexpected inventory: {len(drones)} drones, {len(batteries)} batteries")
    return drones, batteries


def _aircraft_for(code: str, aircrafts: dict[str, Aircraft], reserve: float) -> Aircraft:
    original = aircrafts[code]
    return Aircraft(**{**asdict(original), "reserve_fraction": reserve})


class RouteEvaluator:
    def __init__(self, reserve: float, energy_scale: float):
        self.base, self.sites = load_nodes()
        self.aircrafts = load_aircraft()
        self.energy_rates = {key: value * energy_scale for key, value in load_energy_per_meter(self.aircrafts).items()}
        self.reserve = reserve
        self.dem = rasterio.open(DEM_PATH)
        self.route_data: dict[tuple[str, str], tuple[float, float]] = {}

    def close(self) -> None:
        self.dem.close()

    def route_leg(self, start: str, end: str) -> tuple[float, float]:
        key = (start, end)
        if key not in self.route_data:
            start_node = self.base if start == "O01" else self.sites[start]
            end_node = self.base if end == "O01" else self.sites[end]
            self.route_data[key] = sample_leg(self.dem, start_node, end_node)
        return self.route_data[key]

    def evaluate(self, boxes: list[TaskBox], route: list[str], aircraft_code: str) -> Sortie | None:
        aircraft = _aircraft_for(aircraft_code, self.aircrafts, self.reserve)
        mass = sum(box.mass_kg for box in boxes)
        volume = sum(box.volume_m3 for box in boxes)
        if mass > aircraft.max_payload_kg + 1e-9 or volume > aircraft.volume_m3 + 1e-12:
            return None
        remaining = mass
        current = "O01"
        current_alt = self.base.elevation_m
        total_energy = total_time = 0.0
        legs = []
        for destination in [*route, "O01"]:
            max_ground, distance = self.route_leg(current, destination)
            cruise_alt = max_ground + 50
            end_alt = self.base.elevation_m if destination == "O01" else self.sites[destination].elevation_m + 30
            flight_time, energy, range_budget = leg_flight(
                aircraft, self.energy_rates[aircraft_code], distance, cruise_alt,
                current_alt, end_alt, remaining,
            )
            if distance > range_budget + 1e-7:
                return None
            total_energy += energy
            total_time += flight_time
            legs.append({
                "from": current, "to": destination, "payload_kg": remaining,
                "distance_m": distance, "cruise_altitude_m": cruise_alt,
                "flight_s": flight_time, "energy_kwh": energy,
            })
            if destination != "O01":
                remaining -= sum(box.mass_kg for box in boxes if box.site == destination)
            current, current_alt = destination, end_alt
        if total_energy > aircraft.usable_energy_kwh * (1 - self.reserve) + 1e-10:
            return None
        return Sortie(
            code="", aircraft=aircraft_code, boxes=boxes[:], route=route[:],
            mass_kg=mass, volume_m3=volume, energy_kwh=total_energy,
            flight_s=total_time, battery_soc_return_percent=100 * (1 - total_energy / aircraft.usable_energy_kwh),
            legs=legs,
        )


def _hard_due(box: TaskBox) -> float | None:
    deadlines = _hard_deadlines(box)
    return min((deadline for _, deadline in deadlines), default=None)


def _hard_deadlines(box: TaskBox) -> list[tuple[str, float]]:
    deadlines = []
    if box.item_type == "医疗物资" and box.due_s is not None:
        deadlines.append(("医疗期望送达", box.due_s))
    if box.first_batch and box.first_deadline_s is not None:
        deadlines.append(("首批截止", box.first_deadline_s))
    return deadlines


def _schedule_deliveries(sortie: Sortie, aircraft: Aircraft) -> None:
    current = sortie.takeoff_s
    deliveries = {}
    box_count = {site: sum(box.site == site for box in sortie.boxes) for site in sortie.route}
    for leg in sortie.legs or []:
        current += leg["flight_s"]
        site = leg["to"]
        if site == "O01":
            continue
        current += aircraft.handoff_base_s + aircraft.handoff_each_s * box_count[site]
        for box in sortie.boxes:
            if box.site == site:
                deliveries[box.code] = current
    sortie.deliveries = deliveries


def _partition_by_site(boxes: list[TaskBox], evaluator: RouteEvaluator) -> list[Sortie]:
    by_site: dict[str, list[TaskBox]] = {}
    for box in boxes:
        by_site.setdefault(box.site, []).append(box)
    sorties: list[Sortie] = []
    for site, site_boxes in by_site.items():
        remaining = site_boxes[:]
        while remaining:
            urgent = [box for box in remaining if _hard_due(box) is not None]
            pool = urgent if urgent else remaining
            chosen = None
            for size in range(len(pool), 0, -1):
                for batch in itertools.combinations(pool, size):
                    for aircraft in sorted(evaluator.aircrafts):
                        candidate = evaluator.evaluate(list(batch), [site], aircraft)
                        if candidate:
                            # Keep scarce heavy-lift aircraft available for loads that need them.
                            scarcity = {"A": 0.0, "B": 120.0, "C": 360.0}[aircraft]
                            score = candidate.flight_s + evaluator.aircrafts[aircraft].prep_s + evaluator.aircrafts[aircraft].load_each_s * len(batch) + scarcity
                            if chosen is None or score < chosen[0]:
                                chosen = (score, candidate)
                if chosen is not None:
                    chosen = chosen[1]
                    break
            if chosen is None:
                raise ValueError(f"No feasible one-site load for box {remaining[0].code} at {site}")
            sorties.append(chosen)
            chosen_ids = {box.code for box in chosen.boxes}
            remaining = [box for box in remaining if box.code not in chosen_ids]
    return sorties


def _merge_multisite(sorties: list[Sortie], evaluator: RouteEvaluator) -> list[Sortie]:
    active = sorties[:]
    changed = True
    while changed:
        changed = False
        best = None
        baseline_count = len(active)
        for first_index, first in enumerate(active):
            for second_index in range(first_index + 1, len(active)):
                second = active[second_index]
                if first.aircraft != second.aircraft or set(first.route) & set(second.route):
                    continue
                # Preserve urgent boxes as dedicated single-site sorties unless
                # a combined route can still deliver each hard-deadline box on time.
                merged_boxes = first.boxes + second.boxes
                if len({box.site for box in merged_boxes}) != 2:
                    continue
                for route in (first.route + second.route, second.route + first.route):
                    candidate = evaluator.evaluate(merged_boxes, route, first.aircraft)
                    if candidate is None:
                        continue
                    aircraft = _aircraft_for(candidate.aircraft, evaluator.aircrafts, evaluator.reserve)
                    current = aircraft.prep_s + aircraft.load_each_s * len(candidate.boxes)
                    counts = {site: sum(box.site == site for box in candidate.boxes) for site in route}
                    possible = True
                    for leg in candidate.legs or []:
                        current += leg["flight_s"]
                        site = leg["to"]
                        if site == "O01":
                            continue
                        current += aircraft.handoff_base_s + aircraft.handoff_each_s * counts[site]
                        if any(_hard_due(box) is not None and current > _hard_due(box) for box in candidate.boxes if box.site == site):
                            possible = False
                            break
                    if not possible:
                        continue
                    score = candidate.energy_kwh + 1e-6 * candidate.flight_s
                    if best is None or score < best[0]:
                        best = (score, first_index, second_index, candidate)
        if best:
            _, first_index, second_index, merged = best
            active = [item for index, item in enumerate(active) if index not in {first_index, second_index}]
            active.append(merged)
            changed = len(active) < baseline_count
    return active


def _charge_duration(full_charge_s: float, soc: float) -> float:
    if soc < 0.9:
        return full_charge_s * (0.65 * (0.9 - soc) / 0.9 + 0.35)
    return full_charge_s * 0.35 * (1 - soc) / 0.1


def _assign_and_schedule(
    sorties: list[Sortie], drones: list[Drone], batteries: list[Battery], evaluator: RouteEvaluator,
    objective: str = "balanced",
    order_policy: str = "slack",
) -> list[Sortie]:
    if objective not in {"balanced", "energy"}:
        raise ValueError(f"Unknown objective profile: {objective}")
    by_type_drone = {kind: sorted(item.code for item in drones if item.aircraft == kind) for kind in evaluator.aircrafts}
    by_type_battery = {kind: sorted((item for item in batteries if item.aircraft == kind), key=lambda item: item.code) for kind in evaluator.aircrafts}
    drone_ready = {drone.code: 0.0 for drone in drones}
    battery_ready = {battery.code: 0.0 for battery in batteries}
    # Schedule urgent and long tasks first; their selected starts remain resource-feasible.
    def urgency(item: Sortie) -> tuple[float, float, float]:
        deadlines = [_hard_due(box) for box in item.boxes]
        deadlines = [value for value in deadlines if value is not None]
        aircraft = _aircraft_for(item.aircraft, evaluator.aircrafts, evaluator.reserve)
        processing = aircraft.prep_s + aircraft.load_each_s * len(item.boxes) + item.flight_s
        slack = min((deadline - processing for deadline in deadlines), default=math.inf)
        return (slack, min(deadlines, default=math.inf), item.flight_s)
    if order_policy == "slack":
        ordered = sorted(sorties, key=lambda item: urgency(item))
    elif order_policy == "deadline":
        ordered = sorted(sorties, key=lambda item: (urgency(item)[1], urgency(item)[0], item.flight_s))
    elif order_policy == "shortest":
        ordered = sorted(sorties, key=lambda item: (item.flight_s, urgency(item)[0]))
    elif order_policy == "longest":
        ordered = sorted(sorties, key=lambda item: (-item.flight_s, urgency(item)[0]))
    else:
        raise ValueError(f"Unknown order policy: {order_policy}")
    for index, sortie in enumerate(ordered, 1):
        best = None
        for aircraft_code in evaluator.aircrafts:
            candidate_physics = evaluator.evaluate(sortie.boxes, sortie.route, aircraft_code)
            if candidate_physics is None:
                continue
            aircraft = _aircraft_for(aircraft_code, evaluator.aircrafts, evaluator.reserve)
            prep_load_s = aircraft.prep_s + aircraft.load_each_s * len(sortie.boxes)
            for drone_code in by_type_drone[aircraft_code]:
                for battery in by_type_battery[aircraft_code]:
                    handoff_s = sum(
                        aircraft.handoff_base_s + aircraft.handoff_each_s * sum(box.site == site for box in sortie.boxes)
                        for site in sortie.route
                    )
                    start = max(drone_ready[drone_code], battery_ready[battery.code])
                    takeoff = start + prep_load_s
                    finish = takeoff + candidate_physics.flight_s + handoff_s
                    # Reject assignments that already miss a hard deadline. This
                    # allows a feasible batch to switch from B to A/C at schedule time.
                    current = takeoff
                    deliveries = {}
                    deadline_ok = True
                    counts = {site: sum(box.site == site for box in sortie.boxes) for site in sortie.route}
                    for leg in candidate_physics.legs or []:
                        current += leg["flight_s"]
                        site = leg["to"]
                        if site == "O01":
                            continue
                        current += aircraft.handoff_base_s + aircraft.handoff_each_s * counts[site]
                        for box in sortie.boxes:
                            if box.site == site:
                                deliveries[box.code] = current
                                if _hard_due(box) is not None and current > _hard_due(box) + 1e-7:
                                    deadline_ok = False
                    if not deadline_ok:
                        continue
                    weighted_lateness = sum(
                        box.priority * max(0.0, deliveries[box.code] - box.due_s)
                        for box in sortie.boxes
                        if box.due_s is not None and box.item_type != "医疗物资"
                    )
                    if objective == "energy":
                        objective_key = (candidate_physics.energy_kwh, weighted_lateness, finish, start)
                    else:
                        objective_key = (weighted_lateness, finish, candidate_physics.energy_kwh, start)
                    _candidate = (objective_key, finish, start, drone_code, battery, takeoff, candidate_physics, deliveries)
                    if best is None or _candidate[0] < best[0]:
                        best = _candidate
        if best is None:
            raise ValueError(f"No compatible resources for sortie {index}")
        _, finish, start, drone_code, battery, takeoff, physics, deliveries = best
        assigned_aircraft = _aircraft_for(physics.aircraft, evaluator.aircrafts, evaluator.reserve)
        sortie.aircraft = physics.aircraft
        sortie.energy_kwh = physics.energy_kwh
        sortie.flight_s = physics.flight_s
        sortie.legs = physics.legs
        sortie.battery_soc_return_percent = physics.battery_soc_return_percent
        sortie.code = f"Q2-{index:03d}"
        sortie.drone, sortie.battery = drone_code, battery.code
        sortie.prep_start_s = start
        sortie.prep_end_s = start + assigned_aircraft.prep_s
        sortie.loading_end_s = takeoff
        sortie.takeoff_s = takeoff
        sortie.return_s = finish
        sortie.deliveries = deliveries
        battery_ready[battery.code] = finish + _charge_duration(
            battery.full_charge_s, 1 - sortie.energy_kwh / evaluator.aircrafts[sortie.aircraft].usable_energy_kwh,
        )
        drone_ready[drone_code] = finish
    return sorted(ordered, key=lambda item: item.code)


def _validate(
    sorties: list[Sortie], boxes: list[TaskBox], drones: list[Drone],
    batteries: list[Battery], evaluator: RouteEvaluator,
) -> dict:
    assignments: dict[str, list[Sortie]] = {drone.code: [] for drone in drones}
    battery_assignments: dict[str, list[Sortie]] = {battery.code: [] for battery in batteries}
    by_id = {box.code: box for box in boxes}
    delivered = []
    violations = []
    resource_violations = []
    deadline_violations = []
    physics_violations = []
    drone_by_id = {drone.code: drone for drone in drones}
    battery_by_id = {battery.code: battery for battery in batteries}
    if len({sortie.code for sortie in sorties}) != len(sorties):
        violations.append("duplicate sortie identifiers")
    for sortie in sorties:
        fields = (sortie.prep_start_s, sortie.prep_end_s, sortie.loading_end_s,
                  sortie.takeoff_s, sortie.return_s, sortie.energy_kwh,
                  sortie.flight_s, sortie.mass_kg, sortie.volume_m3,
                  sortie.battery_soc_return_percent)
        if any(not math.isfinite(value) or value < 0 for value in fields):
            message = f"negative or nonfinite physical/time field: {sortie.code}"
            violations.append(message)
            physics_violations.append(message)
            continue
        if any(box.code not in by_id or box != by_id[box.code] for box in sortie.boxes):
            message = f"box attributes differ from source input: {sortie.code}"
            violations.append(message)
            physics_violations.append(message)
        if sortie.aircraft not in evaluator.aircrafts:
            message = f"unknown aircraft type: {sortie.code}"
            violations.append(message)
            physics_violations.append(message)
            continue
        if sortie.drone not in assignments or sortie.battery not in battery_assignments:
            violations.append(f"unknown resource assigned: {sortie.code}")
            physics_violations.append(f"unknown resource assigned: {sortie.code}")
            continue
        assignments[sortie.drone].append(sortie)
        battery_assignments[sortie.battery].append(sortie)
        if drone_by_id[sortie.drone].aircraft != sortie.aircraft or battery_by_id[sortie.battery].aircraft != sortie.aircraft:
            message = f"aircraft/resource type mismatch: {sortie.code}"
            violations.append(message)
            physics_violations.append(message)
        if len(set(sortie.route)) != len(sortie.route) or {box.site for box in sortie.boxes} != set(sortie.route):
            message = f"route/site assignment mismatch: {sortie.code}"
            violations.append(message)
            physics_violations.append(message)
        reevaluated = evaluator.evaluate(sortie.boxes, sortie.route, sortie.aircraft)
        if reevaluated is None:
            message = f"route physical constraints failed: {sortie.code}"
            violations.append(message)
            physics_violations.append(message)
        else:
            if abs(reevaluated.energy_kwh - sortie.energy_kwh) > 1e-7:
                message = f"route energy replay mismatch: {sortie.code}"
                violations.append(message)
                physics_violations.append(message)
        if reevaluated is not None:
            if abs(reevaluated.flight_s - sortie.flight_s) > 1e-7:
                message = f"physical flight duration mismatch: {sortie.code}"
                violations.append(message)
                physics_violations.append(message)
            for index, (stored, physical) in enumerate(zip(sortie.legs or [], reevaluated.legs or []), 1):
                for field in ("flight_s", "energy_kwh", "distance_m", "cruise_altitude_m", "payload_kg"):
                    value = float(stored.get(field, math.nan))
                    if not math.isfinite(value) or abs(value - physical[field]) > 1e-7:
                        message = f"physical leg {field} mismatch: {sortie.code}/{index}"
                        violations.append(message)
                        physics_violations.append(message)
        aircraft = _aircraft_for(sortie.aircraft, evaluator.aircrafts, evaluator.reserve)
        expected_legs = ["O01", *sortie.route, "O01"]
        stored_legs = sortie.legs or []
        replay_time = sortie.takeoff_s
        replay_payload = sortie.mass_kg
        replay_deliveries = {}
        expected_leg_time = 0.0
        counts = {site: sum(box.site == site for box in sortie.boxes) for site in sortie.route}
        if len(stored_legs) != len(expected_legs) - 1:
            violations.append(f"leg count mismatch: {sortie.code}")
            physics_violations.append(f"leg count mismatch: {sortie.code}")
        for leg_index, leg in enumerate(stored_legs):
            if leg_index + 1 >= len(expected_legs):
                break
            expected_from, expected_to = expected_legs[leg_index:leg_index + 2]
            if leg.get("from") != expected_from or leg.get("to") != expected_to:
                message = f"leg sequence mismatch: {sortie.code}/{leg_index + 1}"
                violations.append(message)
                physics_violations.append(message)
            if abs(float(leg.get("payload_kg", math.inf)) - replay_payload) > 1e-8:
                message = f"leg payload replay mismatch: {sortie.code}/{leg_index + 1}"
                violations.append(message)
                physics_violations.append(message)
            leg_time = float(leg.get("flight_s", math.nan))
            if not math.isfinite(leg_time) or leg_time < 0:
                message = f"invalid leg duration: {sortie.code}/{leg_index + 1}"
                violations.append(message)
                physics_violations.append(message)
                continue
            replay_time += leg_time
            expected_leg_time += leg_time
            if expected_to != "O01":
                replay_time += aircraft.handoff_base_s + aircraft.handoff_each_s * counts[expected_to]
                for box in sortie.boxes:
                    if box.site == expected_to:
                        replay_deliveries[box.code] = replay_time
                replay_payload -= sum(box.mass_kg for box in sortie.boxes if box.site == expected_to)
        if abs(sortie.prep_end_s - (sortie.prep_start_s + aircraft.prep_s)) > 1e-7:
            message = f"preparation duration mismatch: {sortie.code}"
            violations.append(message)
            physics_violations.append(message)
        if (abs(sortie.loading_end_s - sortie.takeoff_s) > 1e-7
                or abs(sortie.takeoff_s - (sortie.prep_end_s + aircraft.load_each_s * len(sortie.boxes))) > 1e-7):
            message = f"loading duration mismatch: {sortie.code}"
            violations.append(message)
            physics_violations.append(message)
        if abs(sortie.flight_s - expected_leg_time) > 1e-7 or abs(sortie.return_s - replay_time) > 1e-7:
            message = f"flight or return timeline replay mismatch: {sortie.code}"
            violations.append(message)
            physics_violations.append(message)
        recorded_deliveries = sortie.deliveries or {}
        if set(recorded_deliveries) != set(replay_deliveries):
            message = f"delivery record coverage mismatch: {sortie.code}"
            violations.append(message)
            physics_violations.append(message)
        else:
            for box_code, expected_time in replay_deliveries.items():
                if abs(recorded_deliveries[box_code] - expected_time) > 1e-7:
                    message = f"delivery time replay mismatch: {box_code}"
                    violations.append(message)
                    physics_violations.append(message)
            if abs(sortie.battery_soc_return_percent - 100 * (1 - sortie.energy_kwh / evaluator.aircrafts[sortie.aircraft].usable_energy_kwh)) > 1e-7:
                message = f"return SOC mismatch: {sortie.code}"
                violations.append(message)
                physics_violations.append(message)
        if abs(sum(box.mass_kg for box in sortie.boxes) - sortie.mass_kg) > 1e-8 or abs(sum(box.volume_m3 for box in sortie.boxes) - sortie.volume_m3) > 1e-10:
            message = f"sortie load summary mismatch: {sortie.code}"
            violations.append(message)
            physics_violations.append(message)
        if not (sortie.prep_start_s <= sortie.prep_end_s <= sortie.takeoff_s <= sortie.return_s):
            message = f"sortie timeline invalid: {sortie.code}"
            violations.append(message)
            physics_violations.append(message)
        delivered.extend(box.code for box in sortie.boxes)
        for box in sortie.boxes:
            delivery = (sortie.deliveries or {}).get(box.code)
            hard_due = _hard_due(box)
            if delivery is None:
                violations.append(f"missing delivery time: {box.code}")
            elif hard_due is not None and delivery > hard_due + 1e-7:
                message = f"hard deadline missed: {box.code}"
                violations.append(message)
                deadline_violations.append(message)
    if len(delivered) != len(set(delivered)) or set(delivered) != set(by_id):
        violations.append("box coverage is not an exact partition")
    for values in assignments.values():
        values.sort(key=lambda item: item.prep_start_s)
        for previous, current in zip(values, values[1:]):
            if previous.return_s > current.prep_start_s + 1e-7:
                message = f"airframe overlap: {previous.drone}"
                violations.append(message)
                resource_violations.append(message)
    for battery_code, values in battery_assignments.items():
        values.sort(key=lambda item: item.prep_start_s)
        battery = battery_by_id[battery_code]
        for previous, current in zip(values, values[1:]):
            soc = 1 - previous.energy_kwh / evaluator.aircrafts[battery.aircraft].usable_energy_kwh
            available = previous.return_s + _charge_duration(battery.full_charge_s, soc)
            if available > current.prep_start_s + 1e-7:
                message = f"battery charge overlap: {battery_code}"
                violations.append(message)
                resource_violations.append(message)
    total_boxes = len(boxes)
    due_boxes = [box for box in boxes if box.due_s is not None]
    soft_boxes = [box for box in due_boxes if box.item_type != "医疗物资"]
    due_map = {box.code: (sortie.deliveries or {}).get(box.code, 0.0) for sortie in sorties for box in sortie.boxes}
    all_tardiness = {box.code: max(0.0, due_map.get(box.code, 0.0) - box.due_s) for box in due_boxes}
    soft_tardiness = {box.code: all_tardiness[box.code] for box in soft_boxes}
    hard_checks = [
        (box, delivery, deadline)
        for sortie in sorties for box in sortie.boxes
        for _, deadline in _hard_deadlines(box)
        for delivery in [(sortie.deliveries or {}).get(box.code, math.inf)]
    ]
    expected_by_type = {}
    hard_by_type = {}
    for item_type in sorted({box.item_type for box in boxes}):
        typed_due = [box for box in due_boxes if box.item_type == item_type]
        expected_by_type[item_type] = {
            "count": len(typed_due),
            "on_time_count": sum(all_tardiness[box.code] <= 1e-7 for box in typed_due),
            "on_time_rate": sum(all_tardiness[box.code] <= 1e-7 for box in typed_due) / len(typed_due) if typed_due else 1.0,
        }
        typed_hard = [(box, delivery, deadline) for box, delivery, deadline in hard_checks if box.item_type == item_type]
        hard_by_type[item_type] = {
            "constraint_count": len(typed_hard),
            "compliant_count": sum(delivery <= deadline + 1e-7 for _, delivery, deadline in typed_hard),
            "compliance_rate": sum(delivery <= deadline + 1e-7 for _, delivery, deadline in typed_hard) / len(typed_hard) if typed_hard else 1.0,
        }
    makespan = max((sortie.return_s for sortie in sorties), default=0.0)
    return {
        "feasible": not violations,
        "violations": violations,
        "hard_deadlines_feasible": not deadline_violations,
        "resource_schedule_feasible": not resource_violations,
        "physics_and_timeline_feasible": not physics_violations,
        "box_count": total_boxes,
        "assigned_box_count": len(delivered),
        "sortie_count": len(sorties),
        "total_energy_kwh": sum(item.energy_kwh for item in sorties),
        "makespan_s": makespan,
        "hard_deadline_check_count": len(hard_checks),
        "hard_deadline_compliant_count": sum(delivery <= deadline + 1e-7 for _, delivery, deadline in hard_checks),
        "hard_deadline_compliance_rate": (sum(delivery <= deadline + 1e-7 for _, delivery, deadline in hard_checks) / len(hard_checks)) if hard_checks else 1.0,
        "all_due_box_count": len(due_boxes),
        "all_expected_on_time_count": sum(value <= 1e-7 for value in all_tardiness.values()),
        "all_expected_on_time_rate": (sum(value <= 1e-7 for value in all_tardiness.values()) / len(due_boxes)) if due_boxes else 1.0,
        "all_expected_tardiness_s": sum(all_tardiness.values()),
        "weighted_all_expected_tardiness": sum(all_tardiness[box.code] * box.priority for box in due_boxes),
        "expected_time_by_item_type": expected_by_type,
        "hard_deadline_by_item_type": hard_by_type,
        "soft_tardiness_s": sum(soft_tardiness.values()),
        "weighted_soft_tardiness_s": sum(soft_tardiness[box.code] * box.priority for box in soft_boxes),
        "soft_on_time_rate": (sum(value <= 1e-7 for value in soft_tardiness.values()) / len(soft_boxes)) if soft_boxes else 1.0,
        "resource_checks": {"airframe_count": len(drones), "battery_count": len(batteries), "all_conflicts_clear": not resource_violations},
    }


def _schedule_candidates(
    routes: list[Sortie], drones: list[Drone], batteries: list[Battery], evaluator: RouteEvaluator,
    objective: str,
) -> tuple[list[Sortie] | None, dict]:
    candidates = []
    failures = []
    assignment_profiles = ("balanced", "energy") if objective == "balanced" else (objective,)
    for order_policy in ("slack", "deadline", "shortest", "longest"):
        for assignment_profile in assignment_profiles:
            try:
                schedule = _assign_and_schedule(
                    copy.deepcopy(routes), drones, batteries, evaluator, assignment_profile, order_policy,
                )
                metrics = _validate(schedule, load_task_boxes(), drones, batteries, evaluator)
                metrics["dispatch_order"] = order_policy
                metrics["assignment_profile"] = assignment_profile
                if metrics["feasible"]:
                    candidates.append((schedule, metrics))
            except ValueError as error:
                failures.append(f"{order_policy}/{assignment_profile}: {error}")
    if not candidates:
        return None, {"feasible": False, "reason": "; ".join(failures) or "all candidate schedules failed audit"}
    if objective == "energy":
        key = lambda item: (
            item[1]["total_energy_kwh"], item[1]["weighted_soft_tardiness_s"],
            item[1]["makespan_s"], item[1]["sortie_count"],
        )
    else:
        key = lambda item: (
            item[1]["weighted_all_expected_tardiness"], item[1]["makespan_s"],
            item[1]["total_energy_kwh"], item[1]["sortie_count"],
        )
    return min(candidates, key=key)


def _schedule_signature(sorties: list[Sortie]) -> tuple:
    return tuple(sorted(
        (tuple(sorted(box.code for box in item.boxes)), tuple(item.route), item.aircraft,
         item.drone, item.battery, round(item.prep_start_s, 6), round(item.return_s, 6))
        for item in sorties
    ))


def solve(reserve: float = 0.2, energy_scale: float = 1.0, return_candidates: bool = False):
    boxes = load_task_boxes()
    drones, batteries = load_resources()
    evaluator = RouteEvaluator(reserve, energy_scale)
    try:
        initial = _partition_by_site(boxes, evaluator)
        merged = _merge_multisite(initial, evaluator)
        grouping_options = (("不跨区", initial), ("多点合并", merged))
        selected = []
        unique_candidates: dict[tuple, dict] = {}
        for grouping, routes in grouping_options:
            for profile in ("balanced", "energy"):
                schedule, candidate_metrics = _schedule_candidates(routes, drones, batteries, evaluator, profile)
                if schedule is None:
                    continue
                signature = _schedule_signature(schedule)
                candidate = unique_candidates.setdefault(signature, {
                    "sorties": schedule,
                    "metrics": candidate_metrics,
                    "labels": [],
                })
                label = f"{grouping}/{profile}"
                if label not in candidate["labels"]:
                    candidate["labels"].append(label)
                if profile == "balanced":
                    selected.append(candidate)
        if not selected:
            raise ValueError("No hard-time-feasible schedule found for any grouping candidate")
        primary = min(selected, key=lambda item: (
            item["metrics"]["weighted_all_expected_tardiness"],
            item["metrics"]["makespan_s"], item["metrics"]["total_energy_kwh"],
            item["metrics"]["sortie_count"],
        ))
        metrics = dict(primary["metrics"])
        metrics["objective_profile"] = "weighted lateness, makespan, energy, sorties"
        metrics["primary_candidate"] = primary["labels"]
        metrics["candidate_scope"] = "single-site batches and greedy pairwise two-site merges; balanced and energy assignment heuristics"
        metrics["tradeoff_candidates"] = {
            " | ".join(item["labels"]): item["metrics"] for item in unique_candidates.values()
        }
        if return_candidates:
            candidates = [
                {"labels": list(item["labels"]), "sorties": item["sorties"], "metrics": item["metrics"]}
                for item in unique_candidates.values()
            ]
            return primary["sorties"], metrics, boxes, candidates
        return primary["sorties"], metrics, boxes
    finally:
        evaluator.close()


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_program_bundle(output_path: Path) -> None:
    from final_code.package import write_program_bundle

    write_program_bundle(output_path)


def write_outputs(
    sorties: list[Sortie], metrics: dict, boxes: list[TaskBox], output_dir: Path,
    reserve: float, energy_scale: float,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    template = load_workbook(ROOT / "docs" / "结果提交模板.xlsx")
    worksheet = template["Q2_运输架次"]
    if worksheet.max_row > 1:
        worksheet.delete_rows(2, worksheet.max_row - 1)
    for sortie in sorties:
        worksheet.append([
            sortie.code, sortie.drone, sortie.aircraft, sortie.battery,
            round(sortie.prep_start_s, 3), "→".join(["O01", *sortie.route, "O01"]),
            round(sortie.return_s, 3), round(sortie.energy_kwh, 6),
        ])
    delivery_sheet = template["Q2_逐箱交付"]
    if delivery_sheet.max_row > 1:
        delivery_sheet.delete_rows(2, delivery_sheet.max_row - 1)
    for sortie in sorties:
        for box in sortie.boxes:
            delivery_sheet.append([box.code, sortie.code, box.site, round((sortie.deliveries or {})[box.code], 3)])
    template.save(output_dir / "problem2_submission.xlsx")

    sortie_rows, delivery_rows, segment_rows, battery_rows = [], [], [], []
    for sortie in sorties:
        sortie_rows.append({
            "架次编号": sortie.code, "无人机编号": sortie.drone, "机型编号": sortie.aircraft,
            "电池编号": sortie.battery, "准备开始时刻（s）": sortie.prep_start_s,
            "准备完成时刻（s）": sortie.prep_end_s, "装载完成/起飞时刻（s）": sortie.takeoff_s,
            "访问服务区顺序": "→".join(sortie.route), "返回O01时刻（s）": sortie.return_s,
            "架次能耗（kWh）": sortie.energy_kwh, "质量（kg）": sortie.mass_kg,
            "体积（m³）": sortie.volume_m3, "返航SOC（%）": sortie.battery_soc_return_percent,
        })
        for box in sortie.boxes:
            delivered = (sortie.deliveries or {})[box.code]
            hard_deadline_results = [
                f"{kind}:{'是' if delivered <= deadline else '否'}"
                for kind, deadline in _hard_deadlines(box)
            ]
            delivery_rows.append({
                "货箱编号": box.code, "物资类型": box.item_type, "架次编号": sortie.code,
                "服务区编号": box.site, "是否首批保障": box.first_batch,
                "期望送达时间（s）": box.due_s if box.due_s is not None else "",
                "首批截止时间（s）": box.first_deadline_s if box.first_batch and box.first_deadline_s is not None else "",
                "交付完成时刻（s）": delivered,
                "期望时间迟到（s）": max(0.0, delivered - box.due_s) if box.due_s is not None else "",
                "硬时限检查": ";".join(hard_deadline_results) if hard_deadline_results else "无需硬时限",
            })
        for sequence, leg in enumerate(sortie.legs or [], 1):
            segment_rows.append({"架次编号": sortie.code, "航段序号": sequence, **leg})
    _write_csv(output_dir / "sorties_audit.csv", list(sortie_rows[0]) if sortie_rows else [], sortie_rows)
    _write_csv(output_dir / "box_delivery_audit.csv", list(delivery_rows[0]) if delivery_rows else [], delivery_rows)
    _write_csv(output_dir / "route_segments.csv", list(segment_rows[0]) if segment_rows else [], segment_rows)

    aircraft_by_code = load_aircraft()
    batteries = load_resources()[1]
    for battery in batteries:
        uses = sorted((item for item in sorties if item.battery == battery.code), key=lambda item: item.prep_start_s)
        for item in uses:
            soc = 1 - item.energy_kwh / aircraft_by_code[item.aircraft].usable_energy_kwh
            charge = _charge_duration(battery.full_charge_s, soc)
            battery_rows.append({
                "电池编号": battery.code, "机型编号": battery.aircraft, "架次编号": item.code,
                "任务占用开始（s）": item.prep_start_s, "返航释放（s）": item.return_s,
                "返航SOC（%）": soc * 100, "充电开始（s）": item.return_s,
                "充电完成（s）": item.return_s + charge,
            })
    _write_csv(output_dir / "battery_audit.csv", list(battery_rows[0]) if battery_rows else [], battery_rows)
    tradeoff_rows = []
    for policy, routes in metrics.get("tradeoff_candidates", {}).items():
        tradeoff_rows.append({
            "方案": policy,
            "可行": routes.get("feasible", False),
            "架次": routes.get("sortie_count", ""),
            "总能耗（kWh）": routes.get("total_energy_kwh", ""),
            "完成时间（s）": routes.get("makespan_s", ""),
            "加权迟到（全部期望时间）": routes.get("weighted_all_expected_tardiness", ""),
            "全部期望时间准时率": routes.get("all_expected_on_time_rate", ""),
            "硬截止合规率": routes.get("hard_deadline_compliance_rate", ""),
            "说明": routes.get("reason", "feasible heuristic candidate; not a Pareto-optimality certificate"),
        })
    if tradeoff_rows:
        _write_csv(output_dir / "objective_tradeoff.csv", list(tradeoff_rows[0]), tradeoff_rows)
    _plot_routes(sorties, output_dir / "routes.png")
    _plot_resource_gantt(sorties, output_dir / "resource_gantt.png")
    _plot_delivery_times(sorties, boxes, output_dir / "delivery_times.png")
    _write_program_bundle(output_dir / "problem2_program.zip")
    (output_dir / "validation.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "model_assumptions.json").write_text(json.dumps({
        "reserve_fraction": reserve,
        "horizontal_energy_scale": energy_scale,
        "horizontal_energy_model": "E_hor = E_use * distance / L(payload); baseline E_use/L0 scaled by L0/L(payload)",
        "distance": "great-circle haversine, mean Earth radius 6371008.8 m",
        "dem_sampling": "maximum over every DEM cell touched by the coordinate-linear segment, including edge and corner contacts",
        "cruise_clearance_m": 50.0,
        "template_start_time": "preparation start",
        "airframe_release": "at return to O01; no extra turnaround data provided",
        "battery_reuse": "only after full recharge; independent of airframe release",
        "handoff_timing": "each site's handoff duration is applied after arrival and before the next leg; final-site handoff occurs before return to O01",
        "loading_and_preparation": "fixed preparation followed by serial per-box loading",
        "solver": "deterministic constructive heuristic; no global optimality guarantee",
        "objective_profile": metrics.get("objective_profile", "balanced"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def _plot_routes(sorties: list[Sortie], output_path: Path) -> None:
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
    axis.set_title("Problem 2 transport routes (colors identify aircraft type)")
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def _plot_resource_gantt(sorties: list[Sortie], output_path: Path) -> None:
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
    axes[0].set_title("Resource schedule; battery recharge follows each sortie")
    axes[1].set_xlabel("Time (s)")
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def _plot_delivery_times(sorties: list[Sortie], boxes: list[TaskBox], output_path: Path) -> None:
    delivery = {box.code: time for sortie in sorties for box, time in ((box, (sortie.deliveries or {}).get(box.code, 0)) for box in sortie.boxes)}
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
    axis.set_title("Actual and expected delivery times")
    axis.grid(axis="x", alpha=0.25)
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description="Construct a feasible Problem 2 transport schedule")
    parser.add_argument("--reserve", type=float, default=0.2)
    parser.add_argument("--energy-scale", type=float, default=1.0)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    args = parser.parse_args()
    if not 0 <= args.reserve < 1 or args.energy_scale <= 0:
        parser.error("reserve must be in [0,1), energy-scale must be positive")
    sorties, metrics, boxes = solve(args.reserve, args.energy_scale)
    drones, batteries = load_resources()
    write_outputs(sorties, metrics, boxes, args.output, args.reserve, args.energy_scale)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"Wrote results to {args.output}")
    if not metrics["feasible"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
