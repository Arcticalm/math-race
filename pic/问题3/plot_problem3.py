"""论文图表：问题3（通信保障下的运输与中继联合调度）。"""
from pathlib import Path
import ast
import base64
from io import BytesIO
import math
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
from openpyxl import load_workbook
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "outputs" / "problem3"
OUT = Path(__file__).resolve().parent
BASE = ROOT / "data" / "无人机应急物资运输基础数据"
SAMPLE_STEP_S = 15.0
COLORS = {"直连": "#287a8c", "中继": "#d3b532", "中断": "#b45b3c"}
AIRCRAFT = {"A": "#1769aa", "B": "#e08e0b", "C": "#c44536"}
plt.rcParams.update({
    "font.sans-serif": ["Noto Sans CJK SC", "Microsoft YaHei", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False, "figure.dpi": 160, "savefig.dpi": 300,
    "axes.titlesize": 14, "axes.labelsize": 11, "xtick.labelsize": 9, "ytick.labelsize": 9,
})


def save(fig, name):
    fig.savefig(OUT / name, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def nodes():
    ws = load_workbook(BASE / "调度中心与服务区.xlsx", read_only=True, data_only=True).active
    result = {}
    for row in ws.iter_rows(values_only=True):
        if row and row[0] and (row[0] == "O01" or str(row[0]).startswith("S")):
            result[str(row[0])] = (float(row[2]), float(row[3]))
    return result


def terrain(ax):
    html = ROOT / "data" / "镇龙乡地理空间数据" / "镇龙乡地理空间详情地图.html"
    text = html.read_text(encoding="utf-8")
    match = re.search(r'const terrainUrl = "data:image/png;base64,([^\"]+)"', text)
    if match:
        image = np.asarray(Image.open(BytesIO(base64.b64decode(match.group(1)))).convert("RGB"))
        ax.imshow(image, extent=(109.0328115248, 109.4450943306, 22.8615453408, 23.2247021255),
                  origin="upper", alpha=0.70, zorder=-2, aspect="auto")


def load():
    communication = pd.read_csv(DATA / "communication_audit.csv")
    relay = pd.read_csv(DATA / "relay_resource_audit.csv")
    schedule = pd.read_csv(DATA / "relay_schedule.csv")
    transport = pd.read_csv(DATA / "transport_inherited_audit.csv")
    return communication, relay, schedule, transport


def collect_link_samples(schedule: pd.DataFrame) -> pd.DataFrame:
    """用附件物理模型对本次第三问方案逐点重算三类链路裕量。

    统一求解器只写运输轨迹与中继排程，不写逐点链路采样表，因此这里按同一套
    DEM/自由空间损耗模型重新采样：直连为运输机→G01，中继接入为运输机→悬停点，
    中继回传为悬停点→G01。裕量定义为「接收门限 − 路径损耗」，正值即可用。
    """
    sys.path.insert(0, str(ROOT))
    from src.problem1.solver import Node
    from src.problem3.physics import LinkEvaluator, link_limits
    from src.problem3.solver import TrackPhase, _position

    phases = []
    for row in pd.read_csv(DATA / "trajectory_phases.csv").to_dict("records"):
        phases.append(TrackPhase(
            sortie=row["sortie"], name=row["name"],
            start_s=float(row["start_s"]), end_s=float(row["end_s"]),
            start_node=Node(**ast.literal_eval(row["start_node"])),
            end_node=Node(**ast.literal_eval(row["end_node"])),
            start_altitude_m=float(row["start_altitude_m"]),
            end_altitude_m=float(row["end_altitude_m"])))

    evaluator = LinkEvaluator()
    limits = link_limits(evaluator.params)
    base = evaluator.base
    gateway = Node("G01", base.longitude, base.latitude, base.elevation_m + 20)
    missions = schedule.to_dict("records")
    records = []
    try:
        for phase in phases:
            duration = phase.end_s - phase.start_s
            if duration <= 0:
                continue
            count = max(1, math.ceil(duration / SAMPLE_STEP_S))
            for index in range(count + 1):
                time_s = phase.start_s + duration * index / count
                node, altitude = _position(phase, time_s)
                direct = evaluator.evaluate(node, altitude, gateway, gateway.elevation_m,
                                            limits["transport_gateway_db"])
                access = backhaul = None
                mission = next((m for m in missions
                                if phase.sortie in str(m["covered_sorties"]).split(",")
                                and float(m["service_start_s"]) - 1e-7 <= time_s
                                <= float(m["service_end_s"]) + 1e-7), None)
                if mission is not None:
                    hover = Node("relay", mission["longitude"], mission["latitude"],
                                 mission["ground_dsm_m"])
                    a = evaluator.evaluate(node, altitude, hover, mission["hover_altitude_m"],
                                           limits["transport_relay_db"])
                    b = evaluator.evaluate(hover, mission["hover_altitude_m"], gateway,
                                           gateway.elevation_m, limits["relay_gateway_db"])
                    if a.path_loss_db is not None:
                        access = a.threshold_db - a.path_loss_db
                    if b.path_loss_db is not None:
                        backhaul = b.threshold_db - b.path_loss_db
                records.append({
                    "sortie": phase.sortie, "time_s": time_s,
                    "direct_available": bool(direct.available),
                    "direct_margin_db": None if direct.path_loss_db is None
                                        else direct.threshold_db - direct.path_loss_db,
                    "access_margin_db": access, "backhaul_margin_db": backhaul})
    finally:
        evaluator.close()
    return pd.DataFrame(records)


def plot_joint_gantt(relay, transport):
    t = transport[["架次编号", "起飞时刻（s）", "返回O01时刻（s）"]].copy()
    t["资源"] = "运输 " + t["架次编号"]
    t["类型"] = "运输"
    t["开始"] = t["起飞时刻（s）"]; t["结束"] = t["返回O01时刻（s）"]
    r = relay[["中继架次编号", "准备开始时刻（s）", "返回O01时刻（s）"]].copy()
    r["资源"] = "中继 " + r["中继架次编号"]; r["类型"] = "中继"
    r["开始"] = r["准备开始时刻（s）"]; r["结束"] = r["返回O01时刻（s）"]
    df = pd.concat([t[["资源", "类型", "开始", "结束"]], r[["资源", "类型", "开始", "结束"]]], ignore_index=True)
    df = df.sort_values("开始").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(11.5, 7.0))
    for i, row in df.iterrows():
        color = "#287a8c" if row["类型"] == "运输" else "#d3b532"
        ax.barh(i, row["结束"] - row["开始"], left=row["开始"], height=0.62, color=color, alpha=0.88)
        ax.text((row["开始"] + row["结束"]) / 2, i, row["资源"], ha="center", va="center", fontsize=6.5, color="white")
    ax.set_yticks(range(len(df)), df["资源"]); ax.set_xlabel("时间 / s")
    ax.set_title("运输与中继无人机联合任务时间轴", pad=12, fontweight="bold")
    ax.grid(axis="x", color="#dfe7ee", lw=0.8); ax.spines[["top", "right"]].set_visible(False)
    ax.legend(handles=[Patch(color="#287a8c", label="运输架次"), Patch(color="#d3b532", label="中继架次")],
              frameon=False, loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0)
    fig.subplots_adjust(right=0.82)
    save(fig, "图1_联合任务时间轴.png")


def plot_communication(communication):
    counts = communication.groupby(["运输架次编号", "保障方式"], as_index=False).apply(
        lambda x: pd.Series({"时长_s": (x["结束时刻（s）"] - x["开始时刻（s）"]).sum()}), include_groups=False
    ).reset_index(drop=True)
    pivot = counts.pivot(index="运输架次编号", columns="保障方式", values="时长_s").fillna(0)
    for name in ["直连", "中继", "中断"]:
        if name not in pivot: pivot[name] = 0.0
    pivot = pivot[["直连", "中继", "中断"]]
    pivot["total"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("total", ascending=True)
    fig, ax = plt.subplots(figsize=(10.5, 6.8))
    left = np.zeros(len(pivot))
    for name in ["直连", "中继", "中断"]:
        ax.barh(pivot.index, pivot[name], left=left, color=COLORS[name], label=name, height=0.68)
        left += pivot[name].to_numpy()
    ax.set_xlabel("通信保障时长 / s"); ax.set_ylabel("运输架次")
    ax.set_title("运输架次通信保障方式构成", pad=12, fontweight="bold")
    ax.grid(axis="x", color="#dfe7ee", lw=0.8); ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=1, loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0)
    fig.subplots_adjust(right=0.82)
    save(fig, "图2_通信保障构成.png")


def plot_relay_map(schedule):
    ns = nodes(); fig, ax = plt.subplots(figsize=(8.5, 7.2)); terrain(ax)
    arr = np.asarray(list(ns.values())); ax.set_xlim(arr[:, 0].min()-0.018, arr[:, 0].max()+0.018); ax.set_ylim(arr[:, 1].min()-0.014, arr[:, 1].max()+0.014)
    for code, (x, y) in ns.items():
        if code == "O01":
            ax.scatter(x, y, marker="*", s=130, color="#222", zorder=4); ax.text(x, y, "  O01", va="center", fontweight="bold")
        else:
            ax.scatter(x, y, s=20, color="#59636d", zorder=3); ax.text(x, y, code, fontsize=7, color="#39434d")
    # 同一悬停点可能承载多个中继架次，合并为一个点并合并标注，避免文字重叠。
    for _, row in schedule.iterrows():
        ax.plot([ns["O01"][0], row["longitude"]], [ns["O01"][1], row["latitude"]],
                color="#d3b532", lw=1.4, alpha=0.75, zorder=2)
    grouped = schedule.assign(
        lon_key=schedule["longitude"].round(6), lat_key=schedule["latitude"].round(6)
    ).groupby(["lon_key", "lat_key"], sort=False)
    for (_, _), group in grouped:
        x = group["longitude"].iloc[0]
        y = group["latitude"].iloc[0]
        labels = " / ".join(group["relay_sortie"].astype(str))
        ax.scatter(x, y, s=72, marker="^", color="#d3b532", edgecolor="white", zorder=5)
        ax.annotate(labels, (x, y), xytext=(6, 6), textcoords="offset points",
                    fontsize=7, color="#725f00", ha="left", va="bottom",
                    bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.68, "pad": 1.5})
    ax.set_xlabel("经度"); ax.set_ylabel("纬度"); ax.set_title("中继悬停点与服务覆盖空间分布", pad=12, fontweight="bold")
    ax.grid(color="white", alpha=0.65, lw=0.8); ax.spines[["top", "right"]].set_visible(False)
    ax.legend(handles=[Patch(color="#d3b532", label="中继悬停点/航线")], frameon=False, loc="upper right")
    save(fig, "图3_中继空间部署.png")


