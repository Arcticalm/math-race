# 四问最终代码

从仓库根目录执行，Python 环境安装 `final_code/requirements.txt`。数据仍从 `data/` 读取，提交模板仍从 `docs/结果提交模板.xlsx` 读取。

| 问题 | 代码入口 | 主要方法 | 已有结果 |
| --- | --- | --- | --- |
| 一 | `final_code.problem1.solver` | 单服务区组批、地形与能耗核算，默认含返航余量与能耗率敏感性 | `outputs/problem1/` |
| 二 | `final_code.problem2.run` | 共同路线模式库、CP-SAT 独立选择组批与排程、连续时间审计 | `outputs/unified/final/q2/` |
| 三 | `final_code.problem3.run` | 同一模式库重新选择运输方案，并联合选中继任务、连续通信审计 | `outputs/unified/final/q3/` |
| 四 | `final_code.problem4.solver` | 冻结第三问方案，完整枚举 K=2、K=3 分区与资源配置 | `outputs/unified/final/q4/` |

底层物理与审计模块由已有 `outputs/unified/final/unified_program.zip` 中的最终程序恢复，整理时仅调整了模块路径和程序打包路径。

问题二的 `patterns.py` 是第二、三问共用的模式库；`master.py` 在无中继参数时求第二问，传入通信需求后联合求第三问。各问的底层物理与审计实现随所属目录保存，模块通过 `final_code` 内部路径互相引用。`package.py` 负责把完整可运行程序和题目提交模板打包。

逐问运行示例：

```bash
.venv/bin/python -m final_code.problem1.solver --output outputs/problem1
.venv/bin/python -m final_code.problem2.run --output outputs/problem2/final_code --time-limit 120
.venv/bin/python -m final_code.problem3.run --output outputs/problem3/final_code --time-limit 120 --max-relays 10
.venv/bin/python -m final_code.problem4.solver --input outputs/unified/final/q3 --output outputs/problem4/final_code
```

第二问独立优化、第三问联合重选、第四问冻结分区及反馈迭代的**完整联动**用 `run_all` 一次完成。交付结果采用**独立第三问**（`--q3-partition-groups 0`，默认值，不预留第四问分区）：

```bash
.venv/bin/python -m final_code.run_all --output outputs/unified/run01 \
  --rounds 2 --time-limit 120 --max-relays 10 --q3-partition-groups 0
.venv/bin/python -m final_code.compare_runs outputs/unified/run01 --output outputs/unified/final
.venv/bin/python -m final_code.publish --source outputs/unified/final --output outputs/unified \
  --q1-source outputs/problem1
```

传入 `--q3-partition-groups 2` 或 `3` 则改为四问联动：第三问额外要求冻结后的排程可划分为对应数量的任务组。两种范围的得分不可互相比较，`compare_runs` 会按运行记录的范围重算。输出目录应为空。多次运行的筛选及统一图表发布分别由 `final_code.compare_runs` 和 `final_code.publish` 完成；参数与最优性范围见 [模型说明](MODEL.md)。第二、三问是有限模式库和候选位置集上的优化，代码会记录求解状态和下界，不能据此声称原始连续问题的全局最优。
