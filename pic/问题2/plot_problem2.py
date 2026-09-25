"""论文图表：问题2（异构无人机多点多架次调度）。

运行：MPLCONFIGDIR=/tmp/mplconfig ./.venv/bin/python pic/问题2/plot_problem2.py
"""
from pathlib import Path
import re
import base64
from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.patches import FancyArrowPatch
from PIL import Image
import numpy as np
import pandas as pd
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "outputs" / "problem2"
OUT = Path(__file__).resolve().parent
BASE = ROOT / "data" / "无人机应急物资运输基础数据"
COLORS = {"A": "#1769aa", "B": "#e08e0b", "C": "#c44536"}
LINESTYLES = {"A": "-", "B": "--", "C": ":"}
TYPE_COLORS = {"医疗物资": "#c44536", "饮用水": "#1769aa", "应急食品": "#e08e0b", "卫生用品": "#35a7a0"}
plt.rcParams.update({
    "font.sans-serif": ["Noto Sans CJK SC", "Microsoft YaHei", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False, "figure.dpi": 160, "savefig.dpi": 300,
    "axes.titlesize": 14, "axes.labelsize": 11, "xtick.labelsize": 9, "ytick.labelsize": 9,
})


def save(fig, name):
    fig.savefig(OUT / name, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def read_nodes():
    ws = load_workbook(BASE / "调度中心与服务区.xlsx", read_only=True, data_only=True).active
    nodes = {}
    for row in ws.iter_rows(values_only=True):
        if row and row[0] and (row[0] == "O01" or str(row[0]).startswith("S")):
            nodes[str(row[0])] = (float(row[2]), float(row[3]))
    return nodes


def draw_map_background(ax, nodes):
    """绘制仓库 GIS 中的道路和水系线作为浅色地理背景。"""
    # 详情地图 HTML 内嵌了彩色 DEM 底图，直接复用以保持底图风格一致。
    html = ROOT / "data" / "镇龙乡地理空间数据" / "镇龙乡地理空间详情地图.html"
    html_text = html.read_text(encoding="utf-8")
    match = re.search(r'const terrainUrl = "data:image/png;base64,([^\"]+)"', html_text)
    if match:
        terrain = np.asarray(Image.open(BytesIO(base64.b64decode(match.group(1)))).convert("RGB"))
        ax.imshow(terrain, extent=(109.0328115248, 109.4450943306, 22.8615453408, 23.2247021255),
                  origin="upper", alpha=0.72, zorder=-2, aspect="auto")
    bounds = np.asarray(list(nodes.values()))
    xmin, ymin = bounds.min(axis=0) - np.array([0.012, 0.012])
    xmax, ymax = bounds.max(axis=0) + np.array([0.012, 0.012])
    road_path = ROOT / "data" / "镇龙乡地理空间数据" / "镇龙乡及周边地理数据" / "道路" / "镇龙乡及周边道路.csv"
    water_path = ROOT / "data" / "镇龙乡地理空间数据" / "镇龙乡及周边地理数据" / "水系（线）" / "镇龙乡及周边水系.csv"
    for path, key, color, lw, alpha in [
        (road_path, "道路要素编号", "#b7b0a3", 0.45, 0.40),
        (water_path, "水系要素编号", "#72a9c4", 0.75, 0.50),
    ]:
        if not path.exists():
            continue
        frame = pd.read_csv(path, encoding="utf-8-sig")
        frame = frame[(frame["经度"].between(xmin, xmax)) & (frame["纬度"].between(ymin, ymax))]
        for _, line in frame.groupby(key, sort=False):
            if len(line) > 1:
                ax.plot(line["经度"], line["纬度"], color=color, lw=lw, alpha=alpha, zorder=0)


def load_data():
    sorties = pd.read_csv(DATA / "sorties_audit.csv")
    segments = pd.read_csv(DATA / "route_segments.csv")
    deliveries = pd.read_csv(DATA / "box_delivery_audit.csv")
    batteries = pd.read_csv(DATA / "battery_audit.csv")
    # 候选方案指标表由统一求解器的反馈迭代逐轮输出（publish 汇总）。
    candidates_path = DATA / "time_priority_candidates.csv"
    candidates = pd.read_csv(candidates_path) if candidates_path.exists() else None
    return sorties, segments, deliveries, batteries, candidates


def route_list(value):
    return [x.strip() for x in re.split(r"[,，→、>]", str(value)) if x.strip()]


def plot_routes(sorties):
    nodes = read_nodes()
    fig, ax = plt.subplots(figsize=(8.4, 7.0))
    draw_map_background(ax, nodes)
    node_array = np.asarray(list(nodes.values()))
    x_margin, y_margin = 0.018, 0.014
    ax.set_xlim(node_array[:, 0].min() - x_margin, node_array[:, 0].max() + x_margin)
    ax.set_ylim(node_array[:, 1].min() - y_margin, node_array[:, 1].max() + y_margin)
    # 聚合重复航段：往返使用同一条双向弧线，线宽代表执行架次。
    segment_counts = {}
    for _, row in sorties.iterrows():
        route = ["O01", *route_list(row["访问服务区顺序"]), "O01"]
        for start, end in zip(route, route[1:]):
            if start in nodes and end in nodes:
                endpoints = tuple(sorted((start, end)))
                key = (row["机型编号"], endpoints)
                segment_counts[key] = segment_counts.get(key, 0) + 1
    # 同一节点对的不同机型使用相反弯曲方向，避免航线完全重合。
    aircraft_radius = {"A": 0.065, "B": -0.065, "C": 0.095}
    for (aircraft, (start, end)), count in segment_counts.items():
        color = COLORS.get(aircraft, "#607080")
        x1, y1 = nodes[start]; x2, y2 = nodes[end]
        radius = aircraft_radius.get(aircraft, 0.12)
        arrow = FancyArrowPatch(
            (x1, y1), (x2, y2), arrowstyle="<->", mutation_scale=8,
            connectionstyle=f"arc3,rad={radius}", color=color,
            linewidth=1.8 + 0.45 * np.sqrt(max(1, count / 2)),
            linestyle=LINESTYLES.get(aircraft, "-"), alpha=0.88, zorder=2,
        )
        ax.add_patch(arrow)
    for code, (lon, lat) in nodes.items():
        if code == "O01":
            ax.scatter(lon, lat, s=115, marker="*", color="#222222", zorder=4, label="O01 调度中心")
            ax.text(lon, lat, "  O01", fontsize=9, va="center", fontweight="bold")
        else:
            ax.scatter(lon, lat, s=30, color="#52606d", zorder=3)
            ax.text(lon, lat, code, fontsize=7, ha="left", va="bottom", color="#52606d")
    for code, color in COLORS.items():
        ax.plot([], [], color=color, linestyle=LINESTYLES[code], lw=2.5, label=f"{code}型航段")
    ax.set_xlabel("经度"); ax.set_ylabel("纬度")
    ax.set_title("第二问调度方案的服务区访问路线", pad=12, fontweight="bold")
    ax.grid(color="#dfe7ee", lw=0.8); ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0)
    fig.subplots_adjust(right=0.82)
    save(fig, "图1_调度路线网络.png")


def plot_drone_gantt(sorties):
    df = sorties.sort_values(["无人机编号", "准备开始时刻（s）"])
    drones = list(dict.fromkeys(df["无人机编号"]))
    fig, ax = plt.subplots(figsize=(11.5, 6.5))
    for yi, drone in enumerate(drones):
        sub = df[df["无人机编号"] == drone]
        for _, row in sub.iterrows():
            start = row["准备开始时刻（s）"]; width = row["返回O01时刻（s）"] - start
            ax.barh(yi, width, left=start, height=0.58, color=COLORS.get(row["机型编号"], "#607080"), alpha=0.88)
            ax.text(start + width / 2, yi, row["架次编号"], ha="center", va="center", fontsize=7, color="white")
    ax.set_yticks(range(len(drones)), drones); ax.set_xlabel("时间 / s"); ax.set_ylabel("实体运输无人机")
    ax.set_title("实体运输无人机任务占用时间轴", pad=12, fontweight="bold")
    ax.grid(axis="x", color="#dfe7ee", lw=0.8); ax.spines[["top", "right"]].set_visible(False)
    ax.legend(handles=[Patch(facecolor=color, label=f"{code}型") for code, color in COLORS.items()],
              frameon=False, ncol=1, loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0)
    fig.subplots_adjust(right=0.82)
    save(fig, "图2_无人机资源时间轴.png")


def plot_battery_gantt(batteries):
    df = batteries.sort_values(["电池编号", "任务占用开始（s）"])
    batteries_order = list(dict.fromkeys(df["电池编号"]))
    fig, ax = plt.subplots(figsize=(11.5, 7.0))
    for yi, battery in enumerate(batteries_order):
        sub = df[df["电池编号"] == battery]
        aircraft = str(sub.iloc[0]["机型编号"])
        for _, row in sub.iterrows():
            use_start = row["任务占用开始（s)"] if "任务占用开始（s)" in row else row["任务占用开始（s）"]
            release = row["返航释放（s）"]
            charge_end = row["充电完成（s）"]
            ax.barh(yi, release - use_start, left=use_start, height=0.54, color=COLORS.get(aircraft, "#607080"), alpha=0.9)
            ax.barh(yi, charge_end - release, left=release, height=0.54, color="#b8c2cc", alpha=0.9)
            ax.text(use_start + (release-use_start)/2, yi, row["架次编号"], ha="center", va="center", fontsize=7, color="white")
    ax.set_yticks(range(len(batteries_order)), batteries_order); ax.set_xlabel("时间 / s"); ax.set_ylabel("共享电池")
    ax.set_title("共享电池任务占用与充电周转", pad=12, fontweight="bold")
    ax.grid(axis="x", color="#dfe7ee", lw=0.8); ax.spines[["top", "right"]].set_visible(False)
    ax.legend(handles=[Patch(facecolor="#52606d", label="任务占用"),
                       Patch(facecolor="#b8c2cc", label="充电")],
              frameon=False, ncol=1, loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0)
    fig.subplots_adjust(right=0.82)
    save(fig, "图3_电池周转时间轴.png")


def plot_delivery(deliveries):
    df = deliveries.copy()
    df["交付时刻 / h"] = df["交付完成时刻（s）"] / 3600
    df["期望时刻 / h"] = df["期望送达时间（s）"] / 3600
    fig, ax = plt.subplots(figsize=(10.5, 5.8))
    for item_type, sub in df.groupby("物资类型"):
        ax.scatter(sub["期望时刻 / h"], sub["交付时刻 / h"], s=24, alpha=0.70,
                   color=TYPE_COLORS.get(item_type, "#607080"), label=item_type)
    lim = max(df["期望时刻 / h"].max(), df["交付时刻 / h"].max()) * 1.05
    ax.plot([0, lim], [0, lim], ls="--", color="#52606d", lw=1, label="按期基准线")
    ax.set_xlim(left=0, right=lim); ax.set_ylim(bottom=0, top=lim)
    ax.set_xlabel("期望送达时间 / h"); ax.set_ylabel("实际交付完成时间 / h")
    ax.set_title("逐箱配送时效：期望时间与实际交付时间", pad=12, fontweight="bold")
    ax.grid(color="#dfe7ee", lw=0.8); ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=3, loc="upper left")
    save(fig, "图4_逐箱配送时效.png")