def plot_relay_resources(relay):
    df = relay.sort_values(["中继无人机编号", "准备开始时刻（s）"])
    resources = list(dict.fromkeys(df["中继无人机编号"]))
    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    for yi, resource in enumerate(resources):
        for _, row in df[df["中继无人机编号"] == resource].iterrows():
            ax.barh(yi, row["返回O01时刻（s）"] - row["准备开始时刻（s）"], left=row["准备开始时刻（s）"], height=0.48, color="#d3b532", alpha=0.9)
            ax.text((row["准备开始时刻（s）"] + row["返回O01时刻（s）"]) / 2, yi, row["中继架次编号"], ha="center", va="center", fontsize=7, color="white")
    ax.set_yticks(range(len(resources)), resources); ax.set_xlabel("时间 / s"); ax.set_ylabel("中继无人机")
    ax.set_title("中继无人机任务占用与架次衔接", pad=12, fontweight="bold")
    ax.grid(axis="x", color="#dfe7ee", lw=0.8); ax.spines[["top", "right"]].set_visible(False)
    save(fig, "图4_中继资源周转.png")


def plot_link_margin(samples: pd.DataFrame) -> None:
    series = [samples["direct_margin_db"].dropna(),
              samples["access_margin_db"].dropna(),
              samples["backhaul_margin_db"].dropna()]
    labels = ["直连链路", "中继接入", "中继回传"]
    fig, ax = plt.subplots(figsize=(8.8, 5.5))
    ax.boxplot(series, tick_labels=labels, patch_artist=True,
               boxprops={"facecolor": "#dce9ed", "edgecolor": "#52606d"},
               medianprops={"color": "#b45b3c", "lw": 2},
               whiskerprops={"color": "#52606d"}, capprops={"color": "#52606d"},
               flierprops={"marker": "o", "markersize": 2.5, "alpha": 0.35,
                           "markerfacecolor": "#9aa7b2", "markeredgecolor": "none"})
    ax.axhline(0, color="#52606d", ls="--", lw=1)
    for index, values in enumerate(series, start=1):
        ax.annotate(f"中位 {values.median():.1f} dB\nn={len(values)}",
                    (index, values.median()), xytext=(0, 12), textcoords="offset points",
                    ha="center", fontsize=8.5, color="#39434d")
    ax.set_ylabel("链路裕量 / dB（接收门限 − 路径损耗）")
    ax.set_title("通信链路可用性裕量分布", pad=12, fontweight="bold")
    ax.grid(axis="y", color="#dfe7ee", lw=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "图5_链路裕量分布.png")


