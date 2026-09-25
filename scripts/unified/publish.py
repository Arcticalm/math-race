"""Publish the selected Q2–Q4 workbooks and comparable figures at one location."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import zipfile
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts.unified.solver import digest
from src.problem1.solver import ROOT, load_nodes
from src.problem21.solver import load_task_boxes
from src.problem23.terrain_audit import write_clearance_outputs
from src.problem4.solver import SITES, q3_gate


COLORS = {"A": "#2878b5", "B": "#e07a24", "C": "#37966f", "relay": "#7952a1"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def save(figure, path: Path) -> None:
    figure.savefig(path, dpi=180)
    plt.close(figure)


def candidate_rows(source: Path):
    rows = []
    for root in sorted(source.glob("run*")):
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
    figure, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
    for row in points:
        time_s, late, energy, sorties, deficit, *_ = row["joint_score"]
        chosen = row["run"] == selected["run"] and abs(time_s - selected["time_s"]) < 1e-6
        color = "#c0392b" if chosen else "#2878b5"
        for axis, horizontal in zip(axes, (energy, deficit)):
            axis.scatter(horizontal, time_s, color=color, s=90 if chosen else 45,
                         edgecolor="white", linewidth=.5, zorder=3)
            axis.annotate(f"{row['run']}-{row['iteration']}", (horizontal, time_s),
                          xytext=(4, 4), textcoords="offset points", fontsize=8)
    axes[0].set(xlabel="Joint energy (kWh)", ylabel="Joint completion time (s)",
                title="Completion time and energy")
    axes[1].set(xlabel="K=2 + K=3 resource deficit", ylabel="Joint completion time (s)",
                title="Completion time and partition deficit")
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
    figure, axes = plt.subplots(1, 2, figsize=(14, 6), layout="constrained", sharex=True, sharey=True)
    palette = ("#2878b5", "#e07a24", "#37966f")
    for axis, k in zip(axes, ("2", "3")):
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
    axes[0].set_ylabel("Latitude (deg)")
    save(figure, output)


def inventory_chart(source: Path, output: Path):
    rows = read_csv(source / "q4/inventory_comparison.csv")
    keys = [row["resource"] for row in rows if row["K"] == "2"]
    if len(keys) != 8:
        raise ValueError("Q4 inventory chart expects eight named resource types")
    figure, axes = plt.subplots(2, 1, figsize=(11, 8), layout="constrained", sharex=True)
    for axis, k in zip(axes, ("2", "3")):
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
    axes[1].set_xticks(range(len(keys)), keys, rotation=30, ha="right", fontsize=8)
    axes[0].bar([], [], color="#2878b5", label="Inventory")
    axes[0].bar([], [], color="#37966f", label="Demand within stock")
    axes[0].bar([], [], color="#c0392b", label="Demand exceeding stock")
    axes[0].legend(ncol=3, loc="upper right", fontsize=8)
    save(figure, output)


def publish(source: Path, output: Path) -> dict:
    if not (source / "summary.json").exists():
        raise ValueError("Selected unified solution is missing")
    summary = json.loads((source / "summary.json").read_text(encoding="utf-8"))
    q2 = json.loads((source / "q2/validation.json").read_text(encoding="utf-8"))
    if not (summary.get("feasible") and q2.get("feasible")
            and q2.get("terrain_clearance", {}).get("feasible")
            and q3_gate(source / "q3")["ready"]):
        raise ValueError("Selected Q2/Q3 solution has not passed the required audits")
    if not all(json.loads((source / "q4/result.json").read_text(encoding="utf-8"))
               ["solutions"][str(k)]["feasible"] for k in (2, 3)):
        raise ValueError("Both frozen Q4 partitions are required")
    output.mkdir(parents=True, exist_ok=True)
    names = {"problem2_submission.xlsx": "q2/problem2_submission.xlsx",
             "problem3_submission.xlsx": "q3/problem3_submission.xlsx",
             "problem4_submission.xlsx": "q4/problem4_submission.xlsx",
             "unified_program.zip": "unified_program.zip",
             "routes.png": "q2/routes.png",
             "resource_gantt.png": "q2/resource_gantt.png",
             "delivery_times.png": "q2/delivery_times.png",
             "q3_routes_relays.png": "q3/routes_relays.png"}
    for name, relative in names.items():
        shutil.copy2(source / relative, output / name)
    write_clearance_outputs(output, q2["terrain_clearance"])
    q3 = json.loads((source / "q3/screening.json").read_text(encoding="utf-8"))
    (output / "_q3_clearance_tmp").mkdir(exist_ok=True)
    write_clearance_outputs(output / "_q3_clearance_tmp", q3["terrain_clearance"])
    shutil.move(output / "_q3_clearance_tmp/terrain_clearance.png", output / "q3_terrain_clearance.png")
    shutil.move(output / "_q3_clearance_tmp/terrain_clearance_audit.csv", output / "q3_terrain_clearance_audit.csv")
    (output / "_q3_clearance_tmp").rmdir()
    rows = candidate_rows(output)
    q2_source = Path(summary["q2"]["source"]).name
    q3_source = Path(summary["q3_q4"]["source"]).name
    q2_candidates = time_tradeoff(rows, {"run": q2_source,
                                           "time_s": summary["q2"]["score"][0]},
                                    output / "time_priority_tradeoff.png")
    q3_candidates = joint_tradeoff(rows, {"run": q3_source,
                                             "time_s": summary["q3_q4"]["score"][0]},
                                      output / "q3_tradeoff.png")
    relay_gantt(source, output / "q3_resource_gantt.png")
    delivery_chart(source, output / "q3_delivery_times.png")
    communication_chart(source, output / "q3_communication_timeline.png")
    partition_map(source, output / "q4_partitions.png")
    inventory_chart(source, output / "q4_inventory.png")
    with (output / "time_priority_candidates.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("run", "iteration", "sortie_count",
                                                     "makespan_s", "weighted_lateness", "energy_kwh", "selected"))
        writer.writeheader()
        writer.writerows({"run": row["run"], "iteration": row["iteration"],
                          "sortie_count": row["q2_score"][3], "makespan_s": row["q2_score"][0],
                          "weighted_lateness": row["q2_score"][1], "energy_kwh": row["q2_score"][2],
                          "selected": row["run"] == q2_source
                          and abs(row["q2_score"][0] - summary["q2"]["score"][0]) < 1e-6}
                         for row in q2_candidates)
    assets = [*names, "terrain_clearance.png", "terrain_clearance_audit.csv",
              "q3_terrain_clearance.png", "q3_terrain_clearance_audit.csv",
              "time_priority_tradeoff.png", "time_priority_candidates.csv",
              "q3_tradeoff.png", "q3_resource_gantt.png", "q3_delivery_times.png",
              "q3_communication_timeline.png", "q4_partitions.png", "q4_inventory.png"]
    with zipfile.ZipFile(output / "unified_results.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("problem2_submission.xlsx", "problem3_submission.xlsx",
                     "problem4_submission.xlsx", "unified_program.zip",
                     "terrain_clearance_audit.csv", "q3_terrain_clearance_audit.csv"):
            archive.write(output / name, name)
        for name in assets:
            if name.endswith(".png"):
                archive.write(output / name, name)
        for relative in ("q2/validation.json", "q3/screening.json", "q3/box_delivery_audit.csv",
                         "q3/communication_audit.csv", "q3/relay_resource_audit.csv",
                         "q4/result.json", "q4/inventory_comparison.csv"):
            archive.write(source / relative, relative)
    index = ["# 第二至第四问统一结果", "",
             "三份工作簿分别记录第二问独立运输方案、第三问运输与中继联合方案、第四问冻结后的分区资源配置。",
             "计算指标、适用范围和资源缺口详见 [完整报告](final/REPORT.md)。", "",
             "## 提交与审计", "",
             "- [第二问提交表](problem2_submission.xlsx)",
             "- [第三问提交表](problem3_submission.xlsx)",
             "- [第四问提交表](problem4_submission.xlsx)",
             "- [提交包](unified_results.zip) · [可运行程序](unified_program.zip)",
             "- [文件清单与 SHA-256](deliverables.json)", "",
             "## 图表", "",
             "与 `outputs/problem23` 对应的第二问图：", "",
             "- [运输路线](routes.png) · [资源甘特图](resource_gantt.png) · [逐箱送达](delivery_times.png)",
             "- [完成时间权衡](time_priority_tradeoff.png) · [巡航净空](terrain_clearance.png)", "",
             "第三、四问扩展图：", "",
             "- [运输与中继路线](q3_routes_relays.png) · [联合资源甘特图](q3_resource_gantt.png)",
             "- [第三问逐箱送达](q3_delivery_times.png) · [连续通信时序](q3_communication_timeline.png)",
             "- [第三问巡航净空](q3_terrain_clearance.png) · [分区地图](q4_partitions.png)",
             "- [分区资源需求与库存](q4_inventory.png) · [联合方案权衡](q3_tradeoff.png)", "",
             "图中候选点只代表已认证或已审计的搜索结果；红点是当前选中方案。",
             "第二问和第三问分别来自不同运行，原始方案及审计表保存在 `final/`。", ""]
    (output / "README.md").write_text("\n".join(index), encoding="utf-8")
    result = {"selected_source": str(source.resolve()), "output": str(output.resolve()),
              "q2_candidate_count": len(q2_candidates), "q3_candidate_count": len(q3_candidates),
              "files": {name: digest(output / name) for name in assets + ["unified_results.zip"]}}
    (output / "deliverables.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "outputs/unified/final")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/unified")
    args = parser.parse_args()
    result = publish(args.source, args.output)
    print(json.dumps({key: value for key, value in result.items() if key != "files"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
