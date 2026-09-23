from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import rasterio
from openpyxl import load_workbook
from rasterio.transform import rowcol


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
BASE_DATA = DATA / "无人机应急物资运输基础数据"
DEM_PATH = (
    DATA
    / "镇龙乡地理空间数据"
    / "镇龙乡及周边地理数据"
    / "数字高程模型数据（DEM）"
    / "镇龙乡及周边30米DEM.tif"
)


@dataclass(frozen=True)
class Aircraft:
    code: str
    name: str
    empty_mass_kg: float
    max_payload_kg: float
    volume_m3: float
    cruise_speed_mps: float
    empty_range_m: float
    full_range_m: float
    usable_energy_kwh: float
    reserve_fraction: float
    prep_s: float
    load_each_s: float
    handoff_base_s: float
    handoff_each_s: float
    climb_speed_mps: float
    descent_speed_mps: float
    climb_efficiency: float
    descent_efficiency: float


@dataclass(frozen=True)
class Node:
    code: str
    longitude: float
    latitude: float
    elevation_m: float


@dataclass(frozen=True)
class Box:
    code: str
    site: str
    item_type: str
    mass_kg: float
    volume_m3: float


@dataclass(frozen=True)
class Flight:
    energy_kwh: float
    time_s: float
    outbound_energy_kwh: float
    return_energy_kwh: float
    outbound_time_s: float
    return_time_s: float
    range_budget_m: float
    return_range_budget_m: float
    horizontal_distance_m: float
    cruise_altitude_m: float


@dataclass(frozen=True)
class Candidate:
    site: str
    aircraft: str
    boxes: tuple[str, ...]
    mass_kg: float
    volume_m3: float
    energy_kwh: float
    flight_time_s: float
    work_time_s: float
    range_budget_m: float
    return_range_budget_m: float
    reserve_kwh: float


def _rows(path: Path, sheet: str | None = None) -> list[tuple]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    worksheet = workbook[sheet] if sheet else workbook.active
    return [tuple(row) for row in worksheet.iter_rows(values_only=True)]


def load_aircraft() -> dict[str, Aircraft]:
    rows = _rows(BASE_DATA / "运输无人机数据.xlsx")
    result = {}
    for row in rows:
        if row[0] in {"A", "B", "C"} and isinstance(row[3], (int, float)):
            result[row[0]] = Aircraft(
                code=row[0], name=row[1], empty_mass_kg=float(row[2]),
                max_payload_kg=float(row[3]), volume_m3=float(row[4]),
                cruise_speed_mps=float(row[5]), empty_range_m=float(row[6]),
                full_range_m=float(row[7]), usable_energy_kwh=float(row[8]),
                reserve_fraction=float(row[9]) / 100, prep_s=float(row[10]),
                load_each_s=float(row[11]), handoff_base_s=float(row[12]),
                handoff_each_s=float(row[13]), climb_speed_mps=float(row[14]),
                descent_speed_mps=float(row[15]), climb_efficiency=float(row[16]),
                descent_efficiency=float(row[17]),
            )
    if len(result) != 3:
        raise ValueError(f"Expected three aircraft types, got {sorted(result)}")
    return result


def load_nodes() -> tuple[Node, dict[str, Node]]:
    rows = _rows(BASE_DATA / "调度中心与服务区.xlsx")
    node_rows = [row for row in rows if row and row[0] == "O01"]
    sites = [row for row in rows if row and isinstance(row[0], str) and row[0].startswith("S")]
    if len(node_rows) != 1 or len(sites) != 15:
        raise ValueError(f"Expected O01 and 15 service areas; got {len(node_rows)}, {len(sites)}")

    def convert(row: tuple) -> Node:
        return Node(row[0], float(row[2]), float(row[3]), float(row[4]))

    return convert(node_rows[0]), {row[0]: convert(row) for row in sites}


