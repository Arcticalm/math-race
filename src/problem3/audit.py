"""Independent interval audits for the Problem 3 output contract."""

from __future__ import annotations

import math

from src.problem1.solver import Node
from src.problem3.physics import LinkEvaluator, certify_moving_link, link_limits


def _relay_at(selected, time_s):
    for mission in selected:
        if mission["service_start_s"] - 1e-7 <= time_s <= mission["service_end_s"] + 1e-7:
            return mission
    return None


def _mission_for_interval(selected, start_s, end_s):
    """Return the relay that covers a complete half-open time cell."""
    for mission in selected:
        if (mission["service_start_s"] - 1e-7 <= start_s
                and end_s <= mission["service_end_s"] + 1e-7):
            return mission
    return None


def _merge_rows(rows):
    merged = []
    for row in rows:
        if (merged and merged[-1]["运输架次编号"] == row["运输架次编号"]
                and merged[-1]["通信阶段"] == row["通信阶段"]
                and merged[-1]["保障方式"] == row["保障方式"]
                and merged[-1]["中继架次编号"] == row["中继架次编号"]
                and abs(merged[-1]["结束时刻（s）"] - row["开始时刻（s）"]) <= 1e-7):
            merged[-1]["结束时刻（s）"] = row["结束时刻（s）"]
        else:
            merged.append(row)
    return merged


