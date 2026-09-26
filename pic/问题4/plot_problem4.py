"""论文图表：问题4（救援任务分区与资源配置）。"""
from pathlib import Path
import base64
from io import BytesIO
import re
import csv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.patches import Patch
import numpy as np
from PIL import Image

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "outputs" / "q4"
OUT = Path(__file__).resolve().parent
BASE = ROOT / "data" / "无人机应急物资运输基础数据"
GROUP_COLORS = ["#287a8c", "#d3b532", "#b45b3c"]
RESOURCE_NAMES = {
    "A_airframe": "A型机体", "B_airframe": "B型机体", "C_airframe": "C型机体",
    "A_battery": "A型电池", "B_battery": "B型电池", "C_battery": "C型电池",
    "relay_airframe": "中继机体", "relay_energy": "中继能源组件",
}

font_path = ROOT / "paper" / "fonts" / "SourceHanSerifCN-Regular.otf"
if font_path.exists():
    fm.fontManager.addfont(str(font_path))
    plt.rcParams["font.sans-serif"] = ["Source Han Serif CN", "Noto Sans CJK SC", "Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["font.family"] = "sans-serif"
else:
    plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "Microsoft YaHei", "SimHei", "DejaVu Sans"]

plt.rcParams.update({
    "axes.unicode_minus": False, "figure.dpi": 160, "savefig.dpi": 300,
    "axes.titlesize": 14, "axes.labelsize": 11, "xtick.labelsize": 9, "ytick.labelsize": 9,
})


def save(fig, name):
    fig.savefig(OUT / name, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def read_nodes():
    if load_workbook is not None:
        ws = load_workbook(BASE / "调度中心与服务区.xlsx", read_only=True, data_only=True).active
        result = {}
        for row in ws.iter_rows(values_only=True):
            if row and row[0] and (row[0] == "O01" or str(row[0]).startswith("S")):
                result[str(row[0])] = (float(row[2]), float(row[3]))
        return result
    xlsx_path = BASE / "调度中心与服务区.xlsx"
    if xlsx_path.exists():
        import zipfile
        import xml.etree.ElementTree as ET
        with zipfile.ZipFile(xlsx_path) as z:
            strings = []
            if "xl/sharedStrings.xml" in z.namelist():
                sst = ET.fromstring(z.read("xl/sharedStrings.xml"))
                for si in sst:
                    t = si.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
                    strings.append(t.text if t is not None else "".join(si.itertext()))
            sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
            ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
            result = {}
            for row in sheet.findall(f".//{ns}row"):
                r_vals = []
                for c in row.findall(f"{ns}c"):
                    t_attr = c.get("t")
                    v = c.find(f"{ns}v")
                    val = v.text if v is not None else None
                    if t_attr == "s" and val is not None:
                        val = strings[int(val)]
                    r_vals.append(val)
                if r_vals and r_vals[0] and (r_vals[0] == "O01" or str(r_vals[0]).startswith("S")):
                    result[str(r_vals[0])] = (float(r_vals[2]), float(r_vals[3]))
            return result
    return {}


def draw_terrain(ax):
    html = ROOT / "data" / "镇龙乡地理空间数据" / "镇龙乡地理空间详情地图.html"
    text = html.read_text(encoding="utf-8")
    match = re.search(r'const terrainUrl = "data:image/png;base64,([^\"]+)"', text)
    if match:
        image = np.asarray(Image.open(BytesIO(base64.b64decode(match.group(1)))).convert("RGB"))
        ax.imshow(image, extent=(109.0328115248, 109.4450943306, 22.8615453408, 23.2247021255),
                  origin="upper", alpha=0.65, zorder=-2, aspect="auto")


def _read_csv_dicts(path):
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def load_data():
    if pd is not None:
        inventory = pd.read_csv(DATA / "inventory_comparison.csv")
        workload = pd.read_csv(DATA / "workload_comparison.csv")
        mapping = pd.read_csv(DATA / "site_mapping_audit.csv")
    else:
        inventory = _read_csv_dicts(DATA / "inventory_comparison.csv")
        workload = _read_csv_dicts(DATA / "workload_comparison.csv")
        mapping = _read_csv_dicts(DATA / "site_mapping_audit.csv")
    return inventory, workload, mapping


def plot_partitions(mapping):
    coords = read_nodes()
    if not coords:
        return
    fig, axes = plt.subplots(1, 2, figsize=(12.8, 6.8), sharex=True, sharey=True)
    for ax, k in zip(axes, [2, 3]):
        draw_terrain(ax)
        if hasattr(mapping, "loc") or (hasattr(mapping, "__getitem__") and hasattr(mapping, "columns")):
            sub = mapping[mapping["K"] == k]
            groups = sorted(sub["group"].unique())
            group_sites = {g: sub[sub["group"] == g]["site"].tolist() for g in groups}
        else:
            sub = [r for r in mapping if int(r["K"]) == k]
            groups = sorted(set(int(r["group"]) for r in sub))
            group_sites = {g: [r["site"] for r in sub if int(r["group"]) == g] for g in groups}

        for group in groups:
            sites = group_sites[group]
            xy = np.asarray([coords[s] for s in sites if s in coords])
            if len(xy) == 0:
                continue
            ax.scatter(xy[:, 0], xy[:, 1], s=85, color=GROUP_COLORS[group - 1], edgecolor="white", linewidth=0.8, zorder=3,
                       label=f"任务组 {group}")
            for site, (x, y) in zip(sites, xy):
                ax.annotate(site, (x, y), xytext=(4, 4), textcoords="offset points", fontsize=7,
                            color="#26323c", bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.68, "pad": 0.6})
        center = coords.get("O01", (109.2308517, 23.0085095))
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
    resources = list(RESOURCE_NAMES)
    x = np.arange(len(resources)); width = 0.22
    fig, ax = plt.subplots(figsize=(11.5, 5.8))
    for idx, k in enumerate([2, 3]):
        if hasattr(inventory, "set_index"):
            totals = inventory[inventory["K"] == k].set_index("resource").reindex(resources)["total_demand"]
        else:
            k_rows = {r["resource"]: float(r["total_demand"]) for r in inventory if int(r["K"]) == k}
            totals = [k_rows.get(r, 0.0) for r in resources]
        ax.bar(x + (idx - 1) * width, totals, width, color=GROUP_COLORS[idx], label=f"K={k}总需求")
    if hasattr(inventory, "set_index"):
        stock = inventory[inventory["K"] == 2].set_index("resource").reindex(resources)["inventory"]
    else:
        k_rows = {r["resource"]: float(r["inventory"]) for r in inventory if int(r["K"]) == 2}
        stock = [k_rows.get(r, 0.0) for r in resources]
    ax.bar(x + width, stock, width, color="#59636d", alpha=0.45, label="现有库存")
    ax.set_xticks(x)
    ax.set_xticklabels([RESOURCE_NAMES[r] for r in resources], rotation=25, ha="right")
    ax.set_ylabel("资源数量 / 组或架"); ax.set_title("不同分区方案的资源需求与现有库存", pad=12, fontweight="bold")
    ax.grid(axis="y", color="#dfe7ee", lw=0.8); ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=3, loc="upper left", bbox_to_anchor=(0, 1.02))
    save(fig, "图2_资源需求与库存.png")


