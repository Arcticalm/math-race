"""论文图表：问题3（通信保障下的运输与中继联合调度）。"""
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
DATA = ROOT / "outputs" / "problem3" / "refactored" / "final"
OUT = Path(__file__).resolve().parent
BASE = ROOT / "data" / "无人机应急物资运输基础数据"
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
    link = pd.read_csv(DATA / "link_samples.csv")
    twohop = pd.read_csv(DATA / "two_hop_link_audit.csv")
    history = pd.read_csv(DATA / "iteration_history.csv")
    transport = pd.read_csv(DATA / "transport_inherited_audit.csv")
    return communication, relay, schedule, link, twohop, history, transport


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


def plot_link_margin(link, twohop):
    direct = link[link["available"] == True].copy()
    relay = twohop[twohop["both_available"] == True].copy()
    vals = [direct["threshold_db"] - direct["path_loss_db"], relay["access_limit_db"] - relay["access_loss_db"], relay["backhaul_limit_db"] - relay["backhaul_loss_db"]]
    labels = ["直连链路", "中继接入", "中继回传"]
    fig, ax = plt.subplots(figsize=(8.8, 5.5))
    ax.boxplot(vals, tick_labels=labels, patch_artist=True, boxprops={"facecolor": "#dce9ed"}, medianprops={"color": "#b45b3c", "lw": 2})
    ax.axhline(0, color="#52606d", ls="--", lw=1)
    ax.set_ylabel("链路裕量 / dB（门限 − 路径损耗）"); ax.set_title("通信链路可用性裕量分布", pad=12, fontweight="bold")
    ax.grid(axis="y", color="#dfe7ee", lw=0.8); ax.spines[["top", "right"]].set_visible(False)
    save(fig, "图5_链路裕量分布.png")


def plot_iterations(history):
    fig, ax = plt.subplots(figsize=(7.8, 4.8))
    ax.plot(history["iteration"], history["gap_count"], marker="o", lw=2.2, color="#b45b3c")
    ax.set_xlabel("协调迭代轮次"); ax.set_ylabel("待覆盖通信缺口数")
    ax.set_title("通信缺口协调过程", pad=12, fontweight="bold")
    ax.grid(color="#dfe7ee", lw=0.8); ax.spines[["top", "right"]].set_visible(False)
    save(fig, "图6_通信缺口迭代.png")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    communication, relay, schedule, link, twohop, history, transport = load()
    plot_joint_gantt(relay, transport); plot_communication(communication); plot_relay_map(schedule)
    plot_relay_resources(relay); plot_link_margin(link, twohop); plot_iterations(history)
    (OUT / "图表索引.md").write_text(
        "# 问题3图表\n\n| 文件 | 论文用途 |\n|---|---|\n"
        "| 图1_联合任务时间轴.png | 展示运输与中继架次的联合完成过程 |\n"
        "| 图2_通信保障构成.png | 比较各运输架次直连与中继保障时长 |\n"
        "| 图3_中继空间部署.png | 展示中继悬停点、服务区和地形背景 |\n"
        "| 图4_中继资源周转.png | 展示两架中继无人机的任务衔接 |\n"
        "| 图5_链路裕量分布.png | 展示直连、接入、回传链路安全裕量 |\n"
        "| 图6_通信缺口迭代.png | 展示协调迭代中待覆盖缺口的变化 |\n\n"
        "数据来源：outputs/problem3/refactored/final；方案状态与连续通信认证结果见 screening.json。\n",
        encoding="utf-8")


if __name__ == "__main__":
    main()
