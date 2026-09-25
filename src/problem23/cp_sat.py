"""CP-SAT resource scheduler for a fixed set of routes.

Model times are conservatively rounded upward to whole seconds. Returned
times use the original floating-point flight model and are re-audited.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass

from src.problem21.solver import (
    Battery, Drone, RouteEvaluator, Sortie, _aircraft_for, _charge_duration,
    _hard_due,
)


@dataclass(frozen=True)
class RouteOption:
    sortie: Sortie
    duration_s: int
    charge_s: int
    delivery_offsets_s: dict[str, int]


def route_options(route: Sortie, evaluator: RouteEvaluator,
                  batteries: list[Battery]) -> list[RouteOption]:
    options = []
    charge_by_type = {battery.aircraft: battery.full_charge_s for battery in batteries}
    for kind in evaluator.aircrafts:
        physical = evaluator.evaluate(route.boxes, route.route, kind)
        if physical is None:
            continue
        aircraft = _aircraft_for(kind, evaluator.aircrafts, evaluator.reserve)
        elapsed = aircraft.prep_s + aircraft.load_each_s * len(route.boxes)
        offsets = {}
        for leg in physical.legs or []:
            elapsed += leg["flight_s"]
            site = leg["to"]
            if site == "O01":
                continue
            site_boxes = [box for box in route.boxes if box.site == site]
            elapsed += aircraft.handoff_base_s + aircraft.handoff_each_s * len(site_boxes)
            for box in site_boxes:
                offsets[box.code] = math.ceil(elapsed - 1e-9)
        if any(offsets[box.code] > math.floor(_hard_due(box) + 1e-9)
               for box in route.boxes if _hard_due(box) is not None):
            continue
        soc = 1 - physical.energy_kwh / aircraft.usable_energy_kwh
        charge = _charge_duration(charge_by_type[kind], soc)
        options.append(RouteOption(physical, math.ceil(elapsed - 1e-9),
                                   math.ceil(charge - 1e-9), offsets))
    return options

def solve_fixed_routes(routes: list[Sortie], drones: list[Drone], batteries: list[Battery],
                       evaluator: RouteEvaluator, time_limit_s: float = 30.0,
                       num_search_workers: int = 8, random_seed: int | None = None):
    from ortools.sat.python import cp_model
    alternatives = [route_options(route, evaluator, batteries) for route in routes]
    if any(not options for options in alternatives):
        return None, {"status": "INFEASIBLE", "reason": "route has no feasible aircraft"}
    horizon = sum(max(option.duration_s + option.charge_s for option in options)
                  for options in alternatives) + 3600
    model = cp_model.CpModel()
    starts, ends = [], []
    chosen, drone_choices, battery_choices = {}, {}, {}
    drone_intervals = {drone.code: [] for drone in drones}
    battery_intervals = {battery.code: [] for battery in batteries}
    weighted_late = []

    for index, options in enumerate(alternatives):
        start = model.new_int_var(0, horizon, f"start_{index}")
        end = model.new_int_var(0, horizon, f"end_{index}")
        starts.append(start)
        ends.append(end)
        type_flags = []
        for option_index, option in enumerate(options):
            kind = option.sortie.aircraft
            flag = model.new_bool_var(f"type_{index}_{kind}")
            chosen[index, option_index] = flag
            type_flags.append(flag)
            model.add(end == start + option.duration_s).only_enforce_if(flag)
            active_drones = []
            for drone in drones:
                if drone.aircraft != kind:
                    continue
                assigned = model.new_bool_var(f"drone_{index}_{drone.code}")
                active_drones.append(assigned)
                drone_choices[index, option_index, drone.code] = assigned
                drone_intervals[drone.code].append(model.new_optional_interval_var(
                    start, option.duration_s, end, assigned,
                    f"drone_interval_{index}_{drone.code}",
                ))
            model.add(sum(active_drones) == flag)
            active_batteries = []
            for battery in batteries:
                if battery.aircraft != kind:
                    continue
                assigned = model.new_bool_var(f"battery_{index}_{battery.code}")
                active_batteries.append(assigned)
                battery_choices[index, option_index, battery.code] = assigned
                charge_end = model.new_int_var(0, horizon, f"charge_end_{index}_{battery.code}")
                battery_intervals[battery.code].append(model.new_optional_interval_var(
                    start, option.duration_s + option.charge_s, charge_end,
                    assigned, f"battery_interval_{index}_{battery.code}",
                ))
            model.add(sum(active_batteries) == flag)
            for box in option.sortie.boxes:
                deadline = _hard_due(box)
                if deadline is not None:
                    model.add(start + option.delivery_offsets_s[box.code]
                              <= math.floor(deadline + 1e-9)).only_enforce_if(flag)
        model.add(sum(type_flags) == 1)
        for box in routes[index].boxes:
            if box.due_s is None or box.item_type == "医疗物资":
                continue
            late = model.new_int_var(0, horizon, f"late_{box.code}")
            for option_index, option in enumerate(options):
                model.add(late >= start + option.delivery_offsets_s[box.code]
                          - math.floor(box.due_s + 1e-9)).only_enforce_if(chosen[index, option_index])
            weighted_late.append(round(box.priority * 100) * late)

    for intervals in drone_intervals.values():
        model.add_no_overlap(intervals)
    for intervals in battery_intervals.values():
        model.add_no_overlap(intervals)
    makespan = model.new_int_var(0, horizon, "makespan")
    model.add_max_equality(makespan, ends)
    model.minimize(makespan)
    first_solver = cp_model.CpSolver()
    first_solver.parameters.max_time_in_seconds = time_limit_s
    first_solver.parameters.num_search_workers = num_search_workers
    if random_seed is not None:
        first_solver.parameters.random_seed = random_seed
    status = first_solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, {"status": first_solver.status_name(status),
                      "best_bound_s": first_solver.best_objective_bound}
    first_status = first_solver.status_name(status)
    first_makespan = round(first_solver.objective_value)
    first_bound = first_solver.best_objective_bound
    solver = first_solver
    if weighted_late:
        model.add(makespan <= first_makespan)
        model.minimize(sum(weighted_late))
        second_solver = cp_model.CpSolver()
        second_solver.parameters.max_time_in_seconds = max(5.0, time_limit_s / 2)
        second_solver.parameters.num_search_workers = num_search_workers
        if random_seed is not None:
            second_solver.parameters.random_seed = random_seed
        second_status = second_solver.solve(model)
        if second_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            solver = second_solver

    scheduled = []
    for index, options in enumerate(alternatives):
        option_index = next(i for i in range(len(options)) if solver.value(chosen[index, i]))
        option = options[option_index]
        sortie = copy.deepcopy(option.sortie)
        aircraft = _aircraft_for(sortie.aircraft, evaluator.aircrafts, evaluator.reserve)
        sortie.code = f"Q23-{index + 1:03d}"
        sortie.prep_start_s = float(solver.value(starts[index]))
        sortie.prep_end_s = sortie.prep_start_s + aircraft.prep_s
        sortie.loading_end_s = sortie.prep_end_s + aircraft.load_each_s * len(sortie.boxes)
        sortie.takeoff_s = sortie.loading_end_s
        sortie.drone = next(drone.code for drone in drones
                            if (index, option_index, drone.code) in drone_choices
                            and solver.value(drone_choices[index, option_index, drone.code]))
        sortie.battery = next(battery.code for battery in batteries
                              if (index, option_index, battery.code) in battery_choices
                              and solver.value(battery_choices[index, option_index, battery.code]))
        current = sortie.takeoff_s
        sortie.deliveries = {}
        for leg in sortie.legs or []:
            current += leg["flight_s"]
            site = leg["to"]
            if site == "O01":
                continue
            site_boxes = [box for box in sortie.boxes if box.site == site]
            current += aircraft.handoff_base_s + aircraft.handoff_each_s * len(site_boxes)
            for box in site_boxes:
                sortie.deliveries[box.code] = current
        sortie.return_s = current
        scheduled.append(sortie)
    return scheduled, {
        "status": first_status,
        "time_grid_s": 1,
        "integer_makespan_s": first_makespan,
        "best_bound_s": first_bound,
        "fixed_grouping_optimal": first_status == "OPTIMAL",
    }
