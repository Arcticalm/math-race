# 问题二：完成时间优先求解

从仓库根目录运行：

```bash
python3 -m src.problem23.solver
```

依赖列在 `requirements.txt`。安装 OR-Tools 后，对每种固定组批方案使用 CP-SAT 联合分配实体无人机、电池和开始时刻，并以最后一个架次返回 O01 的时刻为首要目标；没有 OR-Tools 时使用确定性排程器生成可审计的候选方案。两种模式均对所有输出架次进行逐段、逐箱、硬时限、资源占用及电池充电复核。

组批候选包括逐服务区精确集合划分、原构造式划分以及对应的两区合并方案。此候选范围不覆盖第二问所有跨区货箱组合，所以即使某固定组批的 CP-SAT 状态为 `OPTIMAL`，也不能称完整第二问全局最优。CP-SAT 使用整秒保守取整；输出中的时刻和能耗以原浮点物理模型重新计算并审计。

结果保存在 `outputs/problem23/`：`problem2_submission.xlsx`、逐架次/逐箱/电池 CSV、资源甘特图、路线图、送达时间图、`time_priority_tradeoff.png` 和 `time_priority_candidates.csv`。`validation.json` 记录审计结果及求解范围；`problem23_summary.json` 摘要主方案。
