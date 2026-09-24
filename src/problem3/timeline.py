"""Replay the saved Q23 schedule and delay transports to resolve relay conflicts."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from src.problem21.solver import (
    RouteEvaluator, _schedule_deliveries, _validate, _hard_deadlines,
    load_resources, load_task_boxes, _charge_duration,
)
from src.problem3.physics import load_relay_parameters


def load_problem23_schedule(directory: Path):
    from src.problem3.solver import _read_csv, _shift_sortie

    summary = json.loads((directory / "problem23_summary.json").read_text(encoding="utf-8"))
    if not summary.get("feasible") or summary.get("strategy") != "constructive_merged/cp_sat":
        raise ValueError("Q2 input must be the audited constructive_merged/cp_sat output")
    rows = _read_csv(directory / "sorties_audit.csv")
    deliveries = _read_csv(directory / "box_delivery_audit.csv")
    boxes = load_task_boxes()
    by_code = {box.code: box for box in boxes}
    groups = {}
    for row in deliveries:
        groups.setdefault(row["架次编号"], []).append(by_code[row["货箱编号"]])
    sorties = []
    evaluator = RouteEvaluator(0.2, 1.0)
    try:
        for row in rows:
            code = row["架次编号"]
            aircraft = row["机型编号"]
            sortie = evaluator.evaluate(groups[code], row["访问服务区顺序"].split("→"), aircraft)
            if sortie is None:
                raise ValueError(f"Invalid Q23 route: {code}")
            sortie.code, sortie.drone, sortie.battery = code, row["无人机编号"], row["电池编号"]
            model = evaluator.aircrafts[aircraft]
            sortie.prep_end_s = model.prep_s
            sortie.takeoff_s = sortie.loading_end_s = model.prep_s + model.load_each_s * len(sortie.boxes)
            _schedule_deliveries(sortie, model)
            sortie.return_s = sortie.takeoff_s + sortie.flight_s + sum(
                model.handoff_base_s + model.handoff_each_s * sum(b.site == site for b in sortie.boxes)
                for site in sortie.route)
            _shift_sortie(sortie, float(row["准备开始时刻（s）"]))
            for field, actual in [("返回O01时刻（s）", sortie.return_s),
                                  ("装载完成/起飞时刻（s）", sortie.takeoff_s),
                                  ("架次能耗（kWh）", sortie.energy_kwh),
                                  ("返航SOC（%）", sortie.battery_soc_return_percent)]:
                if abs(float(row[field]) - actual) > 1e-6:
                    raise ValueError(f"Stale Q23 physics/timeline: {code}/{field}; use clearance50 output")
            sorties.append(sortie)
        if len({s.code for s in sorties}) != len(sorties):
            raise ValueError("Duplicate Q23 sortie IDs")
        actual_delivery = {(s.code, b): t for s in sorties for b, t in s.deliveries.items()}
        for row in deliveries:
            if abs(actual_delivery[row["架次编号"], row["货箱编号"]] - float(row["交付完成时刻（s）"])) > 1e-6:
                raise ValueError("Q23 delivery timeline does not match reconstructed physics")
        drones, batteries = load_resources()
        validation = _validate(sorties, boxes, drones, batteries, evaluator)
        if not validation["feasible"]:
            raise ValueError(f"Invalid Q23 input: {validation}")
        return sorties, boxes, {**summary, "source": str(directory)}
    finally:
        evaluator.close()


def solve_delays(sorties, groups, gap_count, time_limit_s=60.0, maximum_delay_s=10800,
                 objective="sorties", max_relay_sorties=None):
    """Jointly delay transports and form overlapping service windows at fixed points.

    Millisecond interval bounds are rounded outwards. Transport delays are
    nonnegative integer milliseconds; exact floating-point physics is replayed.
    """
    from ortools.sat.python import cp_model
    from src.problem3.solver import _shift_sortie

    model = cp_model.CpModel()
    scale = 1000
    floor = lambda x: math.floor(x * scale + 1e-6)
    ceil = lambda x: math.ceil(x * scale - 1e-6)
    horizon = ceil(max(s.return_s for s in sorties) + maximum_delay_s + 20000)
    delays = {}
    aircraft_intervals, battery_intervals = {}, {}
    _, batteries = load_resources()
    battery_by_id = {b.code: b for b in batteries}
    for sortie in sorties:
        slack = min([maximum_delay_s] + [deadline - sortie.deliveries[box.code]
                    for box in sortie.boxes for _, deadline in _hard_deadlines(box)])
        if slack < -1e-7:
            return None, {"status": "transport hard deadline already violated"}
        delay = delays[sortie.code] = model.new_int_var(0, max(0, floor(slack)), "delay_" + sortie.code)
        start = floor(sortie.prep_start_s) + delay
        end = ceil(sortie.return_s) + delay
        aircraft_intervals.setdefault(sortie.drone, []).append(model.new_interval_var(
            start, ceil(sortie.return_s) - floor(sortie.prep_start_s), end, "air_" + sortie.code))
        battery_end = ceil(sortie.return_s + _charge_duration(
            battery_by_id[sortie.battery].full_charge_s, sortie.battery_soc_return_percent / 100))
        battery_intervals.setdefault(sortie.battery, []).append(model.new_interval_var(
            start, battery_end - floor(sortie.prep_start_s), battery_end + delay, "bat_" + sortie.code))
    for intervals in [*aircraft_intervals.values(), *battery_intervals.values()]:
        model.add_no_overlap(intervals)
    params = load_relay_parameters()
    options = [c for group in groups for c in group["candidates"]]
    coverage = {i: [] for i in range(1, gap_count + 1)}
    relay_air, relay_battery, chosen = [], [], []
    gaps = {g["gap_id"]: g for group in groups for g in group.get("gaps", [])}
    # A point can serve multiple originally disjoint demands after transport
    # delays bring their absolute intervals into overlap. Do not require all
    # covered transports to receive the same delay.
    locations = {}
    for candidate in options:
        key = (candidate["longitude"], candidate["latitude"], candidate["hover_altitude_m"])
        entry = locations.setdefault(key, {"candidate": candidate, "ids": set()})
        entry["ids"].update(candidate["covered_gap_ids"])
    for location_index, entry in enumerate(locations.values()):
        candidate = entry["candidate"]
        ids = sorted(entry["ids"])
        preflight = candidate["service_start_s"] - candidate["preparation_start_s"]
        return_flight = candidate["return_o01_s"] - candidate["service_end_s"]
        hover_kw = params.hover_power_kw + params.communication_power_kw
        fixed_energy = candidate["energy_kwh"] - hover_kw * (
            candidate["service_end_s"] - candidate["service_start_s"]) / 3600
        maximum_service = (params.usable_energy_kwh * (1 - params.reserve_fraction) - fixed_energy) * 3600 / hover_kw
        if maximum_service <= 0:
            continue
        for anchor_index, anchor in enumerate(ids):
            name = f"{location_index}_{anchor}"
            use = model.new_bool_var("use_" + name)
            chosen.append(use)
            service_start = model.new_int_var(ceil(preflight), horizon, "service_start_" + name)
            service_end = model.new_int_var(ceil(preflight), horizon, "service_end_" + name)
            model.add(service_end >= service_start)
            model.add(service_end - service_start <= floor(maximum_service))
            assignments = {}
            for gap_id in ids[anchor_index:]:
                assigned = use if gap_id == anchor else model.new_bool_var(f"assign_{name}_{gap_id}")
                if gap_id != anchor:
                    model.add(assigned <= use)
                assignments[gap_id] = assigned
                gap = gaps[gap_id]
                begin = floor(gap["start_s"]) + delays[gap["sortie"]]
                end = ceil(gap["end_s"]) + delays[gap["sortie"]]
                model.add(service_start <= begin).only_enforce_if(assigned)
                model.add(service_end >= end).only_enforce_if(assigned)
                coverage[gap_id].append(assigned)
            # A connected chain of overlapping demands can bridge disjoint
            # gaps of one sortie. Requiring a common instant for the entire
            # window would incorrectly exclude such valid merged missions.
            for gap_id, assigned in assignments.items():
                if gap_id == anchor:
                    continue
                gap = gaps[gap_id]
                predecessors = []
                for previous_id, previous_assigned in assignments.items():
                    if previous_id >= gap_id:
                        continue
                    previous = gaps[previous_id]
                    if (previous["sortie"] == gap["sortie"]
                            and previous["end_s"] <= gap["start_s"]):
                        continue
                    edge = model.new_bool_var(f"overlap_{name}_{previous_id}_{gap_id}")
                    model.add(edge <= assigned)
                    model.add(edge <= previous_assigned)
                    previous_start = ceil(previous["start_s"]) + delays[previous["sortie"]]
                    previous_end = floor(previous["end_s"]) + delays[previous["sortie"]]
                    current_start = ceil(gap["start_s"]) + delays[gap["sortie"]]
                    model.add(current_start >= previous_start).only_enforce_if(edge)
                    model.add(current_start + 1 <= previous_end).only_enforce_if(edge)
                    predecessors.append(edge)
                model.add(sum(predecessors) >= assigned)
            start = service_start - ceil(preflight)
            # Charge at reserve SOC bounds the piecewise charge curve from above.
            # Exact SOC and recharge completion are recomputed after time replay.
            for extra, target in [
                (return_flight + params.turnaround_s, relay_air),
                (return_flight + _charge_duration(params.full_charge_s, params.reserve_fraction), relay_battery),
            ]:
                duration = model.new_int_var(0, horizon, "duration_" + name + str(len(target)))
                end = service_end + ceil(extra)
                model.add(duration == end - start)
                target.append(model.new_optional_interval_var(start, duration, end, use,
                                                             "mission_" + name + str(len(target))))
    missing = [gap for gap, choices in coverage.items() if not choices]
    if missing:
        return None, {"status": "no spatial/energy candidate", "impossible_gap_ids": missing}
    for choices in coverage.values():
        model.add(sum(choices) >= 1)
    model.add_cumulative(relay_air, [1] * len(relay_air), 2)
    model.add_cumulative(relay_battery, [1] * len(relay_battery), params.battery_count)
    makespan = model.new_int_var(0, horizon, "makespan")
    for sortie in sorties:
        model.add(makespan >= ceil(sortie.return_s) + delays[sortie.code])
    if max_relay_sorties is not None:
        model.add(sum(chosen) <= max_relay_sorties)
    secondary = sum(delays.values()) + makespan
    count_weight = len(sorties) * ceil(maximum_delay_s) + horizon + 1
    if objective == "sorties":
        model.minimize(count_weight * sum(chosen) + secondary)
    elif objective == "delay":
        model.minimize(secondary + sum(chosen))
    else:
        raise ValueError("objective must be sorties or delay")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 11
    status = solver.solve(model)
    info = {"status": solver.status_name(status), "candidate_count": len(options),
            "objective": objective, "max_relay_sorties": max_relay_sorties}
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, info
    info["relay_sortie_count"] = sum(solver.value(use) for use in chosen)
    info["objective_bound"] = solver.best_objective_bound
    shifted = copy.deepcopy(sorties)
    info["delays_s"] = {code: solver.value(delay) / scale for code, delay in delays.items()}
    for sortie in shifted:
        _shift_sortie(sortie, info["delays_s"][sortie.code])
    return shifted, info


def coordinate_timeline(initial, sample_step_s, candidate_step_s, max_iterations=12, time_limit_s=60,
                        objective="sorties", max_relay_sorties=None, maximum_delay_s=10800,
                        relay_objective="energy"):
    from src.problem3.solver import (
        build_trajectory, screen_direct_links, _merge_gap_intervals, _assign_gap_ids,
        search_relay_candidates, select_relay_schedule,
    )
    sorties = copy.deepcopy(initial)
    history = []
    for iteration in range(max_iterations):
        print(f"Q3 iteration {iteration + 1}: reconstructing trajectories and links", flush=True)
        phases = build_trajectory(sorties)
        samples, intervals = screen_direct_links(sorties, phases, sample_step_s)
        gaps = _merge_gap_intervals(intervals)
        _assign_gap_ids(intervals, gaps)
        groups = search_relay_candidates(sorties, phases, gaps, candidate_step_s,
                                         checkpoints=samples, allow_early_departure=True)
        print(f"Q3: {len(gaps)} demands, {sum(g['candidate_count'] for g in groups)} candidates", flush=True)
        schedule = select_relay_schedule(groups, len(gaps),
            objective="sorties" if objective == "sorties" else relay_objective,
            max_relay_sorties=max_relay_sorties)
        history.append({"iteration": iteration + 1, "gap_count": len(gaps),
                        "fixed_schedule_feasible": schedule["feasible_cover"]})
        result = dict(sorties=sorties, phases=phases, samples=samples, intervals=intervals,
                      gaps=gaps, groups=groups, selected=schedule["selected"], schedule=schedule,
                      history=history)
        if schedule["feasible_cover"]:
            break
        if iteration + 1 == max_iterations:
            history[-1]["stop_reason"] = "iteration limit"
            break
        shifted, info = solve_delays(sorties, groups, len(gaps), time_limit_s,
                                    maximum_delay_s=maximum_delay_s,
                                    objective=objective, max_relay_sorties=max_relay_sorties)
        history[-1]["delay_solver"] = info
        if shifted is None:
            history[-1]["stop_reason"] = info["status"]
            break
        if max(info["delays_s"].values(), default=0) <= 1e-7:
            history[-1]["stop_reason"] = "no progress"
            break
        sorties = shifted
    original = {s.code: s.prep_start_s for s in initial}
    result["coordination"] = {
        "method": "replay, cover, CP-SAT transport delay feedback, repeat",
        "feasible": result["schedule"]["feasible_cover"],
        "iterations": len(history), "history": history,
        "transport_delays_s": {s.code: s.prep_start_s - original[s.code] for s in result["sorties"]},
    }
    return result


def overlapping_windows(covered):
    """Keep singleton options and connected overlap windows at a common point."""
    windows = {(gap["gap_id"],): [gap] for gap in covered}
    for start in sorted({gap["start_s"] for gap in covered}):
        for end in sorted({gap["end_s"] for gap in covered}):
            subset = sorted((gap for gap in covered if gap["start_s"] >= start - 1e-7
                             and gap["end_s"] <= end + 1e-7), key=lambda gap: gap["start_s"])
            if not subset:
                continue
            right = subset[0]["end_s"]
            for gap in subset[1:]:
                if gap["start_s"] >= right - 1e-7:
                    break
                right = max(right, gap["end_s"])
            else:
                windows[tuple(sorted(gap["gap_id"] for gap in subset))] = subset
    return list(windows.values())