def load_boxes() -> dict[str, list[Box]]:
    rows = _rows(BASE_DATA / "物资需求与配送时限.xlsx", "逐箱货箱清单")
    result: dict[str, list[Box]] = {}
    seen: set[str] = set()
    for row in rows[1:]:
        if not row[0]:
            continue
        code = str(row[0])
        if code in seen:
            raise ValueError(f"Duplicate box identifier: {code}")
        seen.add(code)
        box = Box(code, str(row[1]), str(row[2]), float(row[3]), float(row[4]))
        result.setdefault(box.site, []).append(box)
    if len(seen) != 80 or len(result) != 15:
        raise ValueError(f"Expected 80 boxes across 15 sites; got {len(seen)} and {len(result)}")
    return result


def great_circle_distance_m(start: Node, end: Node) -> float:
    radius_m = 6_371_008.8
    lat1, lat2 = math.radians(start.latitude), math.radians(end.latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(end.longitude - start.longitude)
    term = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 2 * radius_m * math.asin(math.sqrt(term))


def sample_leg(dem: rasterio.io.DatasetReader, start: Node, end: Node) -> tuple[float, float]:
    """Return maximum sampled DEM elevation and great-circle horizontal distance."""
    distance = great_circle_distance_m(start, end)
    intervals = max(1, math.ceil(distance / 30))
    elevations = []
    for index in range(intervals + 1):
        fraction = index / intervals
        longitude = start.longitude + fraction * (end.longitude - start.longitude)
        latitude = start.latitude + fraction * (end.latitude - start.latitude)
        row, col = rowcol(dem.transform, longitude, latitude)
        if not (0 <= row < dem.height and 0 <= col < dem.width):
            raise ValueError(f"Route {start.code}-{end.code} leaves DEM extent")
        value = float(dem.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])
        if dem.nodata is not None and math.isclose(value, dem.nodata):
            raise ValueError(f"Route {start.code}-{end.code} crosses DEM NoData")
        elevations.append(value)
    return max(elevations), distance


def load_energy_per_meter(aircrafts: dict[str, Aircraft]) -> dict[str, float]:
    """Calibrate cruise energy per meter from the supplied standard ranges.

    The statement does not prescribe a numerical horizontal-energy function.
    This explicitly documented baseline treats usable battery energy divided by
    standard range as the average horizontal energy rate.
    """
    return {
        code: aircraft.usable_energy_kwh / aircraft.empty_range_m
        for code, aircraft in aircrafts.items()
    }


def leg_flight(
    aircraft: Aircraft,
    energy_per_meter: float,
    distance_m: float,
    cruise_altitude_m: float,
    start_altitude_m: float,
    end_altitude_m: float,
    payload_kg: float,
    mass_override_kg: float | None = None,
) -> tuple[float, float, float]:
    climb_m = max(0.0, cruise_altitude_m - start_altitude_m)
    descent_m = max(0.0, cruise_altitude_m - end_altitude_m)
    flight_time_s = (
        climb_m / aircraft.climb_speed_mps
        + distance_m / aircraft.cruise_speed_mps
        + descent_m / aircraft.descent_speed_mps
    )
    payload_ratio = payload_kg / aircraft.max_payload_kg
    range_m = aircraft.empty_range_m - (aircraft.empty_range_m - aircraft.full_range_m) * payload_ratio**1.5
    horizontal_energy_kwh = energy_per_meter * distance_m * aircraft.empty_range_m / range_m
    flight_mass_kg = mass_override_kg if mass_override_kg is not None else aircraft.empty_mass_kg + payload_kg
    climb_energy_kwh = (
        flight_mass_kg * 9.80665 * climb_m
        / (3_600_000 * aircraft.climb_efficiency)
    )
    descent_energy_kwh = 0.0
    if aircraft.descent_efficiency > 0:
        descent_energy_kwh = (
            flight_mass_kg * 9.80665 * descent_m
            / (3_600_000 * aircraft.descent_efficiency)
        )
    return flight_time_s, horizontal_energy_kwh + climb_energy_kwh + descent_energy_kwh, range_m


