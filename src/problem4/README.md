# 第四问代码

运行：

```bash
.venv/bin/python -m src.problem4.solver
```

程序严格要求 `outputs/problem3/screening.json` 的 `feasible` 和
`continuity_certified` 均为 `true`，并要求运输审计及中继排程存在。前置条件不满足时只写出
`outputs/problem4/status.json`，状态为“等待 Q3 最终方案”，不会把候选中继点或中断通信当作有效 Q3 输入。

资源峰值按固定 Q3 时间轴和半开区间计算；电池、能源组件区间延伸至按题面两阶段充电公式充满。库存全部从源工作簿读取。