def plot_deficit_overhead(inventory):
    resources = list(RESOURCE_NAMES)
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.5), sharey=True)
    x = np.arange(len(resources)); width = 0.34
    
    # 提取 K=2 和 K=3 的指标
    for i, k in enumerate([2, 3]):
        if hasattr(inventory, "set_index"):
            sub = inventory[inventory["K"] == k].set_index("resource").reindex(resources)
            deficits = sub["inventory_deficit"].astype(float).values
            overheads = sub["partition_overhead"].astype(float).values
        else:
            k_rows = {r["resource"]: r for r in inventory if int(r["K"]) == k}
            deficits = [float(k_rows[r]["inventory_deficit"]) for r in resources]
            overheads = [float(k_rows[r]["partition_overhead"]) for r in resources]
        axes[0].bar(x + (i - 0.5) * width, deficits, width, color=GROUP_COLORS[i], label=f"K={k}")
        axes[1].bar(x + (i - 0.5) * width, overheads, width, color=GROUP_COLORS[i], label=f"K={k}")
        
    for ax, title, ylabel in [(axes[0], "库存缺口", "缺口数量"), (axes[1], "分区复制开销", "额外配置数量")]:
        ax.set_xticks(x)
        ax.set_xticklabels([RESOURCE_NAMES[r] for r in resources], rotation=25, ha="right")
        ax.set_title(title, fontweight="bold", pad=12)
        ax.set_ylabel(ylabel)
        ax.set_ylim(0, 1.38)
        ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
        ax.grid(axis="y", color="#dfe7ee", lw=0.8)
        ax.spines[["top", "right"]].set_visible(False)
        # 图例移至右上角空旷区域，带白色衬底，彻底解决与左侧柱状图重叠问题
        ax.legend(frameon=True, facecolor="white", edgecolor="#d0d7de", framealpha=0.95, loc="upper right")
    fig.suptitle("分区造成的资源缺口与复制开销", y=1.01, fontsize=14, fontweight="bold")
    save(fig, "图3_库存缺口与复制开销.png")


