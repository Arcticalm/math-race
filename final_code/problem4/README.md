# 问题四

`solver.py` 只读取已认证的第三问排程，冻结运输、中继与资源时序后，枚举 K=2 和 K=3 的分区及资源配置。入口不重排第三问架次。

运行：` .venv/bin/python -m final_code.problem4.solver --input outputs/unified/final/q3 --output outputs/problem4/final_code `。输出包含 `problem4_submission.xlsx`、分区配置、库存比较及冻结输入审计。现有最终方案在 `outputs/unified/final/q4/`。
