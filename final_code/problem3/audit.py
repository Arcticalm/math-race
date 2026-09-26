"""Independent interval audits for the Problem 3 output contract."""

from __future__ import annotations

import math

from final_code.problem1.solver import Node
from final_code.problem3.physics import LinkEvaluator, certify_moving_link, link_limits


def _missions_for_interval(selected, start_s, end_s, sortie=None):
    """All assigned relay options covering a complete closed time cell."""
    return [mission for mission in selected
            if (sortie is None or sortie in mission.get("covered_sorties", "").split(","))
            and mission["service_start_s"] - 1e-7 <= start_s
            and end_s <= mission["service_end_s"] + 1e-7]


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
    gateway = Node("G01", base.longitude, base.latitude, base.elevation_m + evaluator.params.gateway_agl_m)
    threshold_direct = link_limits(evaluator.params)["transport_gateway_db"]
    threshold_access = link_limits(evaluator.params)["transport_relay_db"]
    threshold_backhaul = link_limits(evaluator.params)["relay_gateway_db"]
    rows = []
    gap_seconds = 0.0
    try:
        for phase in phases:
            if phase.end_s <= phase.start_s:
                continue
            from final_code.problem3.trajectory import _position

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
                relay_ok = False
                relay_code = ""
                for mission in ([] if direct_ok else _missions_for_interval(selected, start, end, phase.sortie)):
                    hover = Node("H", mission["longitude"], mission["latitude"], 0.0)
                    access_ok = certify_moving_link(
                        evaluator, first, first_altitude, last, last_altitude,
                        hover, mission["hover_altitude_m"], threshold_access)
                    backhaul_ok = certify_moving_link(
                        evaluator, hover, mission["hover_altitude_m"], hover,
                        mission["hover_altitude_m"], gateway, gateway.elevation_m,
                        threshold_backhaul)
                    relay_ok = access_ok and backhaul_ok
                    if relay_ok:
                        relay_code = mission.get("relay_sortie", "")
                        break
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
                mid_relay = False
                for mid_mission in ([] if mid_direct.available else _missions_for_interval(selected, start, end, phase.sortie)):
                    mid_hover = Node("H", mid_mission["longitude"],
                                     mid_mission["latitude"], 0.0)
                    mid_access = evaluator.evaluate(
                        mid_node, mid_altitude, mid_hover,
                        mid_mission["hover_altitude_m"], threshold_access)
                    mid_backhaul = evaluator.evaluate(
                        mid_hover, mid_mission["hover_altitude_m"], gateway,
                        gateway.elevation_m, threshold_backhaul)
                    mid_relay = mid_access.available and mid_backhaul.available
                    if mid_relay:
                        break
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
                    relay_ok = False
                    for mission in ([] if direct_ok else _missions_for_interval(selected, start, end, phase.sortie)):
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
                        if relay_ok:
                            break
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
        "audit_version": "exact_dem_interval_v2",
        "sample_step_s": step_s,
        "minimum_certification_step_s": minimum_step_s,
        "interval_count": len(rows),
        "uncovered_interval_count": len(uncovered),
        "communication_outage_s": gap_seconds,
        "uncertified_interval_s": gap_seconds,
        "communication_outage_is_upper_bound": True,
        "certified": not uncovered,
        "method": "recursive continuous interval certificate over complete swept LOS slabs and every touched DEM pixel",
    }


def rebuild_relay_mission(mission, evaluator):
    """Recompute relay physics while preserving its hover point and service window.

    This is a proposed repaired record, not an audit approval. Call
    ``audit_relay_resources`` on the complete repaired fleet before using it.
    """
    import rasterio
    from final_code.problem3.physics import load_relay_parameters, estimate_relay_mission, sampled_flight_leg
    from final_code.problem2.transport import _charge_duration
    params = load_relay_parameters()
    longitude, latitude = mission["longitude"], mission["latitude"]
    row, col = rasterio.transform.rowcol(evaluator.dem.transform, longitude, latitude)
    if not (0 <= row < evaluator.dem.height and 0 <= col < evaluator.dem.width):
        raise ValueError("relay hover point outside DEM")
    ground = float(evaluator.dem_values[row, col])
    if (not math.isfinite(ground) or ground == -32767
            or evaluator.dem.nodata is not None and ground == evaluator.dem.nodata):
        raise ValueError("relay hover point lies on DEM NoData")
    altitude = float(mission["hover_altitude_m"])
    agl = altitude - ground
    if not math.isfinite(altitude) or not 0 <= agl <= params.maximum_agl_m + 1e-7:
        raise ValueError("relay hover AGL violates ground/maximum limit")
    service_start = float(mission["service_start_s"])
    service_end = float(mission["service_end_s"])
    if not all(math.isfinite(t) for t in (service_start, service_end)) or service_end < service_start:
        raise ValueError("invalid relay service window")
    hover = Node("H", longitude, latitude, ground)
    terrain, distance = sampled_flight_leg(evaluator, evaluator.base, hover)
    back_terrain, back_distance = sampled_flight_leg(evaluator, hover, evaluator.base)
    estimate = estimate_relay_mission(service_end - service_start, distance, terrain,
        altitude, back_distance, back_terrain, evaluator.base.elevation_m, params)
    preparation = service_start - params.preparation_s - estimate.outbound_flight_s - params.link_setup_s
    returned = service_end + estimate.return_flight_s
    return {**mission, "ground_dsm_m": ground, "agl_m": agl,
        "preparation_start_s": preparation, "takeoff_s": preparation + params.preparation_s,
        "arrival_s": service_start - params.link_setup_s,
        "outbound_flight_s": estimate.outbound_flight_s,
        "return_flight_s": estimate.return_flight_s,
        "preflight_s": params.preparation_s + estimate.outbound_flight_s + params.link_setup_s,
        "fixed_energy_kwh": estimate.energy_kwh - (params.hover_power_kw + params.communication_power_kw)
                            * (service_end - service_start) / 3600,
        "return_o01_s": returned, "energy_kwh": estimate.energy_kwh,
        "return_soc_percent": estimate.return_soc_percent,
        "drone_ready_s": returned + params.turnaround_s,
        "charge_complete_s": returned + _charge_duration(params.full_charge_s,
                                                          estimate.return_soc_percent / 100)}


