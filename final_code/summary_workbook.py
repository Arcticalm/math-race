"""Consolidate the Question 1-4 results into one review workbook.

Every sheet is written from the files the solvers already produced, so the
workbook never becomes a second source of truth: rerun the four problems, rerun
this script, and the numbers move together. Full-precision values stay in the
source CSV/JSON files; the workbook rounds floats for readability and names the
file each table came from.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from final_code.problem1.solver import ROOT

HEADER_FILL = PatternFill("solid", fgColor="DCE6F1")
HEADER_FONT = Font(bold=True)
LABEL_FONT = Font(bold=True)
MAX_WIDTH = 42

RESOURCE_LABELS = {
    "A_airframe": "A型运输无人机", "B_airframe": "B型运输无人机", "C_airframe": "C型运输无人机",
    "A_battery": "A型电池组", "B_battery": "B型电池组", "C_battery": "C型电池组",
    "relay_airframe": "中继无人机", "relay_energy": "中继能源组件",
}

Q4_ASSUMPTION_KEYS = ("q3_fixed_schedule", "partition_selection", "relay_partition_rule",
                      "inventory_comparison", "resource_reassignment", "optimality_scope",
                      "workload_statistics", "resource_intervals", "mass_by_group",
                      "partition_search_limit", "inventory_source")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"缺少结果文件: {path}")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def read_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"缺少结果文件: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def cell(value):
    """Round floats for display and turn JSON booleans into readable flags."""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, 6)
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    try:
        number = float(text)
    except ValueError:
        return text
    return int(number) if number.is_integer() and "." not in text else round(number, 6)


def write_table(sheet, headers: list[str], rows: list[list], start_row: int = 1) -> int:
    for column, header in enumerate(headers, 1):
        target = sheet.cell(start_row, column, header)
        target.font = HEADER_FONT
        target.fill = HEADER_FILL
        target.alignment = Alignment(horizontal="center")
    for offset, row in enumerate(rows, start_row + 1):
        for column, value in enumerate(row, 1):
            sheet.cell(offset, column, value)
    widths = [len(str(header)) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            if index < len(widths):
                widths[index] = max(widths[index], len(str(value)))
    for column, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(column)].width = min(MAX_WIDTH, max(9, width + 2))
    if rows:
        sheet.freeze_panes = sheet.cell(start_row + 1, 1)
    return start_row + len(rows) + 1


def write_pairs(sheet, pairs: list[tuple[str, object, str]]) -> int:
    """Write label/value/source rows for the metric and assumption sheets."""
    return write_table(sheet, ["指标", "数值", "来源字段"],
                       [[label, cell(value), source] for label, value, source in pairs])


def write_csv_sheet(workbook: Workbook, name: str, path: Path) -> None:
    rows = read_csv(path)
    sheet = workbook.create_sheet(name)
    if not rows:
        sheet.cell(1, 1, f"{path.name} 为空")
        return
    write_table(sheet, list(rows[0]), [[cell(row.get(h)) for h in rows[0]] for row in rows])


def build_sensitivity_pivot(scenarios: list[dict]) -> tuple[list[str], list[list]]:
    keys = sorted({(row["reserve_fraction"], row["horizontal_energy_scale"]) for row in scenarios},
                  key=lambda item: (float(item[0]), float(item[1])))
    table: dict[tuple[str, str], list] = {}
    for row in scenarios:
        entry = table.setdefault((row["site"], row["aircraft"]), [None] * len(keys))
        entry[keys.index((row["reserve_fraction"], row["horizontal_energy_scale"]))] = \
            cell(row["max_safe_payload_kg"])
    headers = ["服务区", "机型",
               *[f"余量{float(reserve):.0%}_能耗率{float(scale):g}" for reserve, scale in keys]]
    return headers, [[site, aircraft, *values] for (site, aircraft), values in sorted(table.items())]


def communication_sheets(workbook: Workbook, screening: dict, source: Path) -> None:
    per_sortie: dict[str, dict] = defaultdict(lambda: {"counts": defaultdict(int),
                                                       "durations": defaultdict(float),
                                                       "relays": set()})
    mode_durations: dict[str, float] = defaultdict(float)
    for row in read_csv(source / "communication_audit.csv"):
        mode = row["保障方式"]
        span = max(0.0, float(row["结束时刻（s）"]) - float(row["开始时刻（s）"]))
        entry = per_sortie[row["运输架次编号"]]
        entry["counts"][mode] += 1
        entry["durations"][mode] += span
        if row["中继架次编号"]:
            entry["relays"].add(row["中继架次编号"])
        mode_durations[mode] += span
    write_table(workbook.create_sheet("Q3_通信保障"),
                ["运输架次编号", "直连区间数", "直连时长（s）", "中继区间数", "中继时长（s）",
                 "中断区间数", "保障中继架次"],
                [[sortie, entry["counts"]["直连"], round(entry["durations"]["直连"], 6),
                  entry["counts"]["中继"], round(entry["durations"]["中继"], 6),
                  entry["counts"]["中断"], ",".join(sorted(entry["relays"]))]
                 for sortie, entry in sorted(per_sortie.items())])

    certificate = screening["continuous_communication_validation"]
    relay = screening["relay_validation"]
    path = "screening.json: continuous_communication_validation"
    write_pairs(workbook.create_sheet("Q3_通信认证"), [
        ("认证版本", certificate["audit_version"], f"{path}.audit_version"),
        ("认证方法", certificate["method"], f"{path}.method"),
        ("认证区间总数", certificate["interval_count"], f"{path}.interval_count"),
        ("未覆盖区间数", certificate["uncovered_interval_count"], f"{path}.uncovered_interval_count"),
        ("未认证通信时长上界（s）", certificate["communication_outage_s"], f"{path}.communication_outage_s"),
        ("未获证书时长（s）", certificate["uncertified_interval_s"], f"{path}.uncertified_interval_s"),
        ("中断时长是否为上界", certificate["communication_outage_is_upper_bound"], f"{path}.communication_outage_is_upper_bound"),
        ("连续通信是否认证通过", certificate["certified"], f"{path}.certified"),
        ("最小认证细分（s）", certificate["minimum_certification_step_s"], f"{path}.minimum_certification_step_s"),
        ("直连保障总时长（s）", round(mode_durations["直连"], 6), "由 communication_audit.csv 汇总"),
        ("中继保障总时长（s）", round(mode_durations["中继"], 6), "由 communication_audit.csv 汇总"),
        ("中继任务数", relay["mission_count"], "screening.json: relay_validation.mission_count"),
        ("中继资源冲突数", relay["resource_conflict_count"], "screening.json: relay_validation.resource_conflict_count"),
        ("中继资源是否可行", relay["feasible"], "screening.json: relay_validation.feasible"),
    ])


def relay_sheet(workbook: Workbook, source: Path) -> None:
    rows = read_csv(source / "relay_schedule.csv")
    headers = ["中继架次编号", "中继无人机编号", "能源组件编号", "悬停经度", "悬停纬度", "离地高度（m）",
               "悬停海拔（m）", "准备开始（s）", "服务开始（s）", "服务结束（s）", "返回O01（s）",
               "机体再次可用（s）", "能源再次可用（s）", "架次能耗（kWh）", "返航SOC（%）", "保障运输架次"]
    keys = ["relay_sortie", "relay_drone", "energy_component", "longitude", "latitude", "agl_m",
            "hover_altitude_m", "preparation_start_s", "service_start_s", "service_end_s",
            "return_o01_s", "drone_ready_s", "charge_complete_s", "energy_kwh", "return_soc_percent",
            "covered_sorties"]
    write_table(workbook.create_sheet("Q3_中继任务"), headers,
                [[cell(row[key]) for key in keys] for row in sorted(rows, key=lambda r: r["relay_sortie"])])


def build(problem1: Path, final: Path, output: Path) -> dict:
    workbook = Workbook()
    workbook.remove(workbook.active)
    from os.path import relpath
    q1_rel = relpath(problem1.resolve(), ROOT.resolve())
    final_rel = relpath(final.resolve(), ROOT.resolve())

    q1_sensitivity = read_csv(problem1 / "sensitivity_summary.csv")
    q1_payloads = read_csv(problem1 / "safe_payloads.csv")
    q1_batches = read_csv(problem1 / "batches.csv")
    q1_detailed = read_csv(problem1 / "batches_detailed.csv")
    q1_summary = read_csv(problem1 / "service_area_summary.csv")
    q1_scenarios = read_csv(problem1 / "safe_payloads_sensitivity.csv")
    q2 = read_json(final / "q2/validation.json")
    q3 = read_json(final / "q3/screening.json")
    q4 = read_json(final / "q4/result.json")
    summary = read_json(final / "summary.json")
    assumptions = read_json(final / "q4/assumptions.json")

    origin = summary.get("q3_q4", {})
    manifest = (final / origin["provenance"] if origin.get("provenance")
                else Path(origin.get("source", ""))) / "manifest.json"
    parameters = read_json(manifest)["parameters"] if manifest.exists() else {}
    baseline = next(row for row in q1_sensitivity
                    if row["reserve_fraction"] == "0.2" and row["horizontal_energy_scale"] == "1.0")
    infeasible = [row["reserve_fraction"] for row in q1_sensitivity if row["feasible"] == "False"]
    inventory = read_csv(final / "q4/inventory_comparison.csv")
    deficits = {k: sum(int(row["inventory_deficit"]) for row in inventory if row["K"] == k)
                for k in ("2", "3")}
    q3_search = q3["search"]
    transport = q3["transport_validation"]
    q2_clearance, q3_clearance = q2["terrain_clearance"], q3["terrain_clearance"]
    q4_k2, q4_k3 = q4["solutions"]["2"], q4["solutions"]["3"]

    readme = workbook.create_sheet("说明")
    readme.column_dimensions["A"].width = 22
    readme.column_dimensions["B"].width = 100
    for index, (label, text) in enumerate([
        ("工作簿内容", "本题四问结果汇总，编排顺序为 总览、第一问、第二问、第三问、第四问。"),
        ("数据来源", f"第一问 {q1_rel}/；第二问 {final_rel}/q2/；第三问 {final_rel}/q3/；"
                     f"第四问 {final_rel}/q4/。"),
        ("生成方式", "python -m final_code.summary_workbook，读取各问已产出的 CSV/JSON 汇总，不重新求解。"),
        ("数值精度", "浮点数统一四舍五入到 6 位小数；完整精度以各问源文件为准。"),
        ("列名口径", "直接搬运源文件的表格沿用源文件列名（第一、四问部分文件为英文字段），"
                     "便于与源 CSV 逐列对照；本工作簿自行汇总的表格（总览、各指标表、"
                     "Q1_安全载荷敏感性、Q3_通信保障）使用中文指标名并在末列标注来源字段。"),
        ("第三问范围", f"第三问预留分区组数（0 表示独立范围）：required_partition_groups="
                       f"{q3_search['required_partition_groups']}，"
                       f"three_group_compatibility_required="
                       f"{q3_search['three_group_compatibility_required']}。"),
        ("第四问口径", "按运输架次和中继保障关系共同合并为原子单元；每个冻结任务恰好归属一个组，不复制、不拆分、不改时刻。"),
        ("第四问枚举", "K=2 与 K=3 均不设候选上限，完整枚举，详见「Q4_口径与最优性」。"),
        ("最优性", f"global_optimal={summary['global_optimal']}；结果为通过审计与回代的最好已知候选，"
                   f"未证明原题全局最优。"),
        ("读表提示", "「Q1_余量敏感性」的 box_count 是题目货箱总数（80），不是该场景的交付箱数；"
                     "feasible 为 False 表示至少一个服务区不可行，因而无法完成全体 80 箱交付，架次、能耗、时间列为空，"
                     "不做部分交付。"),
        ("字典序目标", "第二、三问按「完成时间 → 加权迟到 → 总能耗 → 架次数」；第四问按「库存缺口 → 资源总数 → 最大工作量 CV」。"),
        ("运行参数", "；".join(f"{key}={value}" for key, value in parameters.items())
                     or "见 provenance/ 中的运行记录。"),
        ("权威副本", f"各问结果以其自身目录为准：第一问 {q1_rel}/，第二至四问 {final_rel}/。"),
        ("完整报告", f"{final_rel}/REPORT.md。"),
    ], 1):
        readme.cell(index, 1, label).font = LABEL_FONT
        readme.cell(index, 2, text).alignment = Alignment(wrap_text=True, vertical="top")

    write_table(workbook.create_sheet("总览"), ["问题", "指标", "数值", "来源文件"], [
        ["一", "参与机型数", len({row["aircraft"] for row in q1_payloads}), "safe_payloads.csv"],
        ["一", "基准场景（余量20%、能耗率1.0）交付箱数", baseline["box_count"], "sensitivity_summary.csv"],
        ["一", "基准场景往返架次数", baseline["flight_count"], "sensitivity_summary.csv"],
        ["一", "基准场景总能耗（kWh）", cell(baseline["total_energy_kwh"]), "sensitivity_summary.csv"],
        ["一", "基准场景累计作业时间（s）", cell(baseline["total_work_time_s"]), "sensitivity_summary.csv"],
        ["一", "敏感性场景数", len(q1_sensitivity), "sensitivity_summary.csv"],
        ["一", "不可行的返航余量场景", ",".join(infeasible) or "无", "sensitivity_summary.csv"],
        ["二", "完成时间（s）", cell(q2["makespan_s"]), "q2/validation.json"],
        ["二", "运输架次", q2["sortie_count"], "q2/validation.json"],
        ["二", "总能耗（kWh）", cell(q2["total_energy_kwh"]), "q2/validation.json"],
        ["二", "交付货箱数", f"{q2['assigned_box_count']}/{q2['box_count']}", "q2/validation.json"],
        ["二", "期望时间内送达", f"{q2['all_expected_on_time_count']}/{q2['all_due_box_count']}",
         "q2/validation.json"],
        ["二", "加权迟到（优先权重 × s）", cell(q2["weighted_all_expected_tardiness"]),
         "q2/validation.json"],
        ["二", "硬时限通过", f"{q2['hard_deadline_compliant_count']}/{q2['hard_deadline_check_count']}",
         "q2/validation.json"],
        ["二", "巡航最小净空（m）", cell(q2_clearance["minimum_clearance_m"]), "q2/validation.json"],
        ["三", "联合完成时间（s）", cell(q3["joint_makespan_s"]), "q3/screening.json"],
        ["三", "运输架次", q3["transport_sortie_count"], "q3/screening.json"],
        ["三", "中继架次", q3["relay_sortie_count"], "q3/screening.json"],
        ["三", "运输与中继总能耗（kWh）", cell(q3["joint_energy_kwh"]), "q3/screening.json"],
        ["三", "交付货箱数", f"{transport['assigned_box_count']}/{transport['box_count']}",
         "q3/screening.json"],
        ["三", "期望时间内送达",
         f"{transport['all_expected_on_time_count']}/{transport['all_due_box_count']}",
         "q3/screening.json"],
        ["三", "加权迟到（优先权重 × s）", cell(transport["weighted_all_expected_tardiness"]),
         "q3/screening.json"],
        ["三", "硬时限通过",
         f"{transport['hard_deadline_compliant_count']}/{transport['hard_deadline_check_count']}",
         "q3/screening.json"],
        ["三", "未认证通信时长上界（s）",
         cell(q3["continuous_communication_validation"]["communication_outage_s"]),
         "q3/screening.json"],
        ["三", "中继资源冲突数", q3["relay_validation"]["resource_conflict_count"], "q3/screening.json"],
        ["三", "巡航最小净空（m）", cell(q3_clearance["minimum_clearance_m"]), "q3/screening.json"],
        ["四", "原子任务单元数", len(q4["atomic_units"]), "q4/result.json"],
        ["四", "K=2 是否可行", q4_k2["feasible"], "q4/result.json"],
        ["四", "K=2 候选分区数", q4_k2["candidate_count"], "q4/result.json"],
        ["四", "K=2 库存缺口合计", deficits["2"], "q4/inventory_comparison.csv"],
        ["四", "K=2 资源需求总量", cell(q4_k2.get("score", [None, None, None])[1]), "q4/result.json"],
        ["四", "K=2 最大工作量 CV", cell(q4_k2.get("score", [None, None, None])[2]), "q4/result.json"],
        ["四", "K=3 是否可行", q4_k3["feasible"], "q4/result.json"],
        ["四", "K=3 候选分区数", q4_k3["candidate_count"], "q4/result.json"],
        ["四", "K=3 库存缺口合计", deficits["3"], "q4/inventory_comparison.csv"],
        ["四", "K=3 资源需求总量", cell(q4_k3.get("score", [None, None, None])[1]), "q4/result.json"],
        ["四", "K=3 最大工作量 CV", cell(q4_k3.get("score", [None, None, None])[2]), "q4/result.json"],
    ])

    write_table(workbook.create_sheet("Q1_最大安全载荷"), list(q1_payloads[0]),
                [[cell(row[h]) for h in q1_payloads[0]] for row in q1_payloads])
    write_table(workbook.create_sheet("Q1_组批方案"), list(q1_batches[0]),
                [[cell(row[h]) for h in q1_batches[0]] for row in q1_batches])
    write_table(workbook.create_sheet("Q1_组批能耗明细"), list(q1_detailed[0]),
                [[cell(row[h]) for h in q1_detailed[0]] for row in q1_detailed])
    write_table(workbook.create_sheet("Q1_服务区汇总"), list(q1_summary[0]),
                [[cell(row[h]) for h in q1_summary[0]] for row in q1_summary])
    sensitivity_keys = list(q1_sensitivity[0])
    ordered = sorted(q1_sensitivity, key=lambda row: (float(row["reserve_fraction"]),
                                                      float(row["horizontal_energy_scale"])))
    write_table(workbook.create_sheet("Q1_余量敏感性"), sensitivity_keys,
                [[cell(row[h]) for h in sensitivity_keys] for row in ordered])
    headers, rows = build_sensitivity_pivot(q1_scenarios)
    write_table(workbook.create_sheet("Q1_安全载荷敏感性"), headers, rows)

    write_pairs(workbook.create_sheet("Q2_指标"), [
        ("是否通过审计", q2["feasible"], "validation.json: feasible"),
        ("回代审计版本", q2["audit_version"], "validation.json: audit_version"),
        ("完成时间（s）", q2["makespan_s"], "validation.json: makespan_s"),
        ("运输架次", q2["sortie_count"], "validation.json: sortie_count"),
        ("交付货箱数", q2["assigned_box_count"], "validation.json: assigned_box_count"),
        ("应交付货箱数", q2["box_count"], "validation.json: box_count"),
        ("总能耗（kWh）", q2["total_energy_kwh"], "validation.json: total_energy_kwh"),
        ("期望时间内送达箱数", q2["all_expected_on_time_count"],
         "validation.json: all_expected_on_time_count"),
        ("期望时间准时率", q2["all_expected_on_time_rate"], "validation.json: all_expected_on_time_rate"),
        ("期望时间迟到合计（s）", q2["all_expected_tardiness_s"],
         "validation.json: all_expected_tardiness_s"),
        ("加权迟到（优先权重 × s）", q2["weighted_all_expected_tardiness"],
         "validation.json: weighted_all_expected_tardiness"),
        ("软时限准时率", q2["soft_on_time_rate"], "validation.json: soft_on_time_rate"),
        ("硬时限检查次数", q2["hard_deadline_check_count"], "validation.json: hard_deadline_check_count"),
        ("硬时限通过次数", q2["hard_deadline_compliant_count"],
         "validation.json: hard_deadline_compliant_count"),
        ("硬时限是否全部通过", q2["hard_deadlines_feasible"], "validation.json: hard_deadlines_feasible"),
        ("资源排程是否可行", q2["resource_schedule_feasible"],
         "validation.json: resource_schedule_feasible"),
        ("物理与时间轴是否可行", q2["physics_and_timeline_feasible"],
         "validation.json: physics_and_timeline_feasible"),
        ("目标优先策略", q2["objective_profile"], "validation.json: objective_profile"),
        ("巡航最小净空（m）", q2_clearance["minimum_clearance_m"],
         "validation.json: terrain_clearance.minimum_clearance_m"),
        ("巡航净空要求（m）", q2_clearance["required_clearance_m"],
         "validation.json: terrain_clearance.required_clearance_m"),
        ("巡航净空违规航段数", q2_clearance["violation_count"],
         "validation.json: terrain_clearance.violation_count"),
        ("净空审计航段数", q2_clearance["leg_count"], "validation.json: terrain_clearance.leg_count"),
    ])
    for name, relative in (("Q2_架次安排", "q2/sorties_audit.csv"),
                           ("Q2_逐箱交付", "q2/box_delivery_audit.csv"),
                           ("Q2_电池周转", "q2/battery_audit.csv"),
                           ("Q2_航段明细", "q2/route_segments.csv")):
        write_csv_sheet(workbook, name, final / relative)

    write_pairs(workbook.create_sheet("Q3_联合指标"), [
        ("是否可行", q3["feasible"], "screening.json: feasible"),
        ("联合完成时间（s）", q3["joint_makespan_s"], "screening.json: joint_makespan_s"),
        ("运输架次", q3["transport_sortie_count"], "screening.json: transport_sortie_count"),
        ("中继架次", q3["relay_sortie_count"], "screening.json: relay_sortie_count"),
        ("总架次数", q3["total_sortie_count"], "screening.json: total_sortie_count"),
        ("运输与中继总能耗（kWh）", q3["joint_energy_kwh"], "screening.json: joint_energy_kwh"),
        ("运输能耗（kWh）", transport["total_energy_kwh"],
         "screening.json: transport_validation.total_energy_kwh"),
        ("交付货箱数", transport["assigned_box_count"],
         "screening.json: transport_validation.assigned_box_count"),
        ("期望时间内送达箱数", transport["all_expected_on_time_count"],
         "screening.json: transport_validation.all_expected_on_time_count"),
        ("期望时间迟到合计（s）", transport["all_expected_tardiness_s"],
         "screening.json: transport_validation.all_expected_tardiness_s"),
        ("加权迟到（优先权重 × s）", transport["weighted_all_expected_tardiness"],
         "screening.json: transport_validation.weighted_all_expected_tardiness"),
        ("硬时限是否全部通过", transport["hard_deadlines_feasible"],
         "screening.json: transport_validation.hard_deadlines_feasible"),
        ("硬时限通过次数", transport["hard_deadline_compliant_count"],
         "screening.json: transport_validation.hard_deadline_compliant_count"),
        ("连续通信是否认证通过", q3["continuity_certified"], "screening.json: continuity_certified"),
        ("巡航最小净空（m）", q3_clearance["minimum_clearance_m"],
         "screening.json: terrain_clearance.minimum_clearance_m"),
        ("巡航净空违规航段数", q3_clearance["violation_count"],
         "screening.json: terrain_clearance.violation_count"),
        ("中继资源冲突数", q3["relay_validation"]["resource_conflict_count"],
         "screening.json: relay_validation.resource_conflict_count"),
        ("搜索状态", q3_search["status"], "screening.json: search.status"),
        ("字典序链是否精确最优", q3_search["restricted_lexicographic_optimal"],
         "screening.json: search.restricted_lexicographic_optimal"),
        ("分区约束组数（独立第三问为 0）", q3_search["required_partition_groups"],
         "screening.json: search.required_partition_groups"),
        ("模式库规模", q3_search["pattern_count"], "screening.json: search.pattern_count"),
        ("最多中继任务数", q3_search["max_relay_missions"], "screening.json: search.max_relay_missions"),
        ("整数模型完成时间（s）", q3_search["integer_makespan_s"],
         "screening.json: search.integer_makespan_s"),
    ])
    write_table(workbook.create_sheet("Q3_字典序阶段"), ["阶段", "目标", "当前上界", "下界", "状态"],
                [[index, stage["objective"], cell(stage["incumbent"]), cell(stage["lower_bound"]),
                  stage["status"]] for index, stage in enumerate(q3_search["stages"], 1)])
    write_csv_sheet(workbook, "Q3_运输架次", final / "q3/transport_inherited_audit.csv")
    relay_sheet(workbook, final / "q3")
    write_csv_sheet(workbook, "Q3_逐箱交付", final / "q3/box_delivery_audit.csv")
    communication_sheets(workbook, q3, final / "q3")

    configuration = read_csv(final / "q4/problem4_configuration.csv")
    write_table(workbook.create_sheet("Q4_分区配置"), list(configuration[0]) if configuration else ["K", "状态"],
                [[cell(row[h]) for h in configuration[0]] for row in configuration])
    write_table(workbook.create_sheet("Q4_库存对照"),
                ["K", "资源", "资源名称", "现有库存", "各组需求", "需求合计", "未分区全局峰值",
                 "分区增加量", "库存缺口", "库存余量", "缺口原因", "统计口径"],
                [[cell(row["K"]), row["resource"], RESOURCE_LABELS.get(row["resource"], row["resource"]),
                  cell(row["inventory"]), row["group_demands"], cell(row["total_demand"]),
                  cell(row["global_peak"]), cell(row["partition_overhead"]),
                  cell(row["inventory_deficit"]), cell(row["inventory_surplus"]),
                  row["deficit_reason"], row["inventory_scope"]] for row in inventory])
    workload = read_csv(final / "q4/workload_comparison.csv")
    write_table(workbook.create_sheet("Q4_工作量对照"), list(workload[0]) if workload else ["K", "状态"],
                [[cell(row[h]) for h in workload[0]] for row in workload])
    write_csv_sheet(workbook, "Q4_任务映射", final / "q4/task_mapping_audit.csv")
    site_map = read_csv(final / "q4/site_mapping_audit.csv")
    write_table(workbook.create_sheet("Q4_服务区归属"), list(site_map[0]) if site_map else ["K", "状态"],
                [[cell(row[h]) for h in site_map[0]] for row in site_map])

    pairs = [("原子任务单元数", len(q4["atomic_units"]), "result.json: atomic_units"),
             ("原子任务单元", "; ".join(",".join(unit) for unit in q4["atomic_units"]),
              "result.json: atomic_units"),
             ("冻结的第三问输入哈希", q4["frozen_input_sha256"], "result.json: frozen_input_sha256")]
    for k in ("2", "3"):
        solution = q4["solutions"][k]
        pairs += [
            (f"K={k} 是否可行", solution["feasible"], f"result.json: solutions.{k}.feasible"),
            (f"K={k} 候选分区数", solution.get("candidate_count"),
             f"result.json: solutions.{k}.candidate_count"),
            (f"K={k} 分区搜索是否完整", solution.get("partition_search_complete"),
             f"result.json: solutions.{k}.partition_search_complete"),
            (f"K={k} 库存是否足够", solution.get("inventory_feasible"),
             f"result.json: solutions.{k}.inventory_feasible"),
            (f"K={k} 打分（库存缺口, 资源总量, 最大CV）",
             ", ".join(str(cell(item)) for item in solution.get("score") or []),
             f"result.json: solutions.{k}.score"),
            (f"K={k} 跨组共享的中继任务", "; ".join(solution.get("shared_relay_missions") or []) or "无",
             f"result.json: solutions.{k}.shared_relay_missions"),
            (f"K={k} 最优性范围", solution.get("optimality_scope"),
             f"result.json: solutions.{k}.optimality_scope"),
            (f"K={k} 选择规则", solution.get("selection_rule"),
             f"result.json: solutions.{k}.selection_rule"),
        ]
    for key in Q4_ASSUMPTION_KEYS:
        if key in assumptions:
            pairs.append((f"假设：{key}", assumptions[key], f"assumptions.json: {key}"))
    write_pairs(workbook.create_sheet("Q4_口径与最优性"), pairs)

    output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output)
    return {"output": output.as_posix(), "sheets": [sheet.title for sheet in workbook.worksheets]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--problem1", type=Path, default=ROOT / "outputs/q1")
    parser.add_argument("--final", type=Path, default=ROOT / "outputs")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/四问指标汇总.xlsx")
    args = parser.parse_args()
    result = build(args.problem1, args.final, args.output)
    print(json.dumps({"output": result["output"], "sheet_count": len(result["sheets"])},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
