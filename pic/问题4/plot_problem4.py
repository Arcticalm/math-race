"""论文图表：问题4（救援任务分区与资源配置）。"""
from pathlib import Path
import base64
from io import BytesIO
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
from openpyxl import load_workbook
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "outputs" / "problem4" / "final"
OUT = Path(__file__).resolve().parent
BASE = ROOT / "data" / "无人机应急物资运输基础数据"
GROUP_COLORS = ["#287a8c", "#d3b532", "#b45b3c"]
RESOURCE_NAMES = {
    "A_airframe": "A型机体", "B_airframe": "B型机体", "C_airframe": "C型机体",
    "A_battery": "A型电池", "B_battery": "B型电池", "C_battery": "C型电池",
    "relay_airframe": "中继机体", "relay_energy": "中继能源组件",
}
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
    result = {}
    for row in ws.iter_rows(values_only=True):
        if row and row[0] and (row[0] == "O01" or str(row[0]).startswith("S")):
            result[str(row[0])] = (float(row[2]), float(row[3]))
    return result


def draw_terrain(ax):
    html = ROOT / "data" / "镇龙乡地理空间数据" / "镇龙乡地理空间详情地图.html"
    text = html.read_text(encoding="utf-8")
    match = re.search(r'const terrainUrl = "data:image/png;base64,([^\"]+)"', text)
    if match:
        image = np.asarray(Image.open(BytesIO(base64.b64decode(match.group(1)))).convert("RGB"))
        ax.imshow(image, extent=(109.0328115248, 109.4450943306, 22.8615453408, 23.2247021255),
                  origin="upper", alpha=0.65, zorder=-2, aspect="auto")


def load_data():
    inventory = pd.read_csv(DATA / "inventory_comparison.csv")
    workload = pd.read_csv(DATA / "workload_comparison.csv")
    mapping = pd.read_csv(DATA / "site_mapping_audit.csv")
    return inventory, workload, mapping


def plot_partitions(mapping):
    coords = read_nodes()
    fig, axes = plt.subplots(1, 2, figsize=(12.8, 6.8), sharex=True, sharey=True)
    for ax, k in zip(axes, [2, 3]):
        draw_terrain(ax)
        sub = mapping[mapping["K"] == k]
        groups = sorted(sub["group"].unique())
        for group in groups:
            sites = sub[sub["group"] == group]["site"].tolist()
            xy = np.asarray([coords[s] for s in sites])
            ax.scatter(xy[:, 0], xy[:, 1], s=85, color=GROUP_COLORS[group - 1], edgecolor="white", linewidth=0.8, zorder=3,
                       label=f"任务组 {group}")
            for site, (x, y) in zip(sites, xy):
                ax.annotate(site, (x, y), xytext=(4, 4), textcoords="offset points", fontsize=7,
                            color="#26323c", bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.68, "pad": 0.6})
        center = coords["O01"]
        ax.scatter(*center, marker="*", s=125, color="#222222", zorder=4)
        ax.text(center[0], center[1], "  O01", va="center", fontweight="bold")
        arr = np.asarray(list(coords.values()))
        ax.set_xlim(arr[:, 0].min() - 0.018, arr[:, 0].max() + 0.018)
        ax.set_ylim(arr[:, 1].min() - 0.014, arr[:, 1].max() + 0.014)
        ax.set_title(f"K={k} 分区", fontweight="bold")
        ax.grid(color="white", alpha=0.65, lw=0.8); ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(0.01, 0.99))
    axes[0].set_ylabel("纬度"); axes[0].set_xlabel("经度"); axes[1].set_xlabel("经度")
    fig.suptitle("问题4任务分区空间分布", y=1.01, fontsize=14, fontweight="bold")
    save(fig, "图1_K2与K3任务分区.png")


def plot_resource_inventory(inventory):
    sub = inventory[inventory["K"] == 2].copy()
    resources = list(RESOURCE_NAMES)
    x = np.arange(len(resources)); width = 0.22
    fig, ax = plt.subplots(figsize=(11.5, 5.8))
    for idx, k in enumerate([2, 3]):
        totals = inventory[inventory["K"] == k].set_index("resource").reindex(resources)["total_demand"]
        ax.bar(x + (idx - 1) * width, totals, width, color=GROUP_COLORS[idx], label=f"K={k}总需求")
    stock = inventory[inventory["K"] == 2].set_index("resource").reindex(resources)["inventory"]
    ax.bar(x + width, stock, width, color="#59636d", alpha=0.45, label="现有库存")
    ax.set_xticks(x, [RESOURCE_NAMES[r] for r in resources], rotation=25, ha="right")
    ax.set_ylabel("资源数量 / 组或架"); ax.set_title("不同分区方案的资源需求与现有库存", pad=12, fontweight="bold")
    ax.grid(axis="y", color="#dfe7ee", lw=0.8); ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=3, loc="upper left", bbox_to_anchor=(0, 1.02))
    save(fig, "图2_资源需求与库存.png")


