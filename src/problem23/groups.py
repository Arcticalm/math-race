"""Generate exact single-site box partitions for multiple objectives."""

from __future__ import annotations

import copy
from collections import defaultdict
from functools import lru_cache

from src.problem21.solver import RouteEvaluator, Sortie, TaskBox


def signature(sorties: list[Sortie]) -> tuple:
    return tuple(sorted((tuple(sorted(box.code for box in sortie.boxes)),
                         tuple(sortie.route), sortie.aircraft) for sortie in sorties))


def exact_site_partitions(boxes: list[TaskBox], evaluator: RouteEvaluator) -> dict[str, list[Sortie]]:
    policies = {
        "minimum_sorties": (0, 1, 2),
        "minimum_work_time": (2, 0, 1),
        "minimum_energy": (1, 0, 2),
    }
    by_site = defaultdict(list)
    for box in boxes:
        by_site[box.site].append(box)
    results = {name: [] for name in policies}
    for site, site_boxes in sorted(by_site.items()):
        count = len(site_boxes)
        full = (1 << count) - 1
        by_first = [[] for _ in site_boxes]
        for mask in range(1, full + 1):
            group = [site_boxes[index] for index in range(count) if mask & (1 << index)]
            mass = sum(box.mass_kg for box in group)
            volume = sum(box.volume_m3 for box in group)
            for kind, aircraft in evaluator.aircrafts.items():
                if mass > aircraft.max_payload_kg + 1e-9 or volume > aircraft.volume_m3 + 1e-12:
                    continue
                sortie = evaluator.evaluate(group, [site], kind)
                if sortie is None:
                    continue
                duration = (aircraft.prep_s + aircraft.load_each_s * len(group)
                            + sortie.flight_s + aircraft.handoff_base_s
                            + aircraft.handoff_each_s * len(group))
                values = (1.0, sortie.energy_kwh, duration)
                for index in range(count):
                    if mask & (1 << index):
                        by_first[index].append((mask, sortie, values))
        for name, order in policies.items():
            @lru_cache(maxsize=None)
            def best(remaining: int):
                if not remaining:
                    return (0.0, 0.0, 0.0), ()
                first = (remaining & -remaining).bit_length() - 1
                incumbent = None
                for mask, sortie, values in by_first[first]:
                    if mask & remaining != mask:
                        continue
                    tail = best(remaining ^ mask)
                    if tail is None:
                        continue
                    score = tuple(values[index] + tail[0][index] for index in range(3))
                    key = tuple(score[index] for index in order)
                    if incumbent is None or key < incumbent[0]:
                        incumbent = key, score, (sortie, *tail[1])
                return None if incumbent is None else (incumbent[1], incumbent[2])
            solution = best(full)
            if solution is None:
                raise ValueError(f"No feasible one-site partition for {site}")
            results[name].extend(copy.deepcopy(sortie) for sortie in solution[1])
    return results
