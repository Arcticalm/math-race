"""Relative communication demands with conservative continuous certificates."""

from __future__ import annotations

import math
import hashlib
import json

import rasterio

from final_code.problem1.solver import Node
from final_code.problem3.physics import (
    LinkEvaluator, certify_moving_link, estimate_relay_mission, link_limits,
    load_relay_parameters, sampled_flight_leg,
)
from final_code.problem3.transport_relay import REFERENCE_RELAY_POSITIONS, _position, build_trajectory


def locations(evaluator, expanded=False):
    params = load_relay_parameters()
    limits = link_limits(evaluator.params)
    base = evaluator.base
    gateway = Node("G01", base.longitude, base.latitude, base.elevation_m + 20)
    points = set(REFERENCE_RELAY_POSITIONS.values())
    points.update((n.longitude, n.latitude) for n in evaluator.sites.values())
    if expanded:
        points.update((x + dx, y + dy) for x, y in list(points)
                      for dx, dy in ((0.005, 0), (-0.005, 0), (0, 0.005), (0, -0.005)))
    result = []
    heights = (params.maximum_agl_m,) if not expanded else (150., 250., params.maximum_agl_m)
    for longitude, latitude in sorted(points):
        row, col = rasterio.transform.rowcol(evaluator.dem.transform, longitude, latitude)
        if not (0 <= row < evaluator.dem.height and 0 <= col < evaluator.dem.width):
            continue
        ground = float(evaluator.dem_values[row, col])
        if not math.isfinite(ground) or ground == evaluator.dem.nodata or ground == -32767:
            continue
        node = Node("H", longitude, latitude, ground)
        try:
            outbound, distance = sampled_flight_leg(evaluator, base, node)
            returning, return_distance = sampled_flight_leg(evaluator, node, base)
        except ValueError:
            continue
        for height in sorted(set(heights)):
            if height > params.maximum_agl_m:
                continue
            altitude = ground + height
            if not certify_moving_link(evaluator, node, altitude, node, altitude,
                                       gateway, gateway.elevation_m, limits["relay_gateway_db"]):
                continue
            mission = estimate_relay_mission(0, distance, outbound, altitude,
                                             return_distance, returning, base.elevation_m, params)
            if not mission.feasible_energy:
                continue
            result.append({
                "longitude": longitude, "latitude": latitude, "ground_dsm_m": ground,
                "hover_altitude_m": altitude, "agl_m": height,
                "outbound_flight_s": mission.outbound_flight_s,
                "return_flight_s": mission.return_flight_s,
                "preflight_s": params.preparation_s + mission.outbound_flight_s + params.link_setup_s,
                "fixed_energy_kwh": mission.energy_kwh,
            })
    return result


def _prove(evaluator, phase, start, end, node, altitude, threshold):
    first, first_alt = _position(phase, start)
    last, last_alt = _position(phase, end)
    if certify_moving_link(evaluator, first, first_alt, last, last_alt, node, altitude, threshold):
        return True
    middle = (start + end) / 2
    point, point_alt = _position(phase, middle)
    if end - start <= 1.0 or not evaluator.evaluate(point, point_alt, node, altitude, threshold).available:
        return False
    return (_prove(evaluator, phase, start, middle, node, altitude, threshold)
            and _prove(evaluator, phase, middle, end, node, altitude, threshold))


def profile_key(pattern, candidate_locations, step=10.):
    locations_key = [(x["longitude"], x["latitude"], x["hover_altitude_m"])
                     for x in candidate_locations]
    payload = json.dumps([pattern.geometry_key, locations_key, step], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def build_profiles(pool, candidate_locations, cache=None, step=10.):
    """Cache geometry only: box IDs and payload do not change fixed-speed tracks.

    Each demand is a union of adjacent cells where a direct interval certificate
    failed. Relay eligibility proves the *whole* demand, including phase edges.
    A failure is an unproved candidate, not a proof of physical infeasibility.
    """
    cache = {} if cache is None else cache
    evaluator = LinkEvaluator()
    limits = link_limits(evaluator.params)
    base = evaluator.base
    gateway = Node("G01", base.longitude, base.latitude, base.elevation_m + 20)
    profiles = {}
    try:
        for index, pattern in enumerate(pool):
            key = profile_key(pattern, candidate_locations, step)
            if key not in cache:
                phases = build_trajectory([pattern.sortie])
                demands = []
                for phase in phases:
                    count = max(1, math.ceil((phase.end_s - phase.start_s) / step))
                    for i in range(count):
                        start = phase.start_s + (phase.end_s - phase.start_s) * i / count
                        end = phase.start_s + (phase.end_s - phase.start_s) * (i + 1) / count
                        if end <= start or _prove(evaluator, phase, start, end, gateway,
                                                 gateway.elevation_m, limits["transport_gateway_db"]):
                            continue
                        if demands and abs(demands[-1]["end"] - start) < 1e-7:
                            demands[-1]["end"] = end
                            demands[-1]["cells"].append((phase, start, end))
                        else:
                            demands.append({"start": start, "end": end,
                                            "cells": [(phase, start, end)]})
                result = []
                for demand in demands:
                    eligible = []
                    for loc_id, loc in enumerate(candidate_locations):
                        hover = Node("H", loc["longitude"], loc["latitude"], loc["ground_dsm_m"])
                        if all(_prove(evaluator, phase, a, b, hover, loc["hover_altitude_m"],
                                      limits["transport_relay_db"])
                               for phase, a, b in demand["cells"]):
                            eligible.append(loc_id)
                    result.append({"start": demand["start"], "end": demand["end"],
                                   "locations": eligible})
                cache[key] = result
                if len(cache) % 10 == 0:
                    print(f"Communication: {len(cache)} geometries certified ({index + 1}/{len(pool)} patterns)", flush=True)
            profiles[pattern.code] = cache[key]
    finally:
        evaluator.close()
    return profiles
