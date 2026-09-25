"""Q2 independent selection, Q3 joint reselection, Q4 frozen partition feedback."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import zipfile
import math
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from final_code.problem3.communication import build_profiles, locations
from final_code.problem2.master import solve
from final_code.problem2.patterns import expand, generate
from final_code.problem1.solver import ROOT, DEM_PATH
from final_code.problem2.transport import (
    RouteEvaluator, _charge_duration, _schedule_candidates, _validate,
    load_resources, load_task_boxes, write_outputs,
)
from final_code.problem2.terrain_audit import audit_clearance
from final_code.problem3.audit import audit_communication, audit_relay_resources
from final_code.problem3.physics import LinkEvaluator, load_relay_parameters
from final_code.problem3.transport_relay import (
    _hard_deadline_audit, _plot_problem3_overview, _write_csv,
    _write_q3_submission, build_trajectory,
)
from final_code.problem4.solver import run as partition_frozen_schedule


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def digest(path):
    with path.open("rb") as stream:
        checksum = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
        return checksum.hexdigest()


def snapshot(directory):
    return {p.name: digest(p) for p in sorted(directory.glob("*.csv"))}


def transport_score(metrics):
    return (metrics["makespan_s"], metrics["weighted_all_expected_tardiness"],
            metrics["total_energy_kwh"], metrics["sortie_count"])


def joint_score(metrics, partition):
    if not all(partition.get("solutions", {}).get(str(k), {}).get("feasible") for k in (2, 3)):
        return None
    scores = [partition["solutions"][str(k)]["score"] for k in (2, 3)]
    return (metrics["joint_makespan_s"],
            metrics["transport_validation"]["weighted_all_expected_tardiness"],
            metrics["joint_energy_kwh"], metrics["total_sortie_count"],
            sum(s[0] for s in scores), sum(s[1] for s in scores), max(s[2] for s in scores))


def audit_and_export_joint(directory, result, search, profiles, boxes, drones, batteries, evaluator):
    directory.mkdir(parents=True, exist_ok=True)
    sorties, relays = result["sorties"], result["relays"]
    transport = _validate(sorties, boxes, drones, batteries, evaluator)
    terrain = audit_clearance(sorties, evaluator)
    phases = build_trajectory(sorties)
    by_code = {s.code: s for s in sorties}
    # Audit only the assigned demand windows, so unrelated overlapping relay
    # missions cannot accidentally claim coverage for this transport.
    views = []
    for relay in relays:
        for code, gap in relay["pattern_gaps"]:
            demand = profiles[code][gap]
            start = by_code[code].prep_start_s + demand["start"]
            end = by_code[code].prep_start_s + demand["end"]
            if start < relay["service_start_s"] - 1e-7 or end > relay["service_end_s"] + 1e-7:
                raise ValueError("Relay replay does not contain its assigned demand")
            views.append({**relay, "covered_sorties": code,
                          "service_start_s": start, "service_end_s": end})
    communication, continuous = audit_communication(phases, views, step_s=10., minimum_step_s=.25)
    resources = audit_relay_resources(relays)
    deadlines = _hard_deadline_audit(sorties)
    feasible = all((transport["feasible"], terrain["feasible"], continuous["certified"],
                    resources["feasible"], deadlines["passed"]))
    metrics = {
        "feasible": feasible, "continuity_certified": continuous["certified"],
        "transport_validation": transport, "terrain_clearance": terrain,
        "continuous_communication_validation": continuous,
        "relay_validation": resources, "hard_deadline_audit": deadlines,
        "search": search, "transport_sortie_count": len(sorties),
        "relay_sortie_count": len(relays), "total_sortie_count": len(sorties) + len(relays),
        "joint_makespan_s": max([s.return_s for s in sorties] + [r["return_o01_s"] for r in relays]),
        "joint_energy_kwh": sum(s.energy_kwh for s in sorties) + sum(r["energy_kwh"] for r in relays),
        "global_optimal": False,
    }
    _write_csv(directory / "communication_audit.csv", communication)
    _write_csv(directory / "relay_schedule.csv", relays)
    params = load_relay_parameters()
    _write_csv(directory / "relay_resource_audit.csv", [{
        "中继架次编号": r["relay_sortie"], "中继无人机编号": r["relay_drone"],
        "能源组件编号": r["energy_component"], "准备开始时刻（s）": r["preparation_start_s"],
        "建链完成/服务开始（s）": r["service_start_s"], "服务结束时刻（s）": r["service_end_s"],
        "返回O01时刻（s）": r["return_o01_s"],
        "机体再次可用（s）": r["return_o01_s"] + params.turnaround_s,
        "能源组件再次可用（s）": r["charge_complete_s"],
        "架次能耗（kWh）": r["energy_kwh"], "返航SOC（%）": r["return_soc_percent"],
    } for r in relays])
    by_battery = {b.code: b for b in batteries}
    _write_csv(directory / "transport_inherited_audit.csv", [{
        "架次编号": s.code, "无人机编号": s.drone, "机型编号": s.aircraft,
        "电池编号": s.battery, "准备开始时刻（s）": s.prep_start_s,
        "起飞时刻（s）": s.takeoff_s, "返回O01时刻（s）": s.return_s,
        "访问服务区顺序": "→".join(s.route), "架次能耗（kWh）": s.energy_kwh,
        "返航SOC（%）": s.battery_soc_return_percent, "逐箱交付数": len(s.boxes),
        "电池充电完成时刻（s）": s.return_s + _charge_duration(
            by_battery[s.battery].full_charge_s, s.battery_soc_return_percent / 100),
    } for s in sorties])
    _write_csv(directory / "box_delivery_audit.csv", [{
        "货箱编号": b.code, "服务区编号": b.site, "架次编号": s.code,
        "质量（kg）": b.mass_kg, "交付完成时刻（s）": s.deliveries[b.code],
    } for s in sorties for b in s.boxes])
    _write_csv(directory / "trajectory_phases.csv", [asdict(p) for p in phases])
    if feasible:
        _write_q3_submission(directory, sorties, [], relays, communication)
    save_json(directory / "screening.json", metrics)
    return metrics


def package_versions():
    result = {}
    for name in ("ortools", "numpy", "scipy", "rasterio", "openpyxl", "matplotlib"):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
    return result


def write_program_bundle(output):
    from final_code.package import write_program_bundle as bundle

    bundle(output / "unified_program.zip")
    for folder, name in (("q2", "problem2_program.zip"), ("q3", "problem3_program.zip")):
        if (output / folder).exists():
            shutil.copy2(output / "unified_program.zip", output / folder / name)


def profile_signature():
    sources = list((ROOT / "data/无人机应急物资运输基础数据").glob("*.xlsx")) + [DEM_PATH]
    sources += [ROOT / name for name in ("final_code/problem3/communication.py",
                 "final_code/problem3/physics.py", "final_code/problem3/transport_relay.py",
                 "final_code/problem2/transport.py", "final_code/problem1/solver.py")]
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(sources)}


def run(output, rounds=2, time_limit=120., max_relays=10, expansion_limit=80, profile_cache=None):
    if rounds < 1 or not math.isfinite(time_limit) or time_limit <= 0 or max_relays < 0 or expansion_limit < 1:
        raise ValueError("Invalid feedback or solver limits")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose a new output directory; existing results are never overwritten")
    output.mkdir(parents=True, exist_ok=True)
    boxes = load_task_boxes()
    drones, batteries = load_resources()
    evaluator = RouteEvaluator(.2, 1.)
    history, cache = [], {}
    signature = profile_signature()
    if profile_cache is not None:
        previous = json.loads(profile_cache.read_text())
        if previous["signature"] != signature:
            raise ValueError("Communication cache does not match source inputs and geometry code")
        cache = previous["profiles"]
    best_q2, best_joint, feedback = None, None, None
    try:
        print("Generating common route/box/aircraft patterns", flush=True)
        pool, groups = generate(boxes, evaluator, batteries)
        print(f"Initial shared pool: {len(pool)} patterns", flush=True)
        warm = []
        for routes in groups.values():
            schedule, _ = _schedule_candidates(routes, drones, batteries, evaluator, "balanced")
            if schedule:
                metrics = _validate(schedule, boxes, drones, batteries, evaluator)
                if metrics["feasible"]:
                    warm.append((transport_score(metrics), schedule))
        hint = min(warm, key=lambda item: item[0])[1] if warm else None
        links = LinkEvaluator()
        try:
            candidate_locations = locations(links)
        finally:
            links.close()
        save_json(output / "relay_locations.json", candidate_locations)
        for iteration in range(1, rounds + 1):
            directory = output / f"iteration_{iteration:02d}"
            record = {"iteration": iteration, "pattern_count": len(pool)}
            q2, q2_search = solve(pool, boxes, drones, batteries, evaluator,
                                   time_limit=time_limit, hint=hint)
            save_json(directory / "q2_search.json", q2_search)
            if q2 is not None:
                q2_metrics = _validate(q2["sorties"], boxes, drones, batteries, evaluator)
                q2_metrics["terrain_clearance"] = audit_clearance(q2["sorties"], evaluator)
                q2_metrics.update(search=q2_search, global_optimal=False,
                                  objective_profile="makespan, weighted lateness, energy, sorties")
                if not q2_metrics["feasible"] or not q2_metrics["terrain_clearance"]["feasible"]:
                    raise ValueError("Q2 continuous-time replay failed")
                if best_q2 is None or transport_score(q2_metrics) < transport_score(best_q2[1]):
                    best_q2 = (q2, q2_metrics, iteration)
                hint = best_q2[0]["sorties"]
                record["q2_score"] = transport_score(q2_metrics)
            if best_q2 is None:
                record["status"] = "no Q2 incumbent within solver limits"
                history.append(record)
                break
            profiles = build_profiles(pool, candidate_locations, cache)
            save_json(directory / "communication_profiles.json", profiles)
            save_json(output / "communication_cache.json", {"signature": signature, "profiles": cache})
            record["q3_eligible_patterns"] = sum(all(d["locations"] for d in profiles[p.code]) for p in pool)
            print(f"Q3: {record['q3_eligible_patterns']} patterns have certified relay options", flush=True)
            joint, search = solve(pool, boxes, drones, batteries, evaluator,
                                  time_limit=time_limit, profiles=profiles, locations=candidate_locations,
                                  max_relays=max_relays, hint=hint, partition_feedback=feedback,
                                  partition_groups=3)
            save_json(directory / "q3_search.json", search)
            if joint is not None:
                q3_dir = directory / "q3"
                metrics = audit_and_export_joint(q3_dir, joint, search, profiles,
                                                 boxes, drones, batteries, evaluator)
                record["q3_feasible"] = metrics["feasible"]
                record["q3_makespan_s"] = metrics["joint_makespan_s"]
                if metrics["feasible"]:
                    frozen = snapshot(q3_dir)
                    partition = partition_frozen_schedule(q3_dir, directory / "q4")
                    if frozen != snapshot(q3_dir):
                        raise ValueError("Q4 modified the frozen Q3 input")
                    score = joint_score(metrics, partition)
                    record["joint_score"] = score
                    if score is not None:
                        if best_joint is None or score < best_joint["score"]:
                            best_joint = dict(score=score, iteration=iteration, result=joint,
                                              metrics=metrics, partition=partition)
                        feedback = partition["solutions"]["3"]["groups"]
                        record["q4_feedback"] = {
                            k: {"score": v["score"], "groups": [r["sites"] for r in v["groups"]]}
                            for k, v in partition["solutions"].items()
                        }
                    if iteration < rounds:
                        record["pool_expansion"] = expand(pool, joint["sorties"], evaluator,
                                                           batteries, expansion_limit)
                else:
                    record["audit_failure"] = "candidate rejected; no Q4 export"
            else:
                record["q3_status"] = search["status"]
                if iteration < rounds:
                    record["pool_expansion"] = expand(pool, hint, evaluator, batteries, expansion_limit)
                    links = LinkEvaluator()
                    try:
                        candidate_locations = locations(links, expanded=True)
                    finally:
                        links.close()
                    record["expanded_relay_locations"] = len(candidate_locations)
                    save_json(output / "relay_locations.json", candidate_locations)
            history.append(record)
            save_json(output / "feedback_history.json", history)
        save_json(output / "patterns.json", [{
            "pattern": p.code, "boxes": [b.code for b in p.sortie.boxes],
            "route": p.sortie.route, "aircraft": p.sortie.aircraft,
            "energy_kwh": p.sortie.energy_kwh, "duration_s": p.duration,
            "charge_s": p.charge, "delivery_offsets_s": p.deliveries,
        } for p in pool])
        if best_q2:
            write_outputs(best_q2[0]["sorties"], best_q2[1], boxes, output / "q2", .2, 1.)
            assumptions = output / "q2/model_assumptions.json"
            data = json.loads(assumptions.read_text())
            data["solver"] = "shared optional patterns, CP-SAT joint exact cover and scheduling"
            data["global_optimal"] = False
            save_json(assumptions, data)
        if best_joint:
            chosen = output / f"iteration_{best_joint['iteration']:02d}"
            shutil.copytree(chosen / "q3", output / "q3")
            shutil.copytree(chosen / "q4", output / "q4")
            _plot_problem3_overview(output / "q3/routes_relays.png",
                                   build_trajectory(best_joint["result"]["sorties"]),
                                   best_joint["result"]["relays"])
            save_json(output / "q4/frozen_q3_sha256.json", snapshot(output / "q3"))
        summary = {
            "feasible": best_q2 is not None and best_joint is not None,
            "status": "certified joint incumbent with frozen K=2/K=3 partitions" if best_joint else "no certified joint incumbent within search limits",
            "global_optimal": False, "pattern_count": len(pool), "history": history,
            "q2": {"iteration": best_q2[2], "score": transport_score(best_q2[1])} if best_q2 else None,
            "q3_q4": {"iteration": best_joint["iteration"], "score": best_joint["score"],
                      "transport_sorties": best_joint["metrics"]["transport_sortie_count"],
                      "relay_sorties": best_joint["metrics"]["relay_sortie_count"],
                      "partitions": best_joint["partition"]["solutions"]} if best_joint else None,
        }
        save_json(output / "summary.json", summary)
        sources = sorted((ROOT / "data/无人机应急物资运输基础数据").glob("*.xlsx")) + [DEM_PATH]
        save_json(output / "manifest.json", {
            "python": platform.python_version(),
            "packages": package_versions(),
            "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources},
            "parameters": dict(rounds=rounds, time_limit=time_limit, max_relays=max_relays,
                               expansion_limit=expansion_limit,
                               profile_cache=str(profile_cache) if profile_cache else None),
            "source_sha256": {str(p.relative_to(ROOT)): digest(p)
                              for p in (ROOT / "final_code").rglob("*.py")},
        })
        write_program_bundle(output)
        return summary
    finally:
        evaluator.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/unified")
    parser.add_argument("--profile-cache", type=Path)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--time-limit", type=float, default=120.)
    parser.add_argument("--max-relays", type=int, default=10)
    parser.add_argument("--expansion-limit", type=int, default=80)
    args = parser.parse_args()
    if args.rounds < 1 or not math.isfinite(args.time_limit) or args.time_limit <= 0 or args.max_relays < 0 or args.expansion_limit < 1:
        parser.error("rounds, time-limit and expansion-limit must be positive; max-relays must be nonnegative")
    result = run(args.output, args.rounds, args.time_limit, args.max_relays, args.expansion_limit, args.profile_cache)
    print(json.dumps({k: v for k, v in result.items() if k != "history"}, ensure_ascii=False, indent=2))
    if not result["feasible"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