def flight_for_payload(
    aircraft: Aircraft,
    energy_per_meter: float,
    base: Node,
    site: Node,
    maximum_ground_elevation: float,
    payload_kg: float,
) -> Flight:
    cruise_altitude = maximum_ground_elevation + 50
    base_altitude = base.elevation_m
    site_altitude = site.elevation_m + 30
    outbound_time, outbound_energy, range_m = leg_flight(
        aircraft, energy_per_meter, great_circle_distance_m(base, site),
        cruise_altitude, base_altitude, site_altitude, payload_kg,
    )
    return_time, return_energy, _ = leg_flight(
        aircraft, energy_per_meter, great_circle_distance_m(site, base),
        cruise_altitude, site_altitude, base_altitude, 0.0, aircraft.empty_mass_kg,
    )
    horizontal_round_trip = 2 * great_circle_distance_m(base, site)
    return Flight(
        energy_kwh=outbound_energy + return_energy,
        time_s=outbound_time + return_time,
        outbound_energy_kwh=outbound_energy,
        return_energy_kwh=return_energy,
        outbound_time_s=outbound_time,
        return_time_s=return_time,
        range_budget_m=range_m,
        return_range_budget_m=aircraft.empty_range_m,
        horizontal_distance_m=horizontal_round_trip,
        cruise_altitude_m=cruise_altitude,
    )


def max_safe_payload(
    aircraft: Aircraft,
    energy_per_meter: float,
    base: Node,
    site: Node,
    maximum_ground_elevation: float,
) -> tuple[float, Flight]:
    low, high = 0.0, aircraft.max_payload_kg
    best = flight_for_payload(aircraft, energy_per_meter, base, site, maximum_ground_elevation, low)
    if best.energy_kwh > aircraft.usable_energy_kwh * (1 - aircraft.reserve_fraction):
        return 0.0, best
    for _ in range(60):
        middle = (low + high) / 2
        flight = flight_for_payload(aircraft, energy_per_meter, base, site, maximum_ground_elevation, middle)
        one_way_distance = flight.horizontal_distance_m / 2
        range_feasible = (
            one_way_distance <= flight.range_budget_m
            and one_way_distance <= aircraft.empty_range_m
        )
        energy_feasible = flight.energy_kwh <= aircraft.usable_energy_kwh * (1 - aircraft.reserve_fraction)
        if range_feasible and energy_feasible:
            low, best = middle, flight
        else:
            high = middle
    return low, best


def _is_feasible(
    boxes: tuple[Box, ...], aircraft: Aircraft, safe_payload: float, flight: Flight
) -> bool:
    mass = sum(box.mass_kg for box in boxes)
    volume = sum(box.volume_m3 for box in boxes)
    energy_limit = aircraft.usable_energy_kwh * (1 - aircraft.reserve_fraction)
    return (
        mass <= min(aircraft.max_payload_kg, safe_payload) + 1e-9
        and volume <= aircraft.volume_m3 + 1e-12
        and flight.energy_kwh <= energy_limit + 1e-12
        and flight.horizontal_distance_m / 2 <= flight.range_budget_m + 1e-9
        and flight.horizontal_distance_m / 2 <= aircraft.empty_range_m + 1e-9
    )


def _validate_solution(boxes: list[Box], chosen: list[Candidate]) -> None:
    expected = {box.code for box in boxes}
    assigned = [code for candidate in chosen for code in candidate.boxes]
    if len(assigned) != len(set(assigned)) or set(assigned) != expected:
        raise AssertionError("Set-partition solution must assign every box exactly once")


