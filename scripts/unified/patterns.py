"""Finite, shared pattern library; no cost-only dominance pruning."""

from __future__ import annotations

import copy
import itertools
from collections import Counter
from dataclasses import dataclass

from src.problem21.solver import (
    _aircraft_for, _charge_duration, _hard_due, _partition_by_site,
    _merge_multisite, _schedule_deliveries,
)
from src.problem23.groups import exact_site_partitions


@dataclass
class Pattern:
    code: str
    sortie: object
    duration: float
    charge: float
    deliveries: dict[str, float]

    @property
    def geometry_key(self):
        return (tuple(self.sortie.route), self.sortie.aircraft,
                tuple(sorted(Counter(b.site for b in self.sortie.boxes).items())))


def identity(sortie):
    return (tuple(sorted(b.code for b in sortie.boxes)), tuple(sortie.route), sortie.aircraft)


def replay(sortie, evaluator, start=0.0, code=None):
    result = copy.deepcopy(sortie)
    aircraft = _aircraft_for(result.aircraft, evaluator.aircrafts, evaluator.reserve)
    result.code = code or result.code
    result.prep_start_s = start
    result.prep_end_s = start + aircraft.prep_s
    result.loading_end_s = result.prep_end_s + aircraft.load_each_s * len(result.boxes)
    result.takeoff_s = result.loading_end_s
    _schedule_deliveries(result, aircraft)
    result.return_s = (result.takeoff_s + result.flight_s
                       + len(result.route) * aircraft.handoff_base_s
                       + len(result.boxes) * aircraft.handoff_each_s)
    return result


def add_patterns(pool, proposals, evaluator, batteries, max_accepted=None):
    """Retain every feasible aircraft variant and every distinct box/order tuple."""
    keys = {identity(p.sortie) for p in pool}
    charge_by_type = {b.aircraft: b.full_charge_s for b in batteries}
    attempted = accepted = 0
    for boxes, route in proposals:
        if max_accepted is not None and accepted >= max_accepted:
            break
        attempted += 1
        previous_size = len(pool)
        if not boxes or set(route) != {b.site for b in boxes} or len(route) != len(set(route)):
            continue
        for kind in evaluator.aircrafts:
            key = (tuple(sorted(b.code for b in boxes)), tuple(route), kind)
            if key in keys:
                continue
            physical = evaluator.evaluate(list(boxes), list(route), kind)
            if physical is None:
                continue
            physical = replay(physical, evaluator)
            if any(physical.deliveries[b.code] > _hard_due(b) + 1e-8
                   for b in boxes if _hard_due(b) is not None):
                continue
            code = f"P{len(pool) + 1:05d}"
            physical.code = code
            pool.append(Pattern(code, physical, physical.return_s,
                                _charge_duration(charge_by_type[kind],
                                                 physical.battery_soc_return_percent / 100),
                                dict(physical.deliveries)))
            keys.add(key)
        accepted += len(pool) > previous_size
    return {"attempted_proposals": attempted, "accepted_proposals": accepted}


def generate(boxes, evaluator, batteries):
    groups = exact_site_partitions(boxes, evaluator)
    groups["constructive"] = _partition_by_site(boxes, evaluator)
    for name, sorties in list(groups.items()):
        groups[name + "_merged"] = _merge_multisite(sorties, evaluator)
    proposals = [(s.boxes, s.route) for routes in groups.values() for s in routes]
    proposals += [([b], [b.site]) for b in boxes]
    pool = []
    add_patterns(pool, proposals, evaluator, batteries)
    return pool, groups


def expand(pool, chosen, evaluator, batteries, limit=80):
    """Neighborhood columns from the audited Q3 incumbent, not a pricing proof.

    Split routes and transfer one box between two selected batches. Rank new
    proposals deterministically, retaining route orders explicitly. The cap is
    a declared search restriction, never a dominance claim.
    """
    proposals = {}
    known = {(tuple(sorted(b.code for b in p.sortie.boxes)), tuple(p.sortie.route))
             for p in pool}

    def offer(boxes, route):
        route = [s for s in route if any(b.site == s for b in boxes)]
        key = (tuple(sorted(b.code for b in boxes)), tuple(route))
        if boxes and key not in known:
            proposals[key] = (boxes, route)

    for sortie in chosen:
        for site in sortie.route:
            offer([b for b in sortie.boxes if b.site == site], [site])
        for box in sortie.boxes:
            offer([b for b in sortie.boxes if b.code != box.code], sortie.route)
    for first, second in itertools.combinations(chosen, 2):
        if len(set(first.route + second.route)) > 2:
            continue
        for source, target in ((first, second), (second, first)):
            for box in source.boxes:
                batch = target.boxes + [box]
                for route in itertools.permutations(sorted({b.site for b in batch})):
                    offer(batch, route)
    before = len(pool)
    admitted = add_patterns(pool, [proposals[k] for k in sorted(proposals)],
                            evaluator, batteries, max_accepted=limit)
    return {"new_patterns": len(pool) - before, "proposals": len(proposals),
            "accepted_proposal_limit": limit, **admitted, "method": "split and one-box transfer neighborhood"}
