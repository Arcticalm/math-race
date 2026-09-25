"""Optional transport patterns and variable relay missions in one CP-SAT model."""

from __future__ import annotations

import math
from collections import defaultdict

from ortools.sat.python import cp_model

from final_code.problem2.patterns import identity, replay
from final_code.problem2.transport import _charge_duration, _hard_due
from final_code.problem3.physics import load_relay_parameters
from final_code.problem4.solver import load_inventory


def ceil(value):
    return math.ceil(value - 1e-8)


def floor(value):
    return math.floor(value + 1e-8)


def color_intervals(records, codes):
    """Exact interval coloring for interchangeable resources, half-open intervals."""
    ready = {code: 0. for code in codes}
    result = {}
    for key, start, end in sorted(records, key=lambda row: (row[1], row[2], row[0])):
        code = next((c for c in codes if ready[c] <= start + 1e-7), None)
        if code is None:
            raise ValueError("Resource coloring failed; cumulative/replay mismatch")
        result[key] = code
        ready[code] = end
    return result


def solve(pool, boxes, drones, batteries, evaluator, time_limit=60.,
          profiles=None, locations=None, max_relays=10, horizon=36000,
          hint=None, makespan_cap=None, partition_feedback=None,
          partition_groups=0, random_seed=17, workers=8):
    """Time-first lexicographic incumbent refinement, with explicit stage bounds.

    Q2 has no communication or partition restriction. Q3 freely reselects every
    pattern and resource from the same pool. Optional group labels ensure a
    later frozen Q4 partition under the shared-relay closure convention. Pure
    Q3 defaults to no extra partition restriction; the integrated run requests 3.
    """
    if not pool or not boxes:
        raise ValueError("Empty pattern library or task set")
    if not math.isfinite(time_limit) or time_limit <= 0 or horizon <= 0 or max_relays < 0 or partition_groups < 0 or workers < 1:
        raise ValueError("Invalid solve limits")
    joint = profiles is not None
    model = cp_model.CpModel()
    x, starts, ends = {}, {}, {}
    drone_intervals, battery_intervals = defaultdict(list), defaultdict(list)
    known_boxes = {b.code for b in boxes}
    cover = {b.code: [] for b in boxes}
    energy_terms, lateness = [], []
    hint_variables = []
    by_kind = defaultdict(list)
    for battery in batteries:
        by_kind[battery.aircraft].append(battery.full_charge_s)
    if any(len(set(times)) != 1 for times in by_kind.values()):
        raise ValueError("Cumulative battery model requires equal charge curves within each type")
    site_groups = {}
    if joint and partition_groups:
        sites = sorted({b.site for b in boxes})
        if len(sites) < partition_groups:
            raise ValueError("More required groups than service areas")
        for site in sites:
            site_groups[site] = model.new_int_var(0, partition_groups - 1, "partition_" + site)
        model.add(site_groups[sites[0]] == 0)
        for group in range(partition_groups):
            membership = []
            for site in sites:
                flag = model.new_bool_var(f"site_{site}_group_{group}")
                model.add(site_groups[site] == group).only_enforce_if(flag)
                model.add(site_groups[site] != group).only_enforce_if(flag.negated())
                membership.append(flag)
            model.add(sum(membership) >= 1)

    for pattern in pool:
        code, sortie = pattern.code, pattern.sortie
        if not {b.code for b in sortie.boxes}.issubset(known_boxes):
            raise ValueError("Pattern references an unknown box")
        use = x[code] = model.new_bool_var("use_" + code)
        start = starts[code] = model.new_int_var(0, horizon, "start_" + code)
        end = ends[code] = model.new_int_var(0, horizon, "end_" + code)
        model.add(start == 0).only_enforce_if(use.negated())
        model.add(end == 0).only_enforce_if(use.negated())
        duration = ceil(pattern.duration)
        drone_intervals[sortie.aircraft].append(model.new_optional_interval_var(
            start, duration, end, use, "air_" + code))
        battery_end = model.new_int_var(0, horizon + ceil(pattern.charge), "charge_end_" + code)
        battery_intervals[sortie.aircraft].append(model.new_optional_interval_var(
            start, duration + ceil(pattern.charge), battery_end, use, "battery_" + code))
        for box in sortie.boxes:
            cover[box.code].append(use)
            hard = _hard_due(box)
            if hard is not None:
                model.add(start + ceil(pattern.deliveries[box.code]) <= floor(hard)).only_enforce_if(use)
        if site_groups:
            for site in sortie.route[1:]:
                model.add(site_groups[site] == site_groups[sortie.route[0]]).only_enforce_if(use)
        energy_terms.append(ceil(sortie.energy_kwh * 1_000_000) * use)
        hint_variables += [use, start]
    for box in boxes:
        model.add(sum(cover[box.code]) == 1)
        if box.due_s is None:
            continue
        late = model.new_int_var(0, horizon, "late_" + box.code)
        for pattern in pool:
            if box.code in pattern.deliveries:
                model.add(late >= starts[pattern.code] + ceil(pattern.deliveries[box.code])
                          - floor(box.due_s)).only_enforce_if(x[pattern.code])
        lateness.append(round(box.priority * 100) * late)
    for kind, intervals in drone_intervals.items():
        model.add_cumulative(intervals, [1] * len(intervals), sum(d.aircraft == kind for d in drones))
    for kind, intervals in battery_intervals.items():
        model.add_cumulative(intervals, [1] * len(intervals), sum(b.aircraft == kind for b in batteries))
    makespan = model.new_int_var(0, horizon, "makespan")
    for end in ends.values():
        model.add(makespan >= end)
    if makespan_cap is not None:
        model.add(makespan <= ceil(makespan_cap))

    missions, assignment = [], {}
    if joint:
        params = load_relay_parameters()
        inventory = load_inventory()
        requirements = [(p.code, index, demand) for p in pool
                        for index, demand in enumerate(profiles[p.code])]
        air_intervals, energy_intervals = [], []
        hover_rate = ceil((params.hover_power_kw + params.communication_power_kw) * 1_000_000 / 3600)
        capacity = floor(params.usable_energy_kwh * 1_000_000)
        usable = floor(capacity * (1 - params.reserve_fraction))
        for slot in range(max_relays if requirements and locations else 0):
            use = model.new_bool_var(f"relay_{slot}")
            loc = model.new_int_var(0, len(locations) - 1, f"location_{slot}")
            group = model.new_int_var(0, max(0, partition_groups - 1), f"relay_group_{slot}")
            service_start = model.new_int_var(0, horizon, f"service_start_{slot}")
            service_end = model.new_int_var(0, horizon, f"service_end_{slot}")
            service_duration = model.new_int_var(0, horizon, f"hover_{slot}")
            model.add(service_duration == service_end - service_start)
            before = model.new_int_var(0, horizon, f"preflight_{slot}")
            after = model.new_int_var(0, horizon, f"return_flight_{slot}")
            fixed = model.new_int_var(0, usable, f"fixed_energy_{slot}")
            model.add_element(loc, [ceil(c["preflight_s"]) for c in locations], before)
            model.add_element(loc, [ceil(c["return_flight_s"]) for c in locations], after)
            model.add_element(loc, [ceil(c["fixed_energy_kwh"] * 1_000_000) for c in locations], fixed)
            energy = model.new_int_var(0, usable, f"relay_energy_{slot}")
            model.add(energy == fixed + hover_rate * service_duration)
            charged_energy = model.new_int_var(0, usable, f"selected_energy_{slot}")
            model.add(charged_energy == energy).only_enforce_if(use)
            model.add(charged_energy == 0).only_enforce_if(use.negated())
            energy_terms.append(charged_energy)
            prep = model.new_int_var(0, horizon, f"relay_prep_{slot}")
            returned = model.new_int_var(0, horizon * 2, f"relay_return_{slot}")
            model.add(prep == service_start - before)
            model.add(returned == service_end + after)
            model.add(makespan >= returned).only_enforce_if(use)
            # The piecewise full-charge duration is a concave function of
            # consumed energy: min(3.5*T*e/C, 5*T/18+13*T*e/(18*C)).
            full = ceil(params.full_charge_s)
            charge_a = model.new_int_var(0, 4 * full, f"charge_a_{slot}")
            charge_b = model.new_int_var(0, 4 * full, f"charge_b_{slot}")
            charge = model.new_int_var(0, 4 * full, f"relay_charge_{slot}")
            model.add_division_equality(charge_a, 7 * full * energy + 2 * capacity - 1, 2 * capacity)
            model.add_division_equality(charge_b,
                                       5 * full * capacity + 13 * full * energy + 18 * capacity - 1,
                                       18 * capacity)
            model.add_min_equality(charge, [charge_a, charge_b])
            for extra, target, name in ((ceil(params.turnaround_s), air_intervals, "air"),
                                        (charge, energy_intervals, "battery")):
                resource_end = model.new_int_var(0, 2 * horizon, f"relay_{name}_end_{slot}")
                duration = model.new_int_var(0, 2 * horizon, f"relay_{name}_duration_{slot}")
                model.add(resource_end == returned + extra)
                model.add(duration == resource_end - prep)
                target.append(model.new_optional_interval_var(prep, duration, resource_end,
                                                               use, f"relay_{name}_{slot}"))
            if missions:
                model.add(use <= missions[-1]["use"])
                model.add(service_start >= missions[-1]["start"]).only_enforce_if(use)
            missions.append(dict(use=use, loc=loc, start=service_start, end=service_end, group=group))
            hint_variables += [use, loc, service_start, service_end]
        by_code = {p.code: p for p in pool}
        for code, gap, demand in requirements:
            choices = []
            for slot, mission in enumerate(missions):
                if not demand["locations"]:
                    continue
                assigned = model.new_bool_var(f"gap_{code}_{gap}_{slot}")
                assignment[code, gap, slot] = assigned
                choices.append(assigned)
                model.add(assigned <= mission["use"])
                model.add_allowed_assignments([mission["loc"]],
                                              [(i,) for i in demand["locations"]]).only_enforce_if(assigned)
                model.add(mission["start"] <= starts[code] + floor(demand["start"])).only_enforce_if(assigned)
                model.add(mission["end"] >= starts[code] + ceil(demand["end"])).only_enforce_if(assigned)
                if site_groups:
                    model.add(mission["group"] == site_groups[by_code[code].sortie.route[0]]).only_enforce_if(assigned)
            model.add(sum(choices) == x[code])
        for slot, mission in enumerate(missions):
            model.add(sum(flag for (code, gap, k), flag in assignment.items() if k == slot)
                      >= mission["use"])
        model.add_cumulative(air_intervals, [1] * len(air_intervals), inventory["relay_airframe"])
        model.add_cumulative(energy_intervals, [1] * len(energy_intervals), inventory["relay_energy"])

    if hint:
        by_identity = {identity(s): s for s in hint}
        for pattern in pool:
            previous = by_identity.get(identity(pattern.sortie))
            model.add_hint(x[pattern.code], int(previous is not None))
            model.add_hint(starts[pattern.code], ceil(previous.prep_start_s) if previous else 0)
    stages = [("makespan_s", makespan, .55), ("weighted_lateness_x100", sum(lateness), .2),
              ("energy_micro_kwh", sum(energy_terms), .2),
              ("sorties", sum(x.values()) + sum(m["use"] for m in missions), .05)]
    # Q4 feedback is a final search preference, never a silent relaxation of
    # the Q3 time/lateness/energy/sortie incumbent bounds.
    if partition_feedback:
        groups = {site: i for i, row in enumerate(partition_feedback)
                  for site in row["sites"].split(",")}
        crossings = [x[p.code] for p in pool
                     if len({groups[s] for s in p.sortie.route}) > 1]
        stages.append(("previous_partition_crossings", sum(crossings), .05))
    info = {"time_grid_s": 1, "energy_grid_kwh": 1e-6,
            "scope": "finite pattern/location library, conservative integer model",
            "joint": joint, "pattern_count": len(pool), "horizon_s": horizon,
            "max_relay_missions": max_relays if joint else None,
            "three_group_compatibility_required": bool(joint and partition_groups == 3),
            "required_partition_groups": partition_groups if joint else 0,
            "random_seed": random_seed, "workers": workers, "stages": []}
    incumbent = None
    for name, expression, share in stages:
        model.minimize(expression)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(1., time_limit * share)
        solver.parameters.num_search_workers = workers
        solver.parameters.random_seed = random_seed
        status = solver.solve(model)
        info["stages"].append({"objective": name, "status": solver.status_name(status),
                               "lower_bound": solver.best_objective_bound,
                               "incumbent": solver.objective_value if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None})
        print(f"{'Q3' if joint else 'Q2'} {name}: {info['stages'][-1]}", flush=True)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            if incumbent is None:
                info["status"] = solver.status_name(status)
                info["model_validation"] = model.validate()
                return None, info
            break
        incumbent = solver
        model.add(expression <= round(solver.objective_value))
        model.clear_hints()
        for variable in hint_variables:
            model.add_hint(variable, solver.value(variable))
    solver = incumbent
    info["status"] = "FEASIBLE"
    info["restricted_lexicographic_optimal"] = all(s["status"] == "OPTIMAL" for s in info["stages"])
    info["global_optimal"] = False
    info["integer_makespan_s"] = solver.value(makespan)
    selected = [p for p in pool if solver.value(x[p.code])]
    sorties = [replay(p.sortie, evaluator, float(solver.value(starts[p.code])), p.code) for p in selected]
    for kind in sorted(drone_intervals):
        matching = [s for s in sorties if s.aircraft == kind]
        drone_ids = color_intervals([(s.code, s.prep_start_s, s.return_s) for s in matching],
                                   [d.code for d in drones if d.aircraft == kind])
        charge_by_code = {p.code: p.charge for p in selected}
        battery_ids = color_intervals([(s.code, s.prep_start_s, s.return_s + charge_by_code[s.code])
                                       for s in matching], [b.code for b in batteries if b.aircraft == kind])
        for sortie in matching:
            sortie.drone, sortie.battery = drone_ids[sortie.code], battery_ids[sortie.code]
    relays = []
    if joint:
        for slot, mission in enumerate(missions):
            if not solver.value(mission["use"]):
                continue
            loc = locations[solver.value(mission["loc"])]
            start, end = float(solver.value(mission["start"])), float(solver.value(mission["end"]))
            energy = loc["fixed_energy_kwh"] + (params.hover_power_kw + params.communication_power_kw) * (end - start) / 3600
            soc = 100 * (1 - energy / params.usable_energy_kwh)
            prep = start - loc["preflight_s"]
            returned = end + loc["return_flight_s"]
            covered = sorted({code for (code, gap, k), flag in assignment.items()
                              if k == slot and solver.value(flag)})
            relays.append({**loc, "relay_sortie": f"RU-{slot + 1:03d}",
                           "service_start_s": start, "service_end_s": end,
                           "preparation_start_s": prep, "return_o01_s": returned,
                           "energy_kwh": energy, "return_soc_percent": soc,
                           "takeoff_s": prep + params.preparation_s,
                           "arrival_s": start - params.link_setup_s,
                           "drone_ready_s": returned + params.turnaround_s,
                           "charge_complete_s": returned + _charge_duration(params.full_charge_s, soc / 100),
                           "covered_sorties": ",".join(covered), "covered_gap_ids": [],
                           "pattern_gaps": [(code, gap) for (code, gap, k), flag in assignment.items()
                                            if k == slot and solver.value(flag)]})
        drone_ids = color_intervals([(r["relay_sortie"], r["preparation_start_s"], r["drone_ready_s"]) for r in relays],
                                   [f"R{i + 1:02d}" for i in range(inventory["relay_airframe"])])
        battery_ids = color_intervals([(r["relay_sortie"], r["preparation_start_s"], r["charge_complete_s"]) for r in relays],
                                     [f"RE-{i + 1:02d}" for i in range(inventory["relay_energy"])])
        for r in relays:
            r["relay_drone"] = drone_ids[r["relay_sortie"]]
            r["energy_component"] = battery_ids[r["relay_sortie"]]
        info["three_group_witness"] = {s: solver.value(g) for s, g in site_groups.items()}
    return {"sorties": sorties, "relays": relays}, info
