# 问题三

`run.py` 是单问联合求解入口，先求第二问作为热启动，再从共同模式库重新选择运输架次；热启动不固定第三问的模式和时间。`communication.py` 预计算保守通信需求，`physics.py` 和 `audit.py` 负责链路、中继能量及连续时间独立审计，`transport_relay.py` 提供轨迹与提交表。

运行：` .venv/bin/python -m final_code.problem3.run --output outputs/problem3/final_code --time-limit 120 --max-relays 10 `。输出包含 `problem3_submission.xlsx`、运输及中继时序、通信与资源审计和 `screening.json`。现有已认证方案在 `outputs/unified/final/q3/`。
