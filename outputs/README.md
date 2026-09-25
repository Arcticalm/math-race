# 四问最终结果

按照 docs/结果提交模板.xlsx 分类；原始精度保留在各问 CSV/JSON，展示表按求解器原有精度导出。

- [结果提交汇总](结果提交汇总.xlsx)：原模板 6 张表，加 Q3_运输架次、Q3_逐箱交付两张补充表。
- [四问指标汇总](四问指标汇总.xlsx)：26 张指标、资源和审计明细表。
- [流程与算法](../final_code/四问流程算法与题目审查.md) · [审查报告](REPORT.md)

| 问题 | 按模板填写的工作簿 | 明细与图表 |
| --- | --- | --- |
| 一 | [单点组批](q1/problem1_submission.xlsx) | q1/tables；q1/figures |
| 二 | [运输架次及逐箱交付](q2/problem2_submission.xlsx) | q2/tables；q2/figures |
| 三 | [联合运输、中继及通信保障](q3/problem3_submission.xlsx) | q3/tables；q3/figures |
| 四 | [分区配置](q4/problem4_submission.xlsx) | q4/tables；q4/figures |

第三问单独工作簿沿用模板中的 Q2_运输架次、Q2_逐箱交付字段承载第三问重选后的运输方案；
它们与独立第二问不同。总表中用新增 Q3_运输架次、Q3_逐箱交付区分，绝不相互覆盖。

`provenance/` 保存选中方案的模式、选址和运行来源，`checks/` 保存最终复核和测试证据。
[程序包](程序.zip) 包含四问源码、测试、说明和原模板；[文件清单](deliverables.json) 给出 SHA-256。

重新整理：`.venv/bin/python -m final_code.publish`。此命令不重新优化或改动冻结排程。
