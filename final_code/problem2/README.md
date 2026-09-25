# 问题二

`run.py` 是独立入口；`patterns.py` 建立第二、三问共用的路线、货箱、机型模式库，`master.py` 联合选择模式与整数秒开始时刻。`transport.py` 提供运输物理、资源回代、提交表与图；`groups.py` 生成初始组批；`terrain_audit.py` 独立检查巡航净空。

运行：` .venv/bin/python -m final_code.problem2.run --output outputs/problem2/final_code --time-limit 120 `。输出包含 `problem2_submission.xlsx`、逐箱与资源审计、路线图和 `validation.json`。现有最终方案在 `outputs/unified/final/q2/`。
