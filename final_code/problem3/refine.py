"""Continuous-time refinement with fixed routes, relay locations and resource orders.

A linear program keeps each energy component on its incumbent charging branch.
Its optimum concerns only this fixed subproblem, never the original Q3 problem.
"""
from __future__ import annotations

from collections import defaultdict
from ortools.linear_solver import pywraplp

from final_code.problem2.patterns import replay
from final_code.problem2.transport import _charge_duration, _hard_due, _validate
from final_code.problem3.audit import audit_relay_resources, rebuild_relay_mission
from final_code.problem3.physics import LinkEvaluator, load_relay_parameters


def refine_joint(result, profiles, evaluator, boxes, drones, batteries):
    sorties, relays = result['sorties'], result['relays']
    lp = pywraplp.Solver.CreateSolver('GLOP')
    starts = {s.code: lp.NumVar(0, lp.infinity(), 'start_' + s.code) for s in sorties}
    begin = {r['relay_sortie']: lp.NumVar(0, lp.infinity(), 'begin_' + r['relay_sortie']) for r in relays}
    end = {r['relay_sortie']: lp.NumVar(0, lp.infinity(), 'end_' + r['relay_sortie']) for r in relays}
    makespan = lp.NumVar(0, lp.infinity(), 'makespan')
    params = load_relay_parameters()
    battery_by_code = {b.code: b for b in batteries}
    rate = (params.hover_power_kw + params.communication_power_kw) / 3600
    chains = defaultdict(list)
    lateness = []
    energies = []
    for s in sorties:
        start = starts[s.code]
        duration = s.return_s - s.prep_start_s
        lp.Add(makespan >= start + duration)
        for box in s.boxes:
            offset = s.deliveries[box.code] - s.prep_start_s
            due = _hard_due(box)
            if due is not None:
                lp.Add(start + offset <= due)
            if box.due_s is not None:
                late = lp.NumVar(0, lp.infinity(), 'late_' + box.code)
                lp.Add(late >= start + offset - box.due_s)
                lateness.append(box.priority * late)
        charge = _charge_duration(battery_by_code[s.battery].full_charge_s,
                                  s.battery_soc_return_percent / 100)
        chains['T:' + s.drone].append((s.prep_start_s, s.code, start, start + duration))
        chains['T:' + s.battery].append((s.prep_start_s, s.code, start, start + duration + charge))
    for r in relays:
        code = r['relay_sortie']
        start, stop = begin[code], end[code]
        prep = start - r['preflight_s']
        returned = stop + r['return_flight_s']
        energy = r['fixed_energy_kwh'] + rate * (stop - start)
        energies.append(energy)
        lp.Add(stop >= start)
        lp.Add(prep >= 0)
        lp.Add(makespan >= returned)
        lp.Add(energy <= params.usable_energy_kwh * (1 - params.reserve_fraction))
        for task, gap in r['pattern_gaps']:
            demand = profiles[task][gap]
            lp.Add(start <= starts[task] + demand['start'])
            lp.Add(stop >= starts[task] + demand['end'])
        fraction = energy / params.usable_energy_kwh
        if r['return_soc_percent'] < 90:
            lp.Add(fraction >= .1)
            charge = params.full_charge_s * (5 / 18 + 13 / 18 * fraction)
        else:
            lp.Add(fraction <= .1)
            charge = 3.5 * params.full_charge_s * fraction
        chains['R:' + r['relay_drone']].append((r['preparation_start_s'], code, prep, returned + params.turnaround_s))
        chains['R:' + r['energy_component']].append((r['preparation_start_s'], code, prep, returned + charge))
    for chain in chains.values():
        chain.sort(key=lambda item: (item[0], item[1]))
        for previous, current in zip(chain, chain[1:]):
            lp.Add(current[2] >= previous[3] + 1e-6)
    stages = []
    for name, expression in (('makespan_s', makespan), ('weighted_lateness', sum(lateness)),
                             ('relay_energy_kwh', sum(energies))):
        lp.Minimize(expression)
        status = lp.Solve()
        if status != pywraplp.Solver.OPTIMAL:
            return result, {'accepted': False, 'reason': 'fixed continuous LP not optimal', 'status': status}
        optimum = lp.Objective().Value()
        stages.append({'objective': name, 'optimum': optimum})
        # A microscopic tolerance permits numeric feasibility of later stages.
        if name != 'relay_energy_kwh':
            lp.Add(expression <= optimum + 1e-8)
    updated_sorties = [replay(s, evaluator, max(0., starts[s.code].solution_value())) for s in sorties]
    links = LinkEvaluator()
    try:
        updated_relays = [rebuild_relay_mission({**r,
            'service_start_s': begin[r['relay_sortie']].solution_value(),
            'service_end_s': end[r['relay_sortie']].solution_value()}, links) for r in relays]
    finally:
        links.close()
    physical = _validate(updated_sorties, boxes, drones, batteries, evaluator)
    resource = audit_relay_resources(updated_relays)
    def score(tasks, missions):
        return (max([s.return_s for s in tasks] + [r['return_o01_s'] for r in missions]),
                sum(b.priority * max(0, s.deliveries[b.code] - b.due_s)
                    for s in tasks for b in s.boxes if b.due_s is not None),
                sum(s.energy_kwh for s in tasks) + sum(r['energy_kwh'] for r in missions))
    before, after = score(sorties, relays), score(updated_sorties, updated_relays)
    accepted = physical['feasible'] and resource['feasible'] and after < before
    info = {'accepted': accepted, 'scope': 'fixed routes, hover points, gap assignments, resource orders and charge branches',
            'solver': 'GLOP', 'stages': stages, 'before': before, 'after': after}
    return ({'sorties': updated_sorties, 'relays': updated_relays} if accepted else result), info
