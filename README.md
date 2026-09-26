# 山区洪涝灾害下无人机运输与通信协同优化

四问建模、求解和验证程序在 [final_code](final_code/README.md)，算法与审查说明见 [四问文档](final_code/四问流程算法与题目审查.md)。

| 目录 | 内容 |
| --- | --- |
| `data/` | 原始无人机、货箱、通信、节点和 GIS/DEM 数据 |
| `docs/` | 题目及原始结果提交模板 |
| `final_code/` | 按问题一、二、三、四整理的正式代码 |
| `tests/` | 物理、通信、冻结分区、模板和程序包测试 |
| `outputs/q1/`—`outputs/q4/` | 各问正式工作簿、CSV/JSON、模板分类表及图 |
| `outputs/provenance/` | 已选方案的模式库、选址表与来源记录 |
| `outputs/checks/` | 最终独立审计、输入哈希及测试证据 |
| `pic/`、`analysis/` | 保留的辅助脚本，不参与正式求解和结果生成 |

直接查看 [结果目录](outputs/README.md)、[模板结果总表](outputs/结果提交汇总.xlsx) 或 [四问指标汇总](outputs/四问指标汇总.xlsx)。总表保留原模板六张表，并补充第三问独立运输明细，避免与第二问方案混淆。

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m final_code.publish
```

运行环境和重算命令见代码目录说明。原始数据未修改；正式结果均经过连续时间、资源及通信检查。第二、三问未证明原题全局最优。贡献规范见 [AGENTS.md](AGENTS.md) 与 [commit-conventions.md](commit-conventions.md)。