def build_candidates(
    site_code: str,
    boxes: list[Box],
    base: Node,
    site: Node,
    dem_max: float,
    aircrafts: dict[str, Aircraft],
    energy_rates: dict[str, float],
    reserve_overrides: dict[str, float] | None = None,
) -> list[Candidate]:
    candidates = []
    aircraft_list = []
    for original in aircrafts.values():
        if reserve_overrides and original.code in reserve_overrides:
            aircraft = Aircraft(**{**asdict(original), "reserve_fraction": reserve_overrides[original.code]})
        else:
            aircraft = original
        aircraft_list.append(aircraft)
    safe_payload_by_aircraft = {
        aircraft.code: max_safe_payload(
            aircraft, energy_rates[aircraft.code], base, site, dem_max
        )[0]
        for aircraft in aircraft_list
    }
    for mask in range(1, 1 << len(boxes)):
        subset = tuple(boxes[index] for index in range(len(boxes)) if mask & (1 << index))
        mass = sum(box.mass_kg for box in subset)
        volume = sum(box.volume_m3 for box in subset)
        for aircraft in aircraft_list:
            if mass > aircraft.max_payload_kg or volume > aircraft.volume_m3:
                continue
            flight = flight_for_payload(
                aircraft, energy_rates[aircraft.code], base, site, dem_max, mass
            )
            safe_payload = safe_payload_by_aircraft[aircraft.code]
            if not _is_feasible(subset, aircraft, safe_payload, flight):
                continue
            work_time = (
                aircraft.prep_s + aircraft.load_each_s * len(subset)
                + flight.time_s + aircraft.handoff_base_s
                + aircraft.handoff_each_s * len(subset)
            )
            candidates.append(Candidate(
                site=site_code,
                aircraft=aircraft.code,
                boxes=tuple(box.code for box in subset),
                mass_kg=mass,
                volume_m3=volume,
                energy_kwh=flight.energy_kwh,
                flight_time_s=flight.time_s,
                work_time_s=work_time,
                range_budget_m=flight.range_budget_m,
                return_range_budget_m=flight.return_range_budget_m,
                reserve_kwh=aircraft.usable_energy_kwh * (1-aircraft.reserve_fraction)-flight.energy_kwh,
            ))
    return candidates


def solve_set_partition(boxes: list[Box], candidates: list[Candidate]) -> list[Candidate]:
    """Exact lexicographic set partition via bitmask dynamic programming."""
    count = len(boxes)
    full_mask = (1 << count) - 1
    index = {box.code: position for position, box in enumerate(boxes)}
    by_first: list[list[tuple[int, Candidate]]] = [[] for _ in boxes]
    for candidate in candidates:
        mask = 0
        for code in candidate.boxes:
            mask |= 1 << index[code]
        first_index = min(index[code] for code in candidate.boxes)
        by_first[first_index].append((mask, candidate))

    best: dict[int, tuple[tuple[int, float, float], tuple[Candidate, ...]]] = {0: ((0, 0.0, 0.0), ())}
    for mask in range(full_mask + 1):
        if mask not in best:
            continue
        score, chosen = best[mask]
        remaining = full_mask ^ mask
        if remaining == 0:
            continue
        first_bit = (remaining & -remaining).bit_length() - 1
        for candidate_mask, candidate in by_first[first_bit]:
            if candidate_mask & mask:
                continue
            new_mask = mask | candidate_mask
            new_score = (score[0] + 1, score[1] + candidate.energy_kwh, score[2] + candidate.work_time_s)
            previous = best.get(new_mask)
            if previous is None or new_score < previous[0]:
                best[new_mask] = (new_score, chosen + (candidate,))
    if full_mask not in best:
        raise ValueError(f"No feasible complete partition for {boxes[0].site}")
    return list(best[full_mask][1])


def route_max_elevation(dem: rasterio.io.DatasetReader, base: Node, site: Node) -> tuple[float, float]:
    maximum, distance = sample_leg(dem, base, site)
    return maximum, distance


