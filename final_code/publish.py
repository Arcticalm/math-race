"""Publish the selected Q1–Q4 workbooks and comparable figures at one location."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from final_code.run_all import digest
from final_code.problem1.solver import ROOT, load_nodes
from final_code.problem2.transport import load_task_boxes
from final_code.problem2.terrain_audit import write_clearance_outputs
from final_code.problem4.solver import SITES, q3_gate, validate_frozen_partition


COLORS = {"A": "#2878b5", "B": "#e07a24", "C": "#37966f", "relay": "#7952a1"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def save(figure, path: Path) -> None:
    figure.savefig(path, dpi=180)
    plt.close(figure)


def candidate_rows(source: Path, summary=None):
    if summary is not None:
        records = {}
        for key, score_key in (("q2_candidates", "q2_score"), ("joint_candidates", "joint_score")):
            for candidate in summary.get(key, []):
                name = Path(candidate["source"]).name
                row = records.setdefault(name, {"run": name, "iteration": "best"})
                row[score_key] = candidate["score"]
        return list(records.values())
    rows = []
    for root in sorted(source.iterdir()):
        path = root / "feedback_history.json"
        if not path.exists():
            continue
        for item in json.loads(path.read_text(encoding="utf-8")):
            rows.append({"run": root.name, **item})
    return rows


def time_tradeoff(rows, selected, output):
    points = [row for row in rows if row.get("q2_score")]
    if not points:
        raise ValueError("No Q2 candidates available for the tradeoff chart")
    figure, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
    for row in points:
        time_s, late, energy, count = row["q2_score"]
        chosen = row["run"] == selected["run"] and abs(time_s - selected["time_s"]) < 1e-6
        color = "#c0392b" if chosen else "#2878b5"
        for axis, horizontal in zip(axes, (count, late)):
            axis.scatter(horizontal, time_s, color=color, s=90 if chosen else 45,
                         edgecolor="white", linewidth=.5, zorder=3)
            axis.annotate(f"{row['run']}-{row['iteration']}", (horizontal, time_s),
                          xytext=(4, 4), textcoords="offset points", fontsize=8)
    axes[0].set(xlabel="Transport sorties", ylabel="Completion time (s)",
                title="Completion time and sorties")
    axes[1].set(xlabel="Weighted tardiness (priority × s)", ylabel="Completion time (s)",
                title="Completion time and delivery timeliness")
    for axis in axes:
        axis.grid(alpha=.25)
        axis.scatter([], [], color="#c0392b", label="Selected")
        axis.scatter([], [], color="#2878b5", label="Other audited candidate")
        axis.legend(fontsize=8)
    save(figure, output)
    return points


def joint_tradeoff(rows, selected, output):
    points = [row for row in rows if row.get("joint_score")]
    if not points:
        raise ValueError("No Q3 candidates available for the tradeoff chart")
    # An independently solved Q3 carries no frozen-partition terms, so the second
    # panel falls back to the joint sortie count instead of a partition deficit.
    coupled = len(points[0]["joint_score"]) > 4
    figure, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
    for row in points:
        time_s, late, energy, sorties = row["joint_score"][:4]
        deficit = row["joint_score"][5] if coupled else 0
        chosen = row["run"] == selected["run"] and abs(time_s - selected["time_s"]) < 1e-6
        color = "#c0392b" if chosen else "#2878b5"
        for axis, horizontal in zip(axes, (energy, deficit if coupled else sorties)):
            axis.scatter(horizontal, time_s, color=color, s=90 if chosen else 45,
                         edgecolor="white", linewidth=.5, zorder=3)
            axis.annotate(f"{row['run']}-{row['iteration']}", (horizontal, time_s),
                          xytext=(4, 4), textcoords="offset points", fontsize=8)
    axes[0].set(xlabel="Joint energy (kWh)", ylabel="Joint completion time (s)",
                title="Completion time and energy")
    axes[1].set(xlabel="K=2 + K=3 resource deficit" if coupled else "Joint sortie count",
                ylabel="Joint completion time (s)",
                title="Completion time and partition deficit" if coupled
                else "Completion time and sorties")
    for axis in axes:
        axis.grid(alpha=.25)
        axis.scatter([], [], color="#c0392b", label="Selected")
        axis.scatter([], [], color="#2878b5", label="Other certified candidate")
        axis.legend(fontsize=8)
    save(figure, output)
    return points


def relay_gantt(source: Path, output: Path):
    transport = read_csv(source / "q3/transport_inherited_audit.csv")
    relays = read_csv(source / "q3/relay_resource_audit.csv")
    aircraft = sorted({row["无人机编号"] for row in transport}
                      | {row["中继无人机编号"] for row in relays})
    batteries = sorted({row["电池编号"] for row in transport}
                       | {row["能源组件编号"] for row in relays})
    figure, axes = plt.subplots(2, 1, figsize=(14, max(9, .39 * (len(aircraft) + len(batteries)))),
                                sharex=True, layout="constrained")
    indices = [{name: index for index, name in enumerate(group)} for group in (aircraft, batteries)]
    for row in transport:
        start = float(row["准备开始时刻（s）"])
        returned = float(row["返回O01时刻（s）"])
        charged = float(row["电池充电完成时刻（s）"])
        color = COLORS[row["机型编号"]]
        for axis, name, index in ((axes[0], row["无人机编号"], 0),
                                  (axes[1], row["电池编号"], 1)):
            axis.broken_barh([(start, returned - start)], (indices[index][name] - .35, .7),
                             facecolors=color, edgecolors="white", linewidth=.4)
        if charged > returned:
            axes[1].broken_barh([(returned, charged - returned)],
                                (indices[1][row["电池编号"]] - .35, .7),
                                facecolors="#a8dadc", edgecolors="white", linewidth=.4)
    for row in relays:
        start = float(row["准备开始时刻（s）"])
        returned = float(row["返回O01时刻（s）"])
        drone_end = float(row["机体再次可用（s）"])
        charged = float(row["能源组件再次可用（s）"])
        for axis, name, index, end in ((axes[0], row["中继无人机编号"], 0, drone_end),
                                        (axes[1], row["能源组件编号"], 1, returned)):
            axis.broken_barh([(start, end - start)], (indices[index][name] - .35, .7),
                             facecolors=COLORS["relay"], edgecolors="white", linewidth=.4)
        if charged > returned:
            axes[1].broken_barh([(returned, charged - returned)],
                                (indices[1][row["能源组件编号"]] - .35, .7),
                                facecolors="#a8dadc", edgecolors="white", linewidth=.4)
    for axis, group in zip(axes, (aircraft, batteries)):
        axis.set_yticks(range(len(group)), group, fontsize=8)
        axis.grid(axis="x", alpha=.25)
    axes[0].set(title="Joint transport and relay resource schedule", ylabel="Aircraft")
    axes[1].set(xlabel="Time (s)", ylabel="Battery / energy component")
    for label, color in (("Transport A", COLORS["A"]), ("Transport B", COLORS["B"]),
                         ("Transport C", COLORS["C"]), ("Relay", COLORS["relay"]),
                         ("Recharge", "#a8dadc")):
        axes[0].barh([], [], color=color, label=label)
    axes[0].legend(ncol=5, loc="upper center", bbox_to_anchor=(.5, 1.04), fontsize=8)
    save(figure, output)


def delivery_chart(source: Path, output: Path):
    actual = {row["货箱编号"]: float(row["交付完成时刻（s）"])
              for row in read_csv(source / "q3/box_delivery_audit.csv")}
    boxes = sorted((box for box in load_task_boxes() if box.due_s is not None),
                   key=lambda box: (box.due_s, box.site, box.code))
    if set(actual) != {box.code for box in load_task_boxes()}:
        raise ValueError("Q3 delivery chart requires exactly the source box set")
    figure, axis = plt.subplots(figsize=(12, 11), layout="constrained")
    for index, box in enumerate(boxes):
        delivered = actual[box.code]
        color = "#d97721" if delivered > box.due_s + 1e-7 else "#2878b5"
        axis.plot([box.due_s, delivered], [index, index], color=color, linewidth=.75, alpha=.7)
        axis.scatter([box.due_s], [index], marker="|", s=75, color="#d1495b")
        axis.scatter([delivered], [index], s=19, color=color)
    axis.set_yticks(range(len(boxes)), [box.code for box in boxes], fontsize=5.8)
    axis.set(xlabel="Delivery time (s); red tick = expected time",
             title="Problem 3 actual and expected delivery times")
    axis.grid(axis="x", alpha=.25)
    save(figure, output)


def communication_chart(source: Path, output: Path):
    rows = read_csv(source / "q3/communication_audit.csv")
    by_sortie = defaultdict(list)
    for row in rows:
        mode = row["保障方式"]
        if mode not in {"直连", "中继"}:
            raise ValueError("Selected Q3 communication audit contains an outage")
        by_sortie[row["运输架次编号"]].append((float(row["开始时刻（s）"]),
                                             float(row["结束时刻（s）"]), mode))
    figure, axis = plt.subplots(figsize=(14, max(8, .32 * len(by_sortie))), layout="constrained")
    palette = {"直连": "#2878b5", "中继": COLORS["relay"]}
    for index, (code, cells) in enumerate(sorted(by_sortie.items())):
        merged = []
        for start, end, mode in sorted(cells):
            if merged and merged[-1][2] == mode and abs(merged[-1][1] - start) <= 1e-6:
                merged[-1] = (merged[-1][0], end, mode)
            else:
                merged.append((start, end, mode))
        for start, end, mode in merged:
            axis.broken_barh([(start, end - start)], (index - .35, .7),
                             facecolors=palette[mode], edgecolors="none")
    axis.set_yticks(range(len(by_sortie)), sorted(by_sortie), fontsize=7)
    axis.set(xlabel="Time (s)", ylabel="Transport sortie",
             title="Certified communication coverage by transport sortie")
    axis.grid(axis="x", alpha=.25)
    for label, color in (("Direct gateway", palette["直连"]),
                         ("Air relay", palette["中继"])):
        axis.barh([], [], color=color, label=label)
    axis.legend(loc="upper right")
    save(figure, output)


def partition_map(source: Path, output: Path):
    data = json.loads((source / "q4/result.json").read_text(encoding="utf-8"))
    base, sites = load_nodes()
    # A K that the frozen Q3 schedule cannot realise is reported in the tables but
    # has no partition to draw.
    keys = [k for k in ("2", "3") if data["solutions"][k].get("feasible")]
    figure, axes = plt.subplots(1, len(keys), figsize=(7 * len(keys), 6), layout="constrained",
                                sharex=True, sharey=True, squeeze=False)
    palette = ("#2878b5", "#e07a24", "#37966f")
    for axis, k in zip(axes[0], keys):
        groups = data["solutions"][k]["groups"]
        mapping = {site: index for index, row in enumerate(groups)
                   for site in row["sites"].split(",")}
        if set(mapping) != set(SITES):
            raise ValueError(f"K={k} partition does not cover every service area")
        for name in SITES:
            node = sites[name]
            axis.scatter(node.longitude, node.latitude, marker="s", s=75,
                         color=palette[mapping[name]], edgecolor="white", linewidth=.6)
            axis.annotate(name, (node.longitude, node.latitude), xytext=(3, 3),
                          textcoords="offset points", fontsize=7)
        axis.scatter(base.longitude, base.latitude, marker="*", s=180, color="#d1495b", label="O01")
        for index, row in enumerate(groups):
            axis.scatter([], [], marker="s", s=65, color=palette[index],
                         label=f"Group {index + 1} ({row['site_count']} sites)")
        axis.set(title=f"K={k}: deficit {data['solutions'][k]['score'][0]}",
                 xlabel="Longitude (deg)")
        axis.grid(alpha=.25)
        axis.legend(loc="best", fontsize=8)
    axes[0, 0].set_ylabel("Latitude (deg)")
    save(figure, output)


def inventory_chart(source: Path, output: Path):
    rows = read_csv(source / "q4/inventory_comparison.csv")
    present = [k for k in ("2", "3") if any(row["K"] == k for row in rows)]
    if not present:
        raise ValueError("Q4 inventory comparison has no partition rows")
    keys = [row["resource"] for row in rows if row["K"] == present[0]]
    if len(keys) != 8:
        raise ValueError("Q4 inventory chart expects eight named resource types")
    figure, axes = plt.subplots(len(present), 1, figsize=(11, 4 * len(present)),
                                layout="constrained", sharex=True, squeeze=False)
    axes = axes[:, 0]
    for axis, k in zip(axes, present):
        values = {row["resource"]: row for row in rows if row["K"] == k}
        for index, key in enumerate(keys):
            row = values[key]
            stock, required = float(row["inventory"]), float(row["total_demand"])
            axis.bar(index - .18, stock, width=.36, color="#2878b5")
            axis.bar(index + .18, required, width=.36,
                     color="#c0392b" if required > stock else "#37966f")
            if required > stock:
                axis.text(index + .18, required + .15, f"+{required - stock:.0f}",
                          ha="center", fontsize=8, color="#a52a2a")
        axis.set(ylabel="Units", title=f"K={k}: inventory and independent group demand")
        axis.grid(axis="y", alpha=.25)
    axes[-1].set_xticks(range(len(keys)), keys, rotation=30, ha="right", fontsize=8)
    axes[0].bar([], [], color="#2878b5", label="Inventory")
    axes[0].bar([], [], color="#37966f", label="Demand within stock")
    axes[0].bar([], [], color="#c0392b", label="Demand exceeding stock")
    axes[0].legend(ncol=3, loc="upper right", fontsize=8)
    save(figure, output)


def _copy_question(source: Path, target: Path):
    """Keep full-precision records once and place all figures in a subdirectory."""
    target.mkdir(parents=True, exist_ok=True)
    figures = target / "figures"
    figures.mkdir(exist_ok=True)
    if source.resolve() != target.resolve():
        for path in source.iterdir():
            if path.is_file() and path.suffix in (".csv", ".json", ".xlsx"):
                shutil.copy2(path, target / path.name)
        if (source / "figures").exists():
            shutil.copytree(source / "figures", figures, dirs_exist_ok=True)
    for path in source.glob("*.png"):
        shutil.copy2(path, figures / path.name)
    if source.resolve() == target.resolve():
        for path in list(target.glob("*.png")) + list(target.glob("*_program.zip")):
            path.unlink()


def publish(source: Path, output: Path, q1_source: Path | None = None) -> dict:
    """Write the final four-question tree; source schedules are never rescheduled."""
    from final_code.package import write_program_bundle
    from final_code.submission import organize_workbooks
    from final_code.summary_workbook import build as build_summary

    q1_source = q1_source or output / "q1"
    summary = json.loads((source / "summary.json").read_text(encoding="utf-8"))
    q2 = json.loads((source / "q2/validation.json").read_text(encoding="utf-8"))
    q3 = json.loads((source / "q3/screening.json").read_text(encoding="utf-8"))
    q4 = json.loads((source / "q4/result.json").read_text(encoding="utf-8"))
    if not (summary.get("feasible") and q2.get("feasible")
            and q2.get("terrain_clearance", {}).get("feasible")
            and q2.get("audit_version") == "physical_replay_v2"
            and q3_gate(source / "q3")["ready"]):
        raise ValueError("Selected Q2/Q3 solution has not passed the required audits")
    validate_frozen_partition(source / "q3", q4)
    output.mkdir(parents=True, exist_ok=True)
    _copy_question(q1_source, output / "q1")
    for question in ("q2", "q3", "q4"):
        _copy_question(source / question, output / question)
    if source.resolve() != output.resolve():
        for name in ("summary.json", "REPORT.md", "manifest.json"):
            if (source / name).exists():
                shutil.copy2(source / name, output / name)
        for name in ("provenance", "sources"):
            if (source / name).exists():
                shutil.copytree(source / name, output / "provenance", dirs_exist_ok=True)
    counts = organize_workbooks(output)
    build_summary(output / "q1", output, output / "四问指标汇总.xlsx")
    write_clearance_outputs(output / "q2/figures", q2["terrain_clearance"])
    write_clearance_outputs(output / "q3/figures", q3["terrain_clearance"])
    rows = candidate_rows(output, summary)
    if any(row.get("q2_score") for row in rows):
        time_tradeoff(rows, {"run": Path(summary["q2"]["source"]).name,
                            "time_s": summary["q2"]["score"][0]},
                      output / "q2/figures/time_priority_tradeoff.png")
    if any(row.get("joint_score") for row in rows):
        joint_tradeoff(rows, {"run": Path(summary["q3_q4"]["source"]).name,
                             "time_s": summary["q3_q4"]["score"][0]},
                       output / "q3/figures/tradeoff.png")
    relay_gantt(output, output / "q3/figures/resource_gantt.png")
    delivery_chart(output, output / "q3/figures/delivery_times.png")
    communication_chart(output, output / "q3/figures/communication_timeline.png")
    if any(solution.get("feasible") for solution in q4["solutions"].values()):
        partition_map(output, output / "q4/figures/partitions.png")
        inventory_chart(output, output / "q4/figures/inventory.png")
    summary["layout"] = "question_directories_v1"
    summary["artifact_sha256"] = {
        str(path.relative_to(output)): digest(path)
        for question in ("q1", "q2", "q3", "q4")
        for path in (output / question).iterdir()
        if path.is_file() and path.suffix in (".csv", ".json", ".xlsx")}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    readme = ["# 四问最终结果", "",
        "按照 docs/结果提交模板.xlsx 分类；原始精度保留在各问 CSV/JSON，展示表按求解器原有精度导出。", "",
        "- [结果提交汇总](结果提交汇总.xlsx)：原模板 6 张表，加 Q3_运输架次、Q3_逐箱交付两张补充表。",
        "- [四问指标汇总](四问指标汇总.xlsx)：26 张指标、资源和审计明细表。",
        "- [流程与算法](../final_code/四问流程算法与题目审查.md) · [审查报告](REPORT.md)", "",
        "| 问题 | 按模板填写的工作簿 | 明细与图表 |",
        "| --- | --- | --- |",
        "| 一 | [单点组批](q1/problem1_submission.xlsx) | q1/tables；q1/figures |",
        "| 二 | [运输架次及逐箱交付](q2/problem2_submission.xlsx) | q2/tables；q2/figures |",
        "| 三 | [联合运输、中继及通信保障](q3/problem3_submission.xlsx) | q3/tables；q3/figures |",
        "| 四 | [分区配置](q4/problem4_submission.xlsx) | q4/tables；q4/figures |", "",
        "第三问单独工作簿沿用模板中的 Q2_运输架次、Q2_逐箱交付字段承载第三问重选后的运输方案；",
        "它们与独立第二问不同。总表中用新增 Q3_运输架次、Q3_逐箱交付区分，绝不相互覆盖。", "",
        "`provenance/` 保存选中方案的模式、选址和运行来源，`checks/` 保存最终复核和测试证据。",
        "[程序包](程序.zip) 包含四问源码、测试、说明和原模板；[文件清单](deliverables.json) 给出 SHA-256。", "",
        "重新整理：`.venv/bin/python -m final_code.publish`。此命令不重新优化或改动冻结排程。", ""]
    (output / "README.md").write_text("\n".join(readme), encoding="utf-8")
    write_program_bundle(output / "程序.zip")
    files = {str(p.relative_to(output)): digest(p) for p in sorted(output.rglob("*"))
             if p.is_file() and p.name != "deliverables.json" and "__pycache__" not in p.parts}
    result = {"layout": "question_directories_v1", "template": "docs/结果提交模板.xlsx",
              "template_sheet_rows": counts, "global_optimal_q2_q3": False, "files": files}
    (output / "deliverables.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "outputs")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs")
    parser.add_argument("--q1-source", type=Path)
    args = parser.parse_args()
    result = publish(args.source, args.output, args.q1_source)
    print(json.dumps({key: value for key, value in result.items() if key != "files"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
