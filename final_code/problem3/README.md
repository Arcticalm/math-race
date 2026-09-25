# 问题三

`run.py` 是单问联合求解入口，先求第二问作为热启动，再从共同模式库重新选择运输架次；热启动不固定第三问的模式和时间。`communication.py` 预计算保守通信需求，`physics.py` 和 `audit.py` 负责链路、中继能量及连续时间独立审计，`transport_relay.py` 提供轨迹与提交表。

运行：` .venv/bin/python -m final_code.problem3.run --output outputs/problem3/final_code --time-limit 120 --max-relays 10 `。输出包含 `problem3_submission.xlsx`、运输及中继时序、通信与资源审计和 `screening.json`。现有已认证方案在 `outputs/unified/final/q3/`。

## 求解范围：独立第三问与四问联动

`--partition-groups` 决定第三问是否预留第四问分区：

- `0`（默认，**独立第三问**）：完全按题目第三问求解，不加任何分区约束。交付结果取此范围。
- `2` 或 `3`（**四问联动**）：追加“冻结后的排程必须能划分为 2 或 3 个任务组”的额外约束，
  并在字典序末级加入分区缺口偏好。这会缩小第三问的可行域，因此联动解可能不如独立解。

两个范围的结果不能互相比较；`run_all.py --q3-partition-groups` 与 `compare_runs` 使用同一开关，
并按各运行 manifest 记录的取值重算联合得分。

连续通信不按时间间隔采样判定：`audit.py` 对完整扫掠 LOS 区间和全部被触及的 DEM 像元递归细分，
只有拿到区间证书的时刻区间才判为连续可行，未证明的候选被排除而非默认可行。旧采样认证
（缺少 `audit_version = exact_dem_interval_v2`）会被第四问入口拒绝并要求重新审计。