def plot_deficit_overhead(inventory):
    resources = list(RESOURCE_NAMES)
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.5), sharey=True)
    x = np.arange(len(resources)); width = 0.34
    for i, k in enumerate([2, 3]):
        sub = inventory[inventory["K"] == k].set_index("resource").reindex(resources)
        axes[0].bar(x + (i - 0.5) * width, sub["inventory_deficit"], width, color=GROUP_COLORS[i], label=f"K={k}")
        axes[1].bar(x + (i - 0.5) * width, sub["partition_overhead"], width, color=GROUP_COLORS[i], label=f"K={k}")
    for ax, title, ylabel in [(axes[0], "库存缺口", "缺口数量"), (axes[1], "分区复制开销", "额外配置数量")]:
        ax.set_xticks(x, [RESOURCE_NAMES[r] for r in resources], rotation=25, ha="right")
        ax.set_title(title, fontweight="bold"); ax.set_ylabel(ylabel); ax.grid(axis="y", color="#dfe7ee", lw=0.8)
        ax.spines[["top", "right"]].set_visible(False); ax.legend(frameon=False, loc="upper left")
    fig.suptitle("分区造成的资源缺口与复制开销", y=1.02, fontsize=14, fontweight="bold")
    save(fig, "图3_库存缺口与复制开销.png")


def plot_workload(workload):
    df = workload.copy(); df["组标签"] = "K" + df["K"].astype(str) + "-G" + df["group"].astype(str)
    df["relay_sortie_count"] = df["relay_sorties"].fillna("").map(lambda value: len([x for x in str(value).split(",") if x and x != "nan"]))
    metrics = [("sortie_count", "运输架次"), ("relay_sortie_count", "中继架次"), ("site_count", "服务区数")]
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.8))
    for ax, (col, label) in zip(axes, metrics):
        colors = [GROUP_COLORS[(int(k) - 2) % 3] for k in df["K"]]
        ax.bar(df["组标签"], df[col], color=colors, alpha=0.88)
        ax.set_title(label, fontweight="bold"); ax.tick_params(axis="x", rotation=45); ax.grid(axis="y", color="#dfe7ee", lw=0.8)
        ax.spines[["top", "right"]].set_visible(False)
        for i, value in enumerate(df[col]): ax.text(i, value + max(df[col].max() * 0.02, 0.1), f"{value:g}", ha="center", fontsize=8)
    fig.suptitle("K=2 与 K=3 分区的任务规模比较", y=1.03, fontsize=14, fontweight="bold")
    save(fig, "图4_分区任务规模.png")


def plot_workload_time_energy(workload):
    df = workload.copy(); df["组标签"] = "K" + df["K"].astype(str) + "-G" + df["group"].astype(str)
    fig, ax = plt.subplots(figsize=(10.5, 5.5))
    for k, group in df.groupby("K"):
        ax.scatter(group["transport_flight_time_s"] / 3600, group["transport_energy_kwh"], s=85,
                   color=GROUP_COLORS[int(k) - 2], label=f"K={k}", edgecolor="white", linewidth=1)
        for _, row in group.iterrows():
            ax.annotate(row["组标签"], (row["transport_flight_time_s"] / 3600, row["transport_energy_kwh"]),
                        xytext=(5, 4), textcoords="offset points", fontsize=8)
    ax.set_xlabel("运输飞行时间 / h"); ax.set_ylabel("运输能耗 / kWh")
    ax.set_title("分区运输工作量的时间—能耗关系", pad=12, fontweight="bold")
    ax.grid(color="#dfe7ee", lw=0.8); ax.spines[["top", "right"]].set_visible(False); ax.legend(frameon=False)
    save(fig, "图5_运输时间与能耗.png")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    inventory, workload, mapping = load_data()
    plot_partitions(mapping); plot_resource_inventory(inventory); plot_deficit_overhead(inventory)
    plot_workload(workload); plot_workload_time_energy(workload)
    (OUT / "图表索引.md").write_text(
        "# 问题4图表\n\n| 文件 | 论文用途 |\n|---|---|\n"
        "| 图1_K2与K3任务分区.png | 展示 K=2/K=3 服务区分区空间结构 |\n"
        "| 图2_资源需求与库存.png | 比较两种分区的资源总需求和现有库存 |\n"
        "| 图3_库存缺口与复制开销.png | 展示库存缺口及分区复制带来的额外配置 |\n"
        "| 图4_分区任务规模.png | 比较各任务组的架次和服务区数量 |\n"
        "| 图5_运输时间与能耗.png | 展示各组运输工作量的时间—能耗关系 |\n\n"
        "数据来源：outputs/problem4/final；分区和资源需求固定继承问题3时间轴。\n",
        encoding="utf-8")


if __name__ == "__main__":
    main()