def plot_energy(sorties):
    df = sorties.sort_values("架次能耗（kWh）", ascending=True)
    fig, ax = plt.subplots(figsize=(10.8, 5.8))
    y = np.arange(len(df))
    ax.barh(y, df["架次能耗（kWh）"], color=[COLORS.get(x, "#607080") for x in df["机型编号"]], alpha=0.9)
    ax.set_yticks(y, df["架次编号"]); ax.set_xlabel("架次能耗 / kWh"); ax.set_ylabel("架次")
    ax.set_title("调度方案各架次能耗与机型分布", pad=12, fontweight="bold")
    ax.grid(axis="x", color="#dfe7ee", lw=0.8); ax.spines[["top", "right"]].set_visible(False)
    ax.legend(handles=[Patch(facecolor=color, label=f"{code}型") for code, color in COLORS.items()],
              frameon=False, ncol=3, loc="lower right")
    save(fig, "图5_架次能耗与机型.png")


def plot_tradeoff(candidates):
    """对比各轮反馈迭代给出的候选方案在四个目标上的取值。

    统一求解器不再成批枚举组批方案，而是逐轮反馈迭代各产生一个通过审计的候选解，
    因此这里按轮次并列比较，深色标出最终选定的那一轮。
    """
    df = candidates.copy()
    df["方案"] = df["run"] + " · 第 " + df["iteration"].astype(str) + " 轮"
    selected = df["selected"].astype(str).str.lower().isin(["true", "1", "是"])
    panels = [
        ("makespan_s", "全部任务完成时间 / s", "#1769aa"),
        ("weighted_lateness", "加权迟到量 /（优先级×s）", "#c44536"),
        ("energy_kwh", "总运输能耗 / kWh", "#e08e0b"),
        ("sortie_count", "运输架次 / 架", "#35a7a0"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(11.4, 7.4))
    for ax, (column, label, color) in zip(axes.ravel(), panels):
        colors = [color if flag else "#c3ccd4" for flag in selected]
        bars = ax.bar(df["方案"], df[column], width=0.5, color=colors, alpha=0.92)
        for bar, value in zip(bars, df[column]):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                    f"{value:g}", ha="center", va="bottom", fontsize=10)
        ax.set_ylabel(label)
        ax.grid(axis="y", color="#dfe7ee", lw=0.8)
        ax.spines[["top", "right"]].set_visible(False)
        ax.margins(y=0.20)
    fig.suptitle("反馈迭代候选方案的指标对比（深色为最终选定方案）",
                 y=1.0, fontsize=14, fontweight="bold")
    fig.tight_layout()
    save(fig, "图6_方案指标对比.png")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sorties, segments, deliveries, batteries, candidates = load_data()
    plot_routes(sorties); plot_drone_gantt(sorties); plot_battery_gantt(batteries)
    plot_delivery(deliveries); plot_energy(sorties)
    if candidates is None:
        print("跳过 图6_方案指标对比.png：缺少 time_priority_candidates.csv（需先运行 publish）")
    else:
        plot_tradeoff(candidates)
    rows = [
        ("图1_调度路线网络.png", "展示 O01 到服务区的实际访问路线"),
        ("图2_无人机资源时间轴.png", "展示实体无人机任务串行与并行关系"),
        ("图3_电池周转时间轴.png", "展示共享电池任务占用和充电周转"),
        ("图4_逐箱配送时效.png", "比较期望送达时间和实际交付时间"),
        ("图5_架次能耗与机型.png", "比较各架次能耗及机型差异"),
    ]
    if candidates is not None:
        rows.append(("图6_方案指标对比.png", "对比反馈迭代候选方案的完成时间、迟到量、能耗与架次"))
    table = "\n".join(f"| {name} | {use} |" for name, use in rows)
    (OUT / "图表索引.md").write_text(
        "# 问题2图表\n\n| 文件 | 论文用途 |\n|---|---|\n" + table + "\n\n"
        "数据来源：outputs/problem2（统一求解器 q2 输出）；候选方案指标见 time_priority_candidates.csv。\n",
        encoding="utf-8")


if __name__ == "__main__":
    main()