def run(reserves: Iterable[float] | None = None) -> dict:
    aircrafts = load_aircraft()
    base, sites = load_nodes()
    boxes_by_site = load_boxes()
    reserve_levels = list(reserves) if reserves is not None else [None]
    energy_rates = load_energy_per_meter(aircrafts)
    all_runs = []
    with rasterio.open(DEM_PATH) as dem:
        for reserve in reserve_levels:
            reserve_overrides = None if reserve is None else {code: reserve for code in aircrafts}
            payload_rows = []
            all_candidates: dict[str, list[Candidate]] = {}
            route_metadata = {}
            for site_code, site in sites.items():
                max_elevation, distance = route_max_elevation(dem, base, site)
                route_metadata[site_code] = {"distance_m": distance, "max_ground_elevation_m": max_elevation}
                for aircraft in aircrafts.values():
                    active = aircraft
                    if reserve_overrides:
                        active = Aircraft(**{**asdict(aircraft), "reserve_fraction": reserve})
                    safe_payload, flight = max_safe_payload(
                        active, energy_rates[active.code], base, site, max_elevation
                    )
                    payload_rows.append({
                        "site": site_code, "aircraft": active.code,
                        "max_safe_payload_kg": safe_payload,
                        "route_distance_m": distance,
                        "cruise_altitude_m": flight.cruise_altitude_m,
                        "empty_round_trip_energy_kwh": flight.energy_kwh,
                    })
                candidates = build_candidates(
                    site_code, boxes_by_site[site_code], base, site, max_elevation,
                    aircrafts, energy_rates, reserve_overrides,
                )
                all_candidates[site_code] = candidates
            partitions = {
                site_code: solve_set_partition(boxes_by_site[site_code], all_candidates[site_code])
                for site_code in sites
            }
            for site_code, chosen in partitions.items():
                _validate_solution(boxes_by_site[site_code], chosen)
            flattened = [candidate for candidates in partitions.values() for candidate in candidates]
            all_runs.append({
                "reserve_fraction": reserve,
                "safe_payloads": payload_rows,
                "route_metadata": route_metadata,
                "partitions": {
                    site: [asdict(candidate) for candidate in candidates]
                    for site, candidates in partitions.items()
                },
                "summary": {
                    "box_count": sum(len(items) for items in boxes_by_site.values()),
                    "flight_count": len(flattened),
                    "total_energy_kwh": sum(candidate.energy_kwh for candidate in flattened),
                    "total_work_time_s": sum(candidate.work_time_s for candidate in flattened),
                },
            })
    return {
        "model": {
            "energy_calibration": "usable_energy_kwh / empty_standard_range_m as baseline horizontal energy per meter; check one-way range against payload-adjusted outbound and empty return ranges",
            "reserve_basis": "aircraft return SOC lower bound unless --reserve scenarios override all types",
            "dem": str(DEM_PATH.relative_to(ROOT)),
            "crs": "EPSG:4326; great-circle distance used for horizontal legs",
        },
        "runs": all_runs,
    }


def write_outputs(result: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "problem1_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    run_data = result["runs"][0]
    with (output_dir / "safe_payloads.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=run_data["safe_payloads"][0].keys())
        writer.writeheader()
        writer.writerows(run_data["safe_payloads"])
    with (output_dir / "batches.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        rows = [candidate for batches in run_data["partitions"].values() for candidate in batches]
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        for row in rows:
            row = dict(row)
            row["boxes"] = ",".join(row["boxes"])
            writer.writerow(row)
    with (output_dir / "sensitivity_summary.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        fields = ["reserve_fraction", "box_count", "flight_count", "total_energy_kwh", "total_work_time_s"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in result["runs"]:
            writer.writerow({"reserve_fraction": item["reserve_fraction"], **item["summary"]})


def main() -> None:
    parser = argparse.ArgumentParser(description="Solve Problem 1 single-site round-trip batches")
    parser.add_argument("--reserve", nargs="+", type=float, help="Override each type's reserve fraction, e.g. 0.1 0.2 0.3")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/problem1")
    arguments = parser.parse_args()
    result = run(arguments.reserve)
    write_outputs(result, arguments.output)
    for item in result["runs"]:
        print(item["reserve_fraction"], item["summary"])
    print(f"Wrote results to {arguments.output}")


if __name__ == "__main__":
    main()
