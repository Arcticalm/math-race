"""论文图表：问题1（单点往返运输能力与货箱组批）。

运行：./.venv/bin/python pic/问题1/plot_problem1.py
图表与派生表均写入本脚本所在目录。
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "outputs" / "problem1"
OUT = Path(__file__).resolve().parent

plt.rcParams.update({
    "font.sans-serif": ["Noto Sans CJK SC", "Microsoft YaHei", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "figure.dpi": 160,
    "savefig.dpi": 300,
    "axes.titlesize": 14,
    "axes.labelsize": 11,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
})
COLORS = {"A": "#1769aa", "B": "#e08e0b", "C": "#c44536"}
PALETTE = ["#1769aa", "#35a7a0", "#e08e0b", "#c44536"]


def save(fig: plt.Figure, name: str) -> None:
    fig.savefig(OUT / name, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    safe = pd.read_csv(DATA / "safe_payloads.csv")
    area = pd.read_csv(DATA / "service_area_summary.csv")
    batches = pd.read_csv(DATA / "batches_detailed.csv")
    sensitivity = pd.read_csv(DATA / "sensitivity_summary.csv")
    tradeoff = pd.read_csv(DATA / "objective_tradeoff.csv")
    return safe, area, batches, sensitivity, tradeoff


def plot_payload_heatmap(safe: pd.DataFrame) -> None:
    pivot = safe.pivot(index="site", columns="aircraft", values="max_safe_payload_kg").reindex(columns=["A", "B", "C"])
    fig, ax = plt.subplots(figsize=(7.2, 6.0))
    cmap = LinearSegmentedColormap.from_list("capacity", ["#e8f1f7", "#61b4b0", "#e08e0b", "#c44536"])
    im = ax.imshow(pivot.values, cmap=cmap, aspect="auto", vmin=0, vmax=max(80, pivot.to_numpy().max()))
    ax.set_xticks(range(3), ["A型", "B型", "C型"])
    ax.set_yticks(range(len(pivot)), pivot.index)
    ax.set_xlabel("运输无人机机型")
    ax.set_ylabel("服务区")
    ax.set_title("各服务区—机型最大安全载荷", pad=12, fontweight="bold")
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            value = pivot.iloc[i, j]
            ax.text(j, i, f"{value:.1f}", ha="center", va="center", fontsize=9,
                    color="white" if value > 55 else "#17324d", fontweight="bold")
    cbar = fig.colorbar(im, ax=ax, pad=0.03, shrink=0.86)
    cbar.set_label("最大安全载荷 / kg")
    ax.spines[:].set_visible(False)
    ax.tick_params(length=0)
    save(fig, "图1_最大安全载荷热图.png")


def plot_distance_payload(safe: pd.DataFrame) -> None:
    summary = safe.drop_duplicates("site").sort_values("route_distance_m").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(11.0, 6.8))
    for aircraft in ["A", "B", "C"]:
        sub = safe[safe.aircraft == aircraft].set_index("site").loc[summary.site].reset_index()
        ax.plot(sub.route_distance_m / 1000, sub.max_safe_payload_kg, marker="o", lw=2.4,
                ms=6.5, color=COLORS[aircraft], label=f"{aircraft}型")
    # 15 个服务区全部用引线标注：从该点的 C 型载荷处牵到标签。
    # 排版的三个约束：引线要看得见（与数据点至少差 8 kg）、标签之间不重叠、
    # 引线本身不互相压住。距离轴上有几对点几乎重合（S002 与 S012 只差 37 m、
    # S010 与 S013 差 70 m、S005 与 S014 差 109 m），若标签都放在各自点正下方，
    # 引线会近乎平行重合，因此对这些点额外做水平错位，让引线呈扇形散开。
    c_type = safe[safe.aircraft == "C"].set_index("site")["max_safe_payload_kg"]
    distance = safe.drop_duplicates("site").set_index("site")["route_distance_m"] / 1000
    limited = [s for s in summary.site if c_type[s] < 80.0]      # C 型受电量约束的点
    normal = [s for s in summary.site if s not in limited]

    labels = {}
    rows_y = (64.0, 48.0)
    nudge = {"S010": -0.17, "S013": +0.24, "S005": -0.13, "S014": +0.21, "S007": -0.16}
    placed = {0: [], 1: []}
    for index, site in enumerate(normal):
        level = index % 2
        x = distance[site] + nudge.get(site, 0.0)
        if placed[level] and x - placed[level][-1] < 0.40:
            x = placed[level][-1] + 0.40
        placed[level].append(x)
        labels[site] = (x, rows_y[level])
    # 受约束的 5 个点集中在 x>7.2 的右区，手工定位：除 S002 的标签置于其上方
    # （否则引线只有 4.6 kg 高、几乎不可见）外，其余标签下移到 y=50 一带，
    # 引线长度都在 8 kg 以上，且彼此错开。
    labels.update({"S003": (6.98, 77.0), "S002": (7.72, 80.0), "S012": (7.36, 50.0),
                   "S004": (7.86, 50.0), "S008": (8.34, 50.0)})

    for site, (x, y) in labels.items():
        ax.annotate(site, xy=(distance[site], c_type[site]), xytext=(x, y),
                    textcoords="data", ha="center", va="center",
                    fontsize=11.5, color="#39434d",
                    bbox={"facecolor": "white", "edgecolor": "none", "pad": 1.6},
                    arrowprops={"arrowstyle": "-", "color": "#9aa7b2",
                                "lw": 0.9, "shrinkA": 1, "shrinkB": 2})
    ax.axvline(7.2, color="#9aa7b2", ls="--", lw=1.2)
    ax.annotate("C 型电量约束区间（距离 $\\geq$ 7.2 km）", xy=(7.12, 91),
                fontsize=12.5, color="#52606d", ha="right", va="center")
    ax.set_xlabel("O01—服务区往返航线距离 / km", fontsize=13)
    ax.set_ylabel("最大安全载荷 / kg", fontsize=13)
    ax.set_title("航线距离与最大安全载荷的关系", pad=12, fontsize=16, fontweight="bold")
    ax.set_ylim(bottom=0, top=100)
    ax.set_xlim(2.3, 8.6)
    ax.tick_params(axis="both", labelsize=12)
    ax.grid(axis="y", color="#dfe7ee", lw=0.8)
    # 图例放在左中部空白区：右侧留给 C 型下降段，上方留给区间注释。
    ax.legend(frameon=False, ncol=1, loc="lower left", bbox_to_anchor=(0.015, 0.02),
              borderaxespad=0, handlelength=2.4, labelspacing=0.9, fontsize=13)
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "图2_距离与安全载荷.png")


def plot_area_load(area: pd.DataFrame) -> None:
    df = area.sort_values("总能耗（kWh）", ascending=True)
    fig, axes = plt.subplots(1, 2, figsize=(11.2, 5.3), sharey=True, gridspec_kw={"wspace": 0.08})
    axes[0].barh(df["服务区编号"], df["总能耗（kWh）"], color="#1769aa", alpha=0.9)
    axes[0].set_xlabel("总能耗 / kWh")
    axes[0].set_ylabel("服务区")
    axes[0].set_title("服务区能耗", fontweight="bold")
    axes[1].barh(df["服务区编号"], df["往返架次数"], color="#e08e0b", alpha=0.9)
    axes[1].set_xlabel("往返架次数 / 架")
    axes[1].set_title("服务区架次", fontweight="bold")
    for ax in axes:
        ax.grid(axis="x", color="#dfe7ee", lw=0.8)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.tick_params(axis="y", length=0)
    for y, val in enumerate(df["总能耗（kWh）"]):
        axes[0].text(val + 0.08, y, f"{val:.1f}", va="center", fontsize=8)
    for y, val in enumerate(df["往返架次数"]):
        axes[1].text(val + 0.04, y, f"{int(val)}", va="center", fontsize=8)
    fig.suptitle("各服务区组批方案的运输负荷", y=1.01, fontsize=14, fontweight="bold")
    save(fig, "图3_服务区能耗与架次.png")


def plot_batch_energy(batches: pd.DataFrame) -> None:
    df = batches.copy().sort_values(["服务区编号", "架次编号"])
    labels = [f"{r['服务区编号']}\n{r['架次编号'].split('-')[-1]}" for _, r in df.iterrows()]
    fig, ax = plt.subplots(figsize=(12, 5.2))
    x = np.arange(len(df))
    ax.bar(x, df["去程能耗（kWh）"], color="#1769aa", label="去程")
    ax.bar(x, df["返程能耗（kWh）"], bottom=df["去程能耗（kWh）"], color="#9bc5d8", label="返程")
    for i, (_, row) in enumerate(df.iterrows()):
        ax.text(i, row["往返能耗（kWh）"] + 0.16, row["机型编号"], ha="center", va="bottom",
                fontsize=8, color=COLORS.get(row["机型编号"], "#333"), fontweight="bold")
    ax.set_xticks(x, labels)
    ax.set_xlabel("服务区 / 架次编号")
    ax.set_ylabel("往返能耗 / kWh")
    ax.set_title("组批架次的去程与返程能耗构成", pad=12, fontweight="bold")
    ax.grid(axis="y", color="#dfe7ee", lw=0.8)
    ax.legend(frameon=False, ncol=2, loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "图4_架次能耗构成.png")


def plot_tradeoff(tradeoff: pd.DataFrame) -> None:
    df = tradeoff[(tradeoff["返航余量（%）"] == 20) & (tradeoff["水平能耗率倍率"] == 1.0)].copy()
    df["时间h"] = df["累计作业时间（s）"] / 3600
    points = (df.groupby(["总能耗（kWh）", "时间h"], as_index=False)["目标优先策略"]
                .agg(lambda values: "/".join(values)))
    fig, ax = plt.subplots(figsize=(8.6, 6.2))
    styles = {"架次优先": ("#1769aa", "o"), "能耗优先": ("#c44536", "D"), "时间优先": ("#35a7a0", "s")}
    # 最右点贴近绘图区边界，标注改为向左排，避免溢出坐标区。
    styles_ann = {"架次优先/时间优先": ((-24, 2), "right"), "能耗优先": ((10, 10), "left")}
    for _, row in points.iterrows():
        key = row["目标优先策略"]
        primary = "能耗优先" if "能耗优先" in key else "架次优先"
        color, marker = styles.get(primary, ("#555", "o"))
        ax.scatter(row["总能耗（kWh）"], row["时间h"], s=130, color=color, marker=marker,
                   edgecolor="white", linewidth=1.3, label=row["目标优先策略"])
        offset, align = styles_ann.get(key, ((10, 10), "left"))
        ax.annotate(key, (row["总能耗（kWh）"], row["时间h"]),
                    xytext=offset, textcoords="offset points", ha=align, va="center",
                    fontsize=13, color="#26323c")
    ax.set_xlabel("总运输能耗 / kWh", fontsize=12)
    ax.set_ylabel("累计作业时间 / h", fontsize=12)
    ax.set_title("三种目标优先策略的指标权衡（基准余量 20%）", pad=12,
                 fontsize=15, fontweight="bold")
    ax.tick_params(axis="both", labelsize=11)
    ax.grid(color="#dfe7ee", lw=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_xlim(df["总能耗（kWh）"].min() - 0.006, df["总能耗（kWh）"].max() + 0.006)
    y = points["时间h"]
    ax.set_ylim(y.min() - 0.10, y.max() + 0.10)
    # 图例放到左下空白区：两个数据点都在上方，标在图例原位置会与“能耗优先”的标注重叠。
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    ax.legend(by_label.values(), by_label.keys(), frameon=False, loc="lower left",
              fontsize=12, handletextpad=0.6)
    save(fig, "图5_目标权衡.png")


def plot_sensitivity(sensitivity: pd.DataFrame) -> None:
    df = sensitivity[sensitivity["horizontal_energy_scale"] == 1.0].sort_values("reserve_fraction")
    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.8))
    x = df["reserve_fraction"] * 100
    axes[0].plot(x, df["flight_count"], marker="o", color="#1769aa", lw=2.3)
    axes[0].set_ylabel("总往返架次数 / 架")
    axes[0].set_xlabel("返航安全余量 / %")
    axes[0].set_title("架次响应", fontweight="bold")
    axes[1].plot(x, df["total_energy_kwh"], marker="o", color="#c44536", lw=2.3, label="总能耗")
    ax2 = axes[1].twinx()
    ax2.plot(x, df["total_work_time_s"] / 3600, marker="s", color="#e08e0b", lw=2.0, label="累计作业时间")
    axes[1].set_xlabel("返航安全余量 / %")
    axes[1].set_ylabel("总能耗 / kWh", color="#c44536")
    ax2.set_ylabel("累计作业时间 / h", color="#e08e0b")
    axes[1].set_title("能耗与时间响应", fontweight="bold")
    for ax in axes:
        ax.grid(color="#dfe7ee", lw=0.8)
        ax.spines[["top", "right"]].set_visible(False)
    axes[1].spines["right"].set_visible(False)
    lines = [axes[1].lines[0], ax2.lines[0]]
    axes[1].legend(lines, [line.get_label() for line in lines], frameon=False, loc="upper left")
    fig.suptitle("返航安全余量敏感性（水平能耗率倍率=1）", y=1.02, fontsize=14, fontweight="bold")
    save(fig, "图6_返航余量敏感性.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    safe, area, batches, sensitivity, tradeoff = load()
    plot_payload_heatmap(safe)
    plot_distance_payload(safe)
    plot_area_load(area)
    plot_batch_energy(batches)
    plot_tradeoff(tradeoff)
    plot_sensitivity(sensitivity)
    safe.pivot(index="site", columns="aircraft", values="max_safe_payload_kg").to_csv(OUT / "最大安全载荷矩阵.csv", encoding="utf-8-sig")
    area.to_csv(OUT / "服务区运输汇总.csv", index=False, encoding="utf-8-sig")
    (OUT / "图表索引.md").write_text(
        "# 问题1图表\n\n"
        "| 文件 | 论文用途 |\n|---|---|\n"
        "| 图1_最大安全载荷热图.png | 比较15个服务区与3种机型的安全载荷上限 |\n"
        "| 图2_距离与安全载荷.png | 展示航线距离对安全载荷的影响 |\n"
        "| 图3_服务区能耗与架次.png | 比较服务区组批后的运输负荷 |\n"
        "| 图4_架次能耗构成.png | 展示每架次去程/返程能耗及机型 |\n"
        "| 图5_目标权衡.png | 说明架次、能耗、时间之间的权衡 |\n"
        "| 图6_返航余量敏感性.png | 展示返航安全余量变化的影响 |\n\n"
        "所有数值来自 outputs/problem1 的问题1基准求解结果；图6固定水平能耗率倍率为1。\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