def audit_communication(phases, selected, step_s=30.0, minimum_step_s=1.0):
    """Certify communication on every motion interval.

    A cell is accepted only when ``certify_moving_link`` proves the complete
    moving-link interval. Failed cells are recursively bisected until the
    minimum time scale, then reported as an outage unless a relay proves both
    access and backhaul for that same cell. This keeps the audit conservative
    instead of treating midpoint samples as continuous coverage.
    """
    if step_s <= 0 or minimum_step_s <= 0:
        raise ValueError("step_s and minimum_step_s must be positive")
    evaluator = LinkEvaluator()
    base = evaluator.base
    gateway = Node("G01", base.longitude, base.latitude, base.elevation_m + 20)
    threshold_direct = link_limits(evaluator.params)["transport_gateway_db"]
    threshold_access = link_limits(evaluator.params)["transport_relay_db"]
    threshold_backhaul = link_limits(evaluator.params)["relay_gateway_db"]
    rows = []
    gap_seconds = 0.0
    try:
        for phase in phases:
            if phase.end_s <= phase.start_s:
                continue
            from src.problem3.solver import _position

            # Relay service boundaries are event points and must never be
            # hidden inside a cell. The remaining cells are bounded by step_s.
            points = {phase.start_s, phase.end_s}
            points.update(item["service_start_s"] for item in selected
                          if phase.start_s < item["service_start_s"] < phase.end_s)
            points.update(item["service_end_s"] for item in selected
                          if phase.start_s < item["service_end_s"] < phase.end_s)
            ordered = sorted(points)

            def certify_cell(start, end):
                nonlocal gap_seconds
                first, first_altitude = _position(phase, start)
                last, last_altitude = _position(phase, end)
                direct = evaluator.evaluate(
                    _position(phase, (start + end) / 2)[0],
                    _position(phase, (start + end) / 2)[1], gateway,
                    gateway.elevation_m, threshold_direct)
                direct_ok = certify_moving_link(
                    evaluator, first, first_altitude, last, last_altitude,
                    gateway, gateway.elevation_m, threshold_direct)
                mission = _mission_for_interval(selected, start, end)
                relay_ok = False
                relay_code = ""
                if not direct_ok and mission is not None:
                    hover = Node("H", mission["longitude"], mission["latitude"], 0.0)
                    access_ok = certify_moving_link(
                        evaluator, first, first_altitude, last, last_altitude,
                        hover, mission["hover_altitude_m"], threshold_access)
                    backhaul_ok = certify_moving_link(
                        evaluator, hover, mission["hover_altitude_m"], hover,
                        mission["hover_altitude_m"], gateway, gateway.elevation_m,
                        threshold_backhaul)
                    relay_ok = access_ok and backhaul_ok
                    relay_code = mission.get("relay_sortie", "")
                if direct_ok:
                    mode = "直连"
                elif relay_ok:
                    mode = "中继"
                else:
                    mode = "中断"
                    gap_seconds += end - start
                rows.append({
                    "运输架次编号": phase.sortie,
                    "通信阶段": phase.name,
                    "开始时刻（s）": start,
                    "结束时刻（s）": end,
                    "保障方式": mode,
                    "中继架次编号": relay_code,
                    "直连路径损耗（dB）": direct.path_loss_db if direct.path_loss_db is not None else "",
                    "直连门限（dB）": direct.threshold_db,
                })

            def process(start, end):
                midpoint = (start + end) / 2
                mid_node, mid_altitude = _position(phase, midpoint)
                mid_direct = evaluator.evaluate(
                    mid_node, mid_altitude, gateway, gateway.elevation_m,
                    threshold_direct)
                mid_mission = _mission_for_interval(selected, start, end)
                mid_relay = False
                if not mid_direct.available and mid_mission is not None:
                    mid_hover = Node("H", mid_mission["longitude"],
                                     mid_mission["latitude"], 0.0)
                    mid_access = evaluator.evaluate(
                        mid_node, mid_altitude, mid_hover,
                        mid_mission["hover_altitude_m"], threshold_access)
                    mid_backhaul = evaluator.evaluate(
                        mid_hover, mid_mission["hover_altitude_m"], gateway,
                        gateway.elevation_m, threshold_backhaul)
                    mid_relay = mid_access.available and mid_backhaul.available
                # A midpoint outage is already a concrete outage. Avoid
                # spending thousands of subdivisions trying to certify a cell
                # whose representative state is unavailable.
                if not mid_direct.available and not mid_relay:
                    certify_cell(start, end)
                    return
                if end - start <= step_s + 1e-9:
                    # At the requested base resolution, the certificate itself
                    # decides whether the complete cell is safe. If it cannot
                    # prove it, bisect until the declared minimum scale.
                    first, first_altitude = _position(phase, start)
                    last, last_altitude = _position(phase, end)
                    direct_ok = certify_moving_link(
                        evaluator, first, first_altitude, last, last_altitude,
                        gateway, gateway.elevation_m, threshold_direct)
                    mission = _mission_for_interval(selected, start, end)
                    relay_ok = False
                    if not direct_ok and mission is not None:
                        hover = Node("H", mission["longitude"], mission["latitude"], 0.0)
                        relay_ok = (
                            certify_moving_link(evaluator, first, first_altitude,
                                                last, last_altitude, hover,
                                                mission["hover_altitude_m"], threshold_access)
                            and certify_moving_link(evaluator, hover,
                                                    mission["hover_altitude_m"], hover,
                                                    mission["hover_altitude_m"], gateway,
                                                    gateway.elevation_m, threshold_backhaul)
                        )
                    if (direct_ok or relay_ok or end - start <= minimum_step_s + 1e-9):
                        certify_cell(start, end)
                        return
                if midpoint <= start or midpoint >= end:
                    certify_cell(start, end)
                    return
                process(start, midpoint)
                process(midpoint, end)

            for start, end in zip(ordered, ordered[1:]):
                duration = end - start
                count = max(1, math.ceil(duration / step_s))
                for index in range(count):
                    cell_start = start + duration * index / count
                    cell_end = start + duration * (index + 1) / count
                    process(cell_start, cell_end)
    finally:
        evaluator.close()
    rows.sort(key=lambda row: (row["开始时刻（s）"], row["运输架次编号"], row["通信阶段"]))
    rows = _merge_rows(rows)
    uncovered = [row for row in rows if row["保障方式"] == "中断"]
    return rows, {
        "sample_step_s": step_s,
        "minimum_certification_step_s": minimum_step_s,
        "interval_count": len(rows),
        "uncovered_interval_count": len(uncovered),
        "communication_outage_s": gap_seconds,
        "certified": not uncovered,
        "method": "recursive interval certification with conservative swept-cell LOS bounds",
    }


