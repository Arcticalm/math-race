"""把统一求解器的结果同步到每一问的独立目录。

用法（仓库根目录）：

    python sync_outputs.py

来源与目标：

    outputs/unified/final/q2/*  ->  outputs/problem2/
    outputs/unified/final/q3/*  ->  outputs/problem3/
    outputs/unified/final/q4/*  ->  outputs/problem4/

第三、四问的结果固定继承同一次第三问求解，因此 q3 与 q4 必须成套同步，
本脚本一次复制、不做选择。问题一由 final_code/problem1_final/solver.py
直接写入 outputs/problem1/，不经过这里。

同步完成后即可运行 pic/问题N/plot_problemN.py 出图。
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "outputs" / "unified" / "final"
TARGETS = {
    SOURCE / "q2": ROOT / "outputs" / "problem2",
    SOURCE / "q3": ROOT / "outputs" / "problem3",
    SOURCE / "q4": ROOT / "outputs" / "problem4",
}


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(
            f"未找到 {SOURCE.relative_to(ROOT)}；请先运行统一求解器并执行 compare_runs：\n"
            "  python -m final_code.unified.solver --output outputs/unified/run1\n"
            "  python -m final_code.unified.compare_runs outputs/unified/run1 "
            "--output outputs/unified/final"
        )
    for source, target in TARGETS.items():
        if not source.exists():
            raise SystemExit(f"缺少 {source.relative_to(ROOT)}")
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        print(f"{source.relative_to(ROOT)} -> {target.relative_to(ROOT)}"
              f"  ({len(list(target.iterdir()))} 个文件)")
    # 候选方案指标表由 publish 写在 outputs/unified/ 根目录，问题二的权衡图需要它。
    candidates = ROOT / "outputs" / "unified" / "time_priority_candidates.csv"
    if candidates.exists():
        shutil.copy2(candidates, ROOT / "outputs" / "problem2" / candidates.name)
        print(f"{candidates.relative_to(ROOT)} -> outputs/problem2/{candidates.name}")
    print("同步完成，可运行 pic/问题N/plot_problemN.py 出图。")


if __name__ == "__main__":
    main()
