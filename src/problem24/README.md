# NSGA-II + CP-SAT 双层求解

运行：

```bash
.venv/bin/python -m sec.problem24.solver
```

外层使用 NSGA-II：染色体为 15 个服务区的组批策略编号，加一个是否尝试双服务区贪心合并的基因。交叉和变异产生新的组批候选，目标为完成时间、加权迟到、能耗和架次。

内层先用快速构造式排程评价整个种群；每一代只将非支配精英送入 CP-SAT，决定机型、实体无人机、电池和开始时刻。CP-SAT 的 `NoOverlap` 约束无人机占用和电池充电，医疗/首批时限为硬约束，目标优先最小化最后返航时间。

结果写入 `outputs/problem24/`。`nsga2_candidates.csv` 和 `nsga2_tradeoff.png` 展示搜索到的候选和非支配关系；`problem24_summary.json` 记录 CP-SAT 调用次数、缓存命中、种群参数和最优性状态。该方法是候选范围内的混合启发式搜索，不能证明完整第二问的全局最优。