def plot_workload(workload):
    if hasattr(workload, "columns"):
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
    else:
        labels = [f"K{r['K']}-G{r['group']}" for r in workload]
        sorties = [float(r["sortie_count"]) for r in workload]
        relays = [len([x for x in str(r.get("relay_sorties", "")).split(",") if x and x != "nan"]) for r in workload]
        sites = [float(r["site_count"]) for r in workload]
        metrics = [(sorties, "运输架次"), (relays, "中继架次"), (sites, "服务区数")]
        fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.8))
        for ax, (data, label) in zip(axes, metrics):
            colors = [GROUP_COLORS[(int(r["K"]) - 2) % 3] for r in workload]
            ax.bar(labels, data, color=colors, alpha=0.88)
            ax.set_title(label, fontweight="bold"); ax.tick_params(axis="x", rotation=45); ax.grid(axis="y", color="#dfe7ee", lw=0.8)
            ax.spines[["top", "right"]].set_visible(False)
            for i, value in enumerate(data): ax.text(i, value + max(max(data) * 0.02, 0.1), f"{value:g}", ha="center", fontsize=8)
    fig.suptitle("K=2 与 K=3 分区的任务规模比较", y=1.03, fontsize=14, fontweight="bold")
    save(fig, "图4_分区任务规模.png")


def plot_workload_time_energy(workload):
    points = []
    if hasattr(workload, "iterrows"):
        for _, row in workload.iterrows():
            k = int(row["K"])
            g = int(row["group"])
            t_h = float(row["transport_flight_time_s"]) / 3600
            e_kwh = float(row["transport_energy_kwh"])
            points.append({"K": k, "group": g, "time": t_h, "energy": e_kwh, "tag": f"K{k}-G{g}"})
    else:
        for r in workload:
            k = int(r["K"])
            g = int(r["group"])
            t_h = float(r["transport_flight_time_s"]) / 3600
            e_kwh = float(r["transport_energy_kwh"])
            points.append({"K": k, "group": g, "time": t_h, "energy": e_kwh, "tag": f"K{k}-G{g}"})

    fig, ax = plt.subplots(figsize=(10.5, 5.8))
    
    # 绘制散点：重合点通过大小差异保证可见
    for k in [2, 3]:
        k_pts = [p for p in points if p["K"] == k]
        xs = [p["time"] for p in k_pts]
        ys = [p["energy"] for p in k_pts]
        size = 110 if k == 2 else 75
        ax.scatter(xs, ys, s=size, color=GROUP_COLORS[k - 2], label=f"K={k}", edgecolor="white", linewidth=1.2, zorder=4)

    # 针对性解决重叠问题：定制无重叠标注偏移、对齐方式与带背景框的引线指示
    annotations_config = {
        "K2-G1": {
            "label": "K2-G1 (主体组)",
            "xytext": (14, 0),
            "ha": "left",
            "va": "center",
            "color": "#1d5c6b",
        },
        "K3-G1": {
            "label": "K3-G1 (主体组)",
            "xytext": (-16, 14),
            "ha": "right",
            "va": "bottom",
            "color": "#947600",
        },
        "K3-G2": {
            "label": "K3-G2 (S006组)",
            "xytext": (28, 16),
            "ha": "left",
            "va": "center",
            "color": "#947600",
        },
        "K2-G2": {
            "label": "K2-G2 (S011组)",
            "xytext": (28, 2),
            "ha": "left",
            "va": "center",
            "color": "#1d5c6b",
        },
        "K3-G3": {
            "label": "K3-G3 (S011组·点位重合)",
            "xytext": (28, -12),
            "ha": "left",
            "va": "center",
            "color": "#947600",
        },
    }

    for p in points:
        cfg = annotations_config.get(p["tag"], {"label": p["tag"], "xytext": (10, 10), "ha": "left", "va": "bottom", "color": "#333"})
        arrowprops = dict(
            arrowstyle="->",
            color=cfg["color"],
            lw=0.9,
            shrinkA=3,
            shrinkB=5
        )
        ax.annotate(
            cfg["label"],
            (p["time"], p["energy"]),
            xytext=cfg["xytext"],
            textcoords="offset points",
            fontsize=9,
            fontweight="bold",
            color=cfg["color"],
            ha=cfg["ha"],
            va=cfg["va"],
            bbox=dict(boxstyle="round,pad=0.28", facecolor="white", edgecolor="#cbd5e1", alpha=0.95, lw=0.8),
            arrowprops=arrowprops,
            zorder=5
        )

    ax.set_xlabel("运输飞行时间 / h", labelpad=6)
    ax.set_ylabel("运输能耗 / kWh", labelpad=6)
    ax.set_title("分区运输工作量的时间—能耗关系", pad=14, fontweight="bold")
    ax.set_xlim(-0.3, 11.2)
    ax.set_ylim(-5, 78)
    ax.grid(color="#dfe7ee", lw=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=True, facecolor="white", edgecolor="#d0d7de", framealpha=0.95, loc="upper left", bbox_to_anchor=(0.02, 0.98))
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