def plot_relay_demand(samples: pd.DataFrame, schedule: pd.DataFrame, bucket_s: float = 120.0) -> None:
    """中继通信的需求与供给随时间的匹配情况。

    需求按时间分桶统计「该时段内直连不可用、因而需要中继的运输架次数」；
    供给统计「服务窗口与该时段有交集的中继架次数」。两者用同一分桶口径，
    因此需求不为零的时段供给必然不为零，对应连续通信认证通过。
    注意模型沿用附件的无限并发假设，一架中继可同时服务多架运输机，
    所以需求高于供给不代表容量冲突，本图用于核对中继服务窗口的时段覆盖。
    """
    needing = samples[~samples["direct_available"]].copy()
    needing["bucket"] = (needing["time_s"] // bucket_s) * bucket_s
    demand = needing.groupby("bucket")["sortie"].nunique()
    windows = [(float(row["service_start_s"]), float(row["service_end_s"]))
               for _, row in schedule.iterrows()]
    horizon = float(max(samples["time_s"].max(), max(end for _, end in windows)))
    grid = np.arange(0.0, horizon + bucket_s, bucket_s)
    demand_values = [int(demand.get(t, 0)) for t in grid]
    supply = [sum(1 for start, end in windows if start < t + bucket_s and end > t)
              for t in grid]
    fig, ax = plt.subplots(figsize=(11.2, 5.0))
    ax.fill_between(grid, demand_values, step="post", color="#b45b3c", alpha=0.12)
    ax.step(grid, demand_values, where="post", lw=2.0, color="#b45b3c",
            label="需要中继保障的运输架次")
    ax.step(grid, supply, where="post", lw=2.0, color="#d3b532", label="在服中继无人机")
    uncovered = [t for t, need, have in zip(grid, demand_values, supply) if need and not have]
    if uncovered:
        ax.scatter(uncovered, [0] * len(uncovered), marker="v", s=45,
                   color="#b45b3c", zorder=5, label="需求时段无中继在服")
    ax.set_xlabel("时间 / s")
    ax.set_ylabel("并发架次数 / 架")
    ax.set_title(f"中继通信需求与供给的时序匹配（{bucket_s:.0f} s 分桶）", pad=12, fontweight="bold")
    ax.grid(color="#dfe7ee", lw=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.margins(y=0.18)
    ax.legend(frameon=False, loc="upper left")
    ax.annotate("沿用附件无限并发假设：一架中继可同时服务多架运输机，\n"
                "故需求高于供给不构成冲突，本图核对的是服务窗口的时段覆盖。",
                xy=(0.985, 0.035), xycoords="axes fraction", ha="right", va="bottom",
                fontsize=8, color="#52606d")
    save(fig, "图6_中继通信供需时序.png")
    if uncovered:
        print(f"警告：{len(uncovered)} 个分桶内需求非零但无中继在服")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    communication, relay, schedule, transport = load()
    plot_joint_gantt(relay, transport); plot_communication(communication); plot_relay_map(schedule)
    plot_relay_resources(relay)
    # 图5、图6 需要逐点链路裕量：统一求解器不写该表，这里用附件物理模型重算。
    print("按附件物理模型重算逐点链路裕量 ...")
    samples = collect_link_samples(schedule)
    samples.to_csv(OUT / "链路裕量采样.csv", index=False, encoding="utf-8-sig")
    plot_link_margin(samples)
    plot_relay_demand(samples, schedule)
    rows = [
        ("图1_联合任务时间轴.png", "展示运输与中继架次的联合完成过程"),
        ("图2_通信保障构成.png", "比较各运输架次直连与中继保障时长"),
        ("图3_中继空间部署.png", "展示中继悬停点、服务区和地形背景"),
        ("图4_中继资源周转.png", "展示两架中继无人机的任务衔接"),
        ("图5_链路裕量分布.png", "展示直连、接入、回传三类链路的安全裕量分布"),
        ("图6_中继通信供需时序.png", "比较需中继保障的运输架次与在服中继数的时序匹配"),
    ]
    table = "\n".join(f"| {name} | {use} |" for name, use in rows)
    (OUT / "图表索引.md").write_text(
        "# 问题3图表\n\n| 文件 | 论文用途 |\n|---|---|\n" + table + "\n\n"
        "数据来源：outputs/problem3；图5、图6 的链路裕量由附件 DEM/LOS 物理模型对本次方案"
        "逐点重算得到（采样步长见脚本 SAMPLE_STEP_S）。\n",
        encoding="utf-8")


if __name__ == "__main__":
    main()
