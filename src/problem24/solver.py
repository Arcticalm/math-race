"""Hybrid NSGA-II + CP-SAT search for Problem 2.

NSGA-II explores per-service-area grouping policies. A fast constructive
scheduler evaluates the population; CP-SAT is called only for elite grouping
signatures and resolves the drone/battery start-time subproblem exactly for
that fixed grouping and integer-second model.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import random
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.problem1.solver import ROOT
from src.problem21.solver import (
    RouteEvaluator, _merge_multisite, _schedule_candidates, _validate,
    load_resources, load_task_boxes, write_outputs,
)
from src.problem23.groups import exact_site_partitions, signature
from src.problem23.cp_sat import solve_fixed_routes

OUTPUT_DEFAULT = ROOT / "outputs" / "problem24"


def dominates(a: dict, b: dict) -> bool:
    fields = ("makespan_s", "weighted_all_expected_tardiness", "total_energy_kwh", "sortie_count")
    return all(a[x] <= b[x] + 1e-7 for x in fields) and any(a[x] < b[x] - 1e-7 for x in fields)


def fronts(items: list[dict]) -> list[list[int]]:
    domination = [0] * len(items)
    beaten = [[] for _ in items]
    result = [[]]
    for i, left in enumerate(items):
        for j, right in enumerate(items):
            if i == j:
                continue
            if dominates(left["metrics"], right["metrics"]):
                beaten[i].append(j)
            elif dominates(right["metrics"], left["metrics"]):
                domination[i] += 1
        if domination[i] == 0:
            result[0].append(i)
    level = 0
    while result[level]:
        next_level = []
        for i in result[level]:
            for j in beaten[i]:
                domination[j] -= 1
                if domination[j] == 0:
                    next_level.append(j)
        level += 1
        result.append(next_level)
    return result[:-1]


def crowding(items: list[dict], indices: list[int]) -> dict[int, float]:
    distance = {index: 0.0 for index in indices}
    fields = ("makespan_s", "weighted_all_expected_tardiness", "total_energy_kwh", "sortie_count")
    for field in fields:
        ordered = sorted(indices, key=lambda index: items[index]["metrics"][field])
        if len(ordered) < 3:
            for index in ordered:
                distance[index] = float("inf")
            continue
        distance[ordered[0]] = distance[ordered[-1]] = float("inf")
        lo = items[ordered[0]]["metrics"][field]
        hi = items[ordered[-1]]["metrics"][field]
        if hi <= lo:
            continue
        for pos in range(1, len(ordered) - 1):
            distance[ordered[pos]] += (items[ordered[pos + 1]]["metrics"][field]
                                       - items[ordered[pos - 1]]["metrics"][field]) / (hi - lo)
    return distance


def select(items: list[dict], size: int) -> list[dict]:
    selected = []
    for level in fronts(items):
        if len(selected) + len(level) <= size:
            selected.extend(items[index] for index in level)
        else:
            distance = crowding(items, level)
            selected.extend(items[index] for index in sorted(level, key=lambda index: distance[index], reverse=True)[:size - len(selected)])
            break
    return selected


def make_grouping(chromosome: tuple[int, ...], policies: dict[str, list], sites: list[str], evaluator: RouteEvaluator) -> list:
    routes = []
    for site, gene in zip(sites, chromosome[:-1]):
        routes.extend(copy.deepcopy(policies[site][gene % len(policies[site])]))
    if chromosome[-1]:
        routes = _merge_multisite(routes, evaluator)
    return routes


def solve(population_size: int = 8, generations: int = 4, elite_cp: int = 2,
          cp_sat_time_limit_s: float = 5.0, seed: int = 20260924):
    rng = random.Random(seed)
    boxes = load_task_boxes()
    drones, batteries = load_resources()
    evaluator = RouteEvaluator(0.2, 1.0)
    try:
        exact = exact_site_partitions(boxes, evaluator)
        sites = sorted({box.site for box in boxes})
        policies = {site: [[route for route in exact[name] if route.route == [site]] for name in ("minimum_sorties", "minimum_work_time", "minimum_energy")] for site in sites}
        population = []
        seeds = [0, 1, 2]
        for policy in seeds:
            population.append(tuple([policy] * len(sites) + [0]))
        for _ in range(max(0, population_size - len(population))):
            population.append(tuple([rng.randrange(3) for _ in sites] + [rng.randrange(2)]))
        fast_cache, cp_cache = {}, {}
        all_candidates = []
        cp_calls = cp_hits = 0

        def evaluate(chromosome: tuple[int, ...], cp: bool = False) -> dict:
            nonlocal cp_calls, cp_hits
            routes = make_grouping(chromosome, policies, sites, evaluator)
            key = signature(routes)
            cache = cp_cache if cp else fast_cache
            if key in cache:
                if cp:
                    cp_hits += 1
                return cache[key]
            if cp:
                cp_calls += 1
                schedule, search = solve_fixed_routes(routes, drones, batteries, evaluator, cp_sat_time_limit_s)
                method = "cp_sat"
            else:
                schedule, search = _schedule_candidates(routes, drones, batteries, evaluator, "balanced")
                method = "heuristic"
            if schedule is None:
                metrics = {"feasible": False, "makespan_s": 1e12, "weighted_all_expected_tardiness": 1e12,
                           "total_energy_kwh": 1e12, "sortie_count": 1e12, "violations": ["infeasible"]}
                item = {"chromosome": chromosome, "routes": routes, "sorties": [], "metrics": metrics, "method": method, "search": search}
            else:
                metrics = _validate(schedule, boxes, drones, batteries, evaluator)
                item = {"chromosome": chromosome, "routes": routes, "sorties": schedule, "metrics": metrics, "method": method, "search": search}
            cache[key] = item
            return item

        for generation in range(generations):
            population_items = [evaluate(chromosome) for chromosome in population]
            elite = select(population_items, min(elite_cp, len(population_items)))
            for item in elite:
                cp_item = evaluate(item["chromosome"], cp=True)
                if cp_item["metrics"].get("feasible"):
                    all_candidates.append(cp_item)
            all_candidates.extend(population_items)
            ranked = select(population_items, len(population_items))
            parents = [item["chromosome"] for item in ranked]
            next_population = [item["chromosome"] for item in ranked[:max(1, population_size // 4)]]
            while len(next_population) < population_size:
                first, second = rng.choice(parents), rng.choice(parents)
                cut = rng.randrange(1, len(sites))
                child = list(first[:cut] + second[cut:])
                if rng.random() < 0.35:
                    child[rng.randrange(len(sites))] = rng.randrange(3)
                if rng.random() < 0.2:
                    child[-1] = 1 - child[-1]
                next_population.append(tuple(child))
            population = next_population

        feasible = [item for item in all_candidates if item["metrics"].get("feasible")]
        if not feasible:
            raise RuntimeError("NSGA-II produced no feasible candidate")
        nondominated = [item for item in feasible if not any(dominates(other["metrics"], item["metrics"]) for other in feasible if other is not item)]
        chosen = min(nondominated, key=lambda item: (item["metrics"]["makespan_s"], item["metrics"]["weighted_all_expected_tardiness"], item["metrics"]["total_energy_kwh"], item["metrics"]["sortie_count"]))
        metrics = dict(chosen["metrics"])
        metrics.update({"strategy": "NSGA-II outer + CP-SAT elite inner", "method": chosen["method"],
                        "objective_profile": "makespan, weighted lateness, energy, sorties",
                        "optimality_status": "best nondominated candidate found; global optimum unproven",
                        "population_size": population_size, "generations": generations,
                        "elite_cp_calls": elite_cp, "cp_sat_calls": cp_calls, "cp_sat_cache_hits": cp_hits,
                        "nondominated_count": len(nondominated), "seed": seed,
                        "candidate_scope": "per-service partition policy chromosomes with optional greedy two-site merge"})
        return chosen["sorties"], metrics, boxes, feasible
    finally:
        evaluator.close()


def write_outputs(sorties, metrics, boxes, candidates, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    try:
        write_outputs_base(sorties, metrics, boxes, output)
    except FileNotFoundError:
        pass
    fields = ["method", "sortie_count", "makespan_s", "weighted_all_expected_tardiness", "total_energy_kwh", "nondominated"]
    rows = []
    for item in candidates:
        metric = item["metrics"]
        rows.append({field: (item.get("method", "") if field == "method" else metric.get(field, "")) if field != "nondominated" else not any(dominates(other["metrics"], metric) for other in candidates if other is not item) for field in fields})
    with (output / "nsga2_candidates.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
    for row in rows:
        color = "#c0392b" if row["nondominated"] else "#2878b5"
        axes[0].scatter(row["sortie_count"], row["makespan_s"], color=color, alpha=0.75)
        axes[1].scatter(row["total_energy_kwh"], row["makespan_s"], color=color, alpha=0.75)
    axes[0].set(xlabel="Sorties", ylabel="Makespan (s)", title="NSGA-II candidates")
    axes[1].set(xlabel="Energy (kWh)", ylabel="Makespan (s)", title="Energy-time tradeoff")
    for axis in axes:
        axis.grid(alpha=0.25)
    fig.savefig(output / "nsga2_tradeoff.png", dpi=180)
    plt.close(fig)
    (output / "problem24_summary.json").write_text(json.dumps({key: metrics[key] for key in (
        "feasible", "sortie_count", "makespan_s", "total_energy_kwh", "weighted_all_expected_tardiness",
        "method", "strategy", "optimality_status", "population_size", "generations", "cp_sat_calls",
        "cp_sat_cache_hits", "nondominated_count", "seed")}, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "validation.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


def write_outputs_base(sorties, metrics, boxes, output):
    from src.problem21.solver import write_outputs as base_writer
    base_writer(sorties, metrics, boxes, output, 0.2, 1.0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--population", type=int, default=8)
    parser.add_argument("--generations", type=int, default=4)
    parser.add_argument("--elite-cp", type=int, default=2)
    parser.add_argument("--cp-sat-time-limit", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=20260924)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    args = parser.parse_args()
    sorties, metrics, boxes, candidates = solve(args.population, args.generations, args.elite_cp, args.cp_sat_time_limit, args.seed)
    write_outputs(sorties, metrics, boxes, candidates, args.output)
    print(json.dumps({key: metrics[key] for key in ("feasible", "sortie_count", "makespan_s", "total_energy_kwh", "method", "cp_sat_calls", "nondominated_count")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
