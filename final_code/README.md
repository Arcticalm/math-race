# 四问代码与复现

只保留正式求解、物理模型、审计和结果发布流程。原始数据从 `data/` 读取，表头和格式以 `docs/结果提交模板.xlsx` 为准。

```text
final_code/
├── problem1/solver.py       单点能力、精确组批、敏感性
├── problem2/
│   ├── run.py              第二问独立入口
│   ├── patterns.py         二、三问共享模式库
│   ├── master.py           CP-SAT 联合选择与排程
│   ├── transport.py        运输物理、资源、导出及热启动
│   ├── groups.py           初始精确组批
│   └── terrain_audit.py    全像元巡航净空检查
├── problem3/
│   ├── run.py              第三问联合重选入口
│   ├── communication.py    通信需求与位置候选
│   ├── physics.py          链路、中继物理与区间证明
│   ├── trajectory.py       运输轨迹、时限及模板导出
│   ├── refine.py           固定离散决策的连续 LP
│   └── audit.py            连续通信与中继资源检查
├── problem4/solver.py       严格冻结任务分区与资源核算
├── run_all.py              共同库、多轮求解与分区反馈
├── compare_runs.py         相同范围的候选比较
├── replay.py               读取保存方案及连续回代
├── review.py               从源数据重新审计最终结果
├── submission.py           按题目模板分类并汇总
├── summary_workbook.py     四问指标汇总
├── publish.py              图表、结果树、文件清单
├── package.py              一份完整可运行程序包
├── requirements.txt        统一依赖
└── 四问流程算法与题目审查.md
```

安装依赖与验证：

```bash
.venv/bin/python -m pip install -r final_code/requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m final_code.review --source outputs --output /tmp/math-race-audit
```

当前最终结果见 [outputs](../outputs/README.md)。重新分类和生成图表、提交表、指标汇总及程序包：

```bash
.venv/bin/python -m final_code.publish
```

逐问重算时使用空的新目录，避免覆盖已选方案：

```bash
.venv/bin/python -m final_code.problem1.solver --output /tmp/math-race-q1
.venv/bin/python -m final_code.problem2.run --output /tmp/math-race-q2 --time-limit 240
.venv/bin/python -m final_code.problem3.run --output /tmp/math-race-q3 --time-limit 240
.venv/bin/python -m final_code.problem4.solver --input outputs/q3 --output /tmp/math-race-q4
```

统一求解与选择示例：

```bash
.venv/bin/python -m final_code.run_all --output /tmp/math-race-run \
  --rounds 2 --time-limit 240 --expanded-locations --q3-partition-groups 0
.venv/bin/python -m final_code.compare_runs outputs /tmp/math-race-run \
  --output /tmp/math-race-selected
.venv/bin/python -m final_code.publish --source /tmp/math-race-selected \
  --q1-source outputs/q1 --output /tmp/math-race-delivery
```

`0` 是独立第三问；`2/3` 是额外预留分区的联动范围，只有联动范围加入分区反馈。不同范围不可混比。第二、三问仍为有限模式/选址库上的最好已知解，不声称原题全局最优。详见 [四问流程、算法与审查](四问流程算法与题目审查.md)。