def audit_relay_resources(selected):
    from src.problem3.physics import load_relay_parameters, estimate_relay_mission, sampled_flight_leg
    from src.problem3.solver import _charge_duration
    params = load_relay_parameters()
    occupancy, conflicts = {}, []
    evaluator = LinkEvaluator()
    try:
        for mission in selected:
            drone, component = mission.get("relay_drone"), mission.get("energy_component")
            if drone not in {"R01", "R02"} or component not in {f"RE-{i:02d}" for i in range(1, 7)}:
                conflicts.append({"reason": "unknown relay resource"})
            start = mission["preparation_start_s"]
            hover = Node("H", mission["longitude"], mission["latitude"], mission["ground_dsm_m"])
            terrain, distance = sampled_flight_leg(evaluator, evaluator.base, hover)
            back_terrain, back_distance = sampled_flight_leg(evaluator, hover, evaluator.base)
            estimate = estimate_relay_mission(mission["service_end_s"] - mission["service_start_s"],
                distance, terrain, mission["hover_altitude_m"], back_distance, back_terrain,
                evaluator.base.elevation_m, params)
            expected_start = mission["service_start_s"] - params.preparation_s - estimate.outbound_flight_s - params.link_setup_s
            expected_return = mission["service_end_s"] + estimate.return_flight_s
            if (start < -1e-7 or not estimate.feasible_energy
                    or abs(start - expected_start) > 1e-6
                    or abs(mission["return_o01_s"] - expected_return) > 1e-6
                    or abs(mission["energy_kwh"] - estimate.energy_kwh) > 1e-6
                    or abs(mission["return_soc_percent"] - estimate.return_soc_percent) > 1e-6):
                conflicts.append({"reason": "relay physics/timeline mismatch", "mission": mission.get("relay_sortie")})
            for resource, end in [(drone, expected_return + params.turnaround_s),
                                  (component, expected_return + _charge_duration(params.full_charge_s,
                                                                       estimate.return_soc_percent / 100))]:
                occupancy.setdefault(resource, []).append((start, end))
        for resource, intervals in occupancy.items():
            intervals.sort()
            for first, second in zip(intervals, intervals[1:]):
                if first[1] > second[0] + 1e-7:
                    conflicts.append({"resource": resource, "first": first, "second": second})
    finally:
        evaluator.close()
    return {"mission_count": len(selected), "resource_conflict_count": len(conflicts),
            "feasible": not conflicts, "conflicts": conflicts}


def audit_checkpoints(samples, intervals, selected):
    """Independently re-evaluate both hops at every covered trajectory checkpoint."""
    from src.problem3.solver import _communication_rows
    evaluator = LinkEvaluator()
    limits = link_limits(evaluator.params)
    base = evaluator.base
    gateway = Node("G01", base.longitude, base.latitude, base.elevation_m + 20)
    records, failures = [], []
    try:
        for point in samples:
            node = Node("transport", point["longitude"], point["latitude"], 0)
            altitude, time_s = point["altitude_m"], point["time_s"]
            direct = evaluator.evaluate(node, altitude, gateway, gateway.elevation_m,
                                        limits["transport_gateway_db"])
            covered = direct.available
            for mission in selected:
                if (point["sortie"] not in mission["covered_sorties"].split(",")
                        or not mission["service_start_s"] - 1e-7 <= time_s <= mission["service_end_s"] + 1e-7):
                    continue
                if not any(interval["sortie"] == point["sortie"]
                           and interval.get("gap_id") in mission["covered_gap_ids"]
                           and interval["start_s"] - 1e-7 <= time_s <= interval["end_s"] + 1e-7
                           for interval in intervals):
                    continue
                hover = Node("relay", mission["longitude"], mission["latitude"], mission["ground_dsm_m"])
                access = evaluator.evaluate(node, altitude, hover, mission["hover_altitude_m"],
                                            limits["transport_relay_db"])
                backhaul = evaluator.evaluate(hover, mission["hover_altitude_m"], gateway,
                                               gateway.elevation_m, limits["relay_gateway_db"])
                ok = access.available and backhaul.available
                covered |= ok
                records.append({"sortie": point["sortie"], "phase": point["phase"], "time_s": time_s,
                    "relay_sortie": mission["relay_sortie"], "access_loss_db": access.path_loss_db,
                    "access_limit_db": access.threshold_db, "access_available": access.available,
                    "backhaul_loss_db": backhaul.path_loss_db, "backhaul_limit_db": backhaul.threshold_db,
                    "backhaul_available": backhaul.available, "both_available": ok})
            if not covered:
                failures.append({"sortie": point["sortie"], "phase": point["phase"], "time_s": time_s})
    finally:
        evaluator.close()
    rows = _communication_rows([], intervals, selected)
    for row in rows:
        if row["保障方式"] == "中继候选":
            row["保障方式"] = "中继"
        if any(p["sortie"] == row["运输架次编号"] and p["phase"] == row["通信阶段"]
               and row["开始时刻（s）"] - 1e-7 <= p["time_s"] <= row["结束时刻（s）"] + 1e-7
               for p in failures):
            row["保障方式"] = "中断"
    return rows, {"certified": not failures and all(r["both_available"] for r in records),
                  "checkpoint_count": len(samples), "two_hop_check_count": len(records),
                  "two_hop_failure_count": sum(not r["both_available"] for r in records),
                  "uncovered_checkpoint_count": len(failures), "failures": failures,
                  "method": "independent checkpoint replay; not continuous interval certification"}, records
