"""Recompute exported Q2/Q3 physics and communication, then refreeze Q4."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from final_code.problem1.solver import ROOT
from final_code.problem2.transport import RouteEvaluator, _validate, load_resources, load_task_boxes
from final_code.problem2.terrain_audit import audit_clearance
from final_code.problem3.audit import audit_communication, audit_relay_resources, load_saved_q3
from final_code.problem3.trajectory import build_trajectory
from final_code.problem4.solver import run as partition, read_q3
from final_code.replay import load_transport, read_csv
from final_code.run_all import save_json, snapshot


def _same(first, second):
    if isinstance(first, dict):
        return first.keys() == second.keys() and all(_same(first[k], second[k]) for k in first)
    if isinstance(first, list):
        return len(first) == len(second) and all(_same(a, b) for a, b in zip(first, second))
    if isinstance(first, (int, float)):
        return abs(first - second) <= 1e-6
    return first == second


def review(source: Path, output: Path):
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose an empty audit output directory")
    output.mkdir(parents=True, exist_ok=True)
    before = snapshot(source / 'q3')
    boxes = load_task_boxes()
    drones, batteries = load_resources()
    evaluator = RouteEvaluator(.2, 1.)
    report = {'source': str(source.resolve()), 'audit_scope': 'fresh physics and continuous certificates from source workbooks and DEM'}
    try:
        for question in ('q2', 'q3'):
            sorties = load_transport(source / question, evaluator)
            validation = _validate(sorties, boxes, drones, batteries, evaluator)
            validation['terrain_clearance'] = audit_clearance(sorties, evaluator)
            if not validation['feasible'] or not validation['terrain_clearance']['feasible']:
                raise ValueError(f'{question} physical replay failed: {validation}')
            report[question] = validation
            original = json.loads((source / question / ('validation.json' if question == 'q2' else 'screening.json')).read_text())
            recorded = original if question == 'q2' else original['transport_validation']
            for key in ('makespan_s', 'total_energy_kwh', 'weighted_all_expected_tardiness', 'assigned_box_count', 'sortie_count'):
                if not _same(validation[key], recorded[key]):
                    raise ValueError(f'Recorded {question} metric differs from fresh audit: {key}')
            if question == 'q3':
                phases = build_trajectory(sorties)
                saved_phases, relays = load_saved_q3(source / question)
                if not _same([asdict(p) for p in phases], [asdict(p) for p in saved_phases]):
                    # Lists need elementwise comparison for float roundoff.
                    if len(phases) != len(saved_phases) or any(not _same(asdict(a), asdict(b)) for a, b in zip(phases, saved_phases)):
                        raise ValueError('Saved trajectory differs from source-derived transport physics')
                resources = audit_relay_resources(relays)
                by_code = {r['relay_sortie']: r for r in relays}
                rows = read_csv(source / 'q3/communication_audit.csv')
                views = []
                for row in rows:
                    if row['保障方式'] != '中继':
                        continue
                    relay = by_code[row['中继架次编号']]
                    start, end = float(row['开始时刻（s）']), float(row['结束时刻（s）'])
                    if (row['运输架次编号'] not in relay['covered_sorties'].split(',')
                            or start < relay['service_start_s'] - 1e-7 or end > relay['service_end_s'] + 1e-7):
                        raise ValueError('Communication assignment lies outside its frozen relay mission')
                    views.append({**relay, 'covered_sorties': row['运输架次编号'],
                                  'service_start_s': start, 'service_end_s': end})
                _, communication = audit_communication(phases, views, step_s=10., minimum_step_s=.25)
                if not resources['feasible'] or not communication['certified']:
                    raise ValueError(f'Q3 audit failed: {resources}, {communication}')
                report['relay'] = resources
                report['communication'] = communication
                report['joint_makespan_s'] = max([s.return_s for s in sorties] + [r['return_o01_s'] for r in relays])
                report['joint_energy_kwh'] = sum(s.energy_kwh for s in sorties) + sum(r['energy_kwh'] for r in relays)
                for key in ('joint_makespan_s', 'joint_energy_kwh'):
                    if not _same(report[key], original[key]):
                        raise ValueError(f'Recorded joint metric differs from fresh audit: {key}')
                # Cross-check the redundant relay resource export and box mapping.
                _, exported = read_q3(source / 'q3')
                fields = {'准备开始时刻（s）': 'preparation_start_s',
                          '建链完成/服务开始（s）': 'service_start_s',
                          '服务结束时刻（s）': 'service_end_s',
                          '返回O01时刻（s）': 'return_o01_s',
                          '机体再次可用（s）': 'drone_ready_s',
                          '能源组件再次可用（s）': 'charge_complete_s',
                          '架次能耗（kWh）': 'energy_kwh', '返航SOC（%）': 'return_soc_percent'}
                for row in exported:
                    physical = by_code[row['relay_sortie']]
                    if any(not _same(float(row[key]), physical[value]) for key, value in fields.items()):
                        raise ValueError('Relay resource export differs from physical mission')
        report['q4'] = partition(source / 'q3', output / 'q4')
        if snapshot(source / 'q3') != before:
            raise ValueError('Q4 modified the frozen Q3 records')
        save_json(output / 'q4/frozen_q3_sha256.json', before)
        report['passed'] = True
        report['frozen_q3_sha256'] = before
        save_json(output / 'audit.json', report)
        return report
    finally:
        evaluator.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'outputs')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = review(args.source, args.output)
    print(json.dumps({k: result[k] for k in ('passed', 'joint_makespan_s', 'joint_energy_kwh')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