def load_saved_q3(directory):
    """Read the frozen exported trajectories and relay records without optimization."""
    import ast
    import csv
    from pathlib import Path
    from final_code.problem3.trajectory import TrackPhase
    directory = Path(directory)
    with (directory / "trajectory_phases.csv").open(encoding="utf-8-sig") as source:
        phases = []
        for row in csv.DictReader(source):
            for key in ("start_s", "end_s", "start_altitude_m", "end_altitude_m"):
                row[key] = float(row[key])
            for key in ("start_node", "end_node"):
                row[key] = Node(**ast.literal_eval(row[key]))
            phases.append(TrackPhase(**row))
    with (directory / "relay_schedule.csv").open(encoding="utf-8-sig") as source:
        selected = []
        for row in csv.DictReader(source):
            for key, value in list(row.items()):
                if key in ("covered_gap_ids", "pattern_gaps"):
                    row[key] = ast.literal_eval(value)
                elif key not in ("relay_sortie", "covered_sorties", "relay_drone", "energy_component"):
                    row[key] = float(value)
            selected.append(row)
    return phases, selected


def audit_relay_resources(selected):
    from final_code.problem1.solver import BASE_DATA
    from final_code.problem2.transport import _rows
    from final_code.problem3.physics import load_relay_parameters
    params = load_relay_parameters()
    known_drones = {str(row[0]) for row in _rows(BASE_DATA / "中继无人机数据.xlsx")
                    if len(row) > 2 and row[1] == params.code and row[2] == "O01"}
    known_components = {f"RE-{i:02d}" for i in range(1, params.battery_count + 1)}
    occupancy, conflicts = {}, []
    evaluator = LinkEvaluator()
    seen = set()
    try:
        for mission in selected:
            code = mission.get("relay_sortie")
            if not code or code in seen:
                conflicts.append({"reason": "missing/duplicate relay sortie identifier", "mission": code})
            seen.add(code)
            drone, component = mission.get("relay_drone"), mission.get("energy_component")
            if drone not in known_drones or component not in known_components:
                conflicts.append({"reason": "unknown relay resource", "mission": code})
            try:
                expected = rebuild_relay_mission(mission, evaluator)
            except (ValueError, KeyError, TypeError, OverflowError) as error:
                conflicts.append({"reason": str(error), "mission": code})
                continue
            if (expected["preparation_start_s"] < -1e-7
                    or expected["return_soc_percent"] < 100 * params.reserve_fraction - 1e-7):
                conflicts.append({"reason": "negative preparation time or insufficient reserve", "mission": code})
            required = ("ground_dsm_m", "preparation_start_s", "return_o01_s", "energy_kwh", "return_soc_percent")
            optional = ("agl_m", "takeoff_s", "arrival_s", "drone_ready_s", "charge_complete_s",
                        "outbound_flight_s", "return_flight_s", "preflight_s", "fixed_energy_kwh")
            for field in required + tuple(field for field in optional if field in mission):
                value = mission.get(field)
                if (not isinstance(value, (int, float)) or not math.isfinite(value)
                        or abs(value - expected[field]) > 1e-6):
                    conflicts.append({"reason": "relay physics/timeline mismatch", "mission": code,
                                      "field": field, "recorded": value, "expected": expected[field]})
            for resource, end in ((drone, expected["drone_ready_s"]),
                                  (component, expected["charge_complete_s"])):
                occupancy.setdefault(resource, []).append((expected["preparation_start_s"], end))
        for resource, intervals in occupancy.items():
            intervals.sort()
            for first, second in zip(intervals, intervals[1:]):
                if first[1] > second[0] + 1e-7:
                    conflicts.append({"resource": resource, "first": first, "second": second})
    finally:
        evaluator.close()
    return {"audit_version": "exact_dem_interval_v2", "mission_count": len(selected),
            "resource_conflict_count": len(conflicts), "feasible": not conflicts, "conflicts": conflicts}
