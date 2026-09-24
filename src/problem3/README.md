# 问题三：按问题二时间轴重建与协调中继任务

默认读取 `outputs/problem23/clearance50/` 中已保存的
`constructive_merged/cp_sat` 方案。入口会核对摘要中的策略、可行性以及
逐架次、逐箱 CSV，并用当前物理模型回放；旧地形模型产生的时间或能耗
与回放不符时直接报错，不会重新求解问题二或悄悄更换组批方案。

在仓库根目录运行：

```bash
uv run --with-requirements src/problem3/requirements.txt python -m src.problem3.solver \
  --q2-output outputs/problem23/clearance50 --output outputs/problem3 \
  --sample-step 10 --relay-candidate-step 10 --max-iterations 12 --time-limit 60

uv run --with-requirements src/problem3/requirements.txt python -m unittest \
  tests.test_problem3 tests.test_problem3_timeline -v
```

`--time-limit` 是每轮后移协调的 CP-SAT 求解秒数；固定时间轴上的中继选择
使用 SciPy MILP，时限为 120 秒。`--sample-step` 和 `--relay-candidate-step`
均以秒为单位。默认检查点间隔不超过 10 秒，同时包含全部阶段边界。
原始数据不作修改，输出目录可自行指定。

## 计算流程

1. 保留问题二的货箱组批、访问顺序、机型、运输机、电池及起始时间。
   逐航段构造爬升、巡航、下降和物资投送（`handoff`）四阶段三维轨迹，
   校验轨迹终点时间与问题二返航时刻一致。
2. 对每个检查点计算运输机至固定网关 G01 的三维距离、地形遮挡及传播损耗。
   任一端点直连失败的采样单元需要中继，按架次合并连续单元，跨阶段也可合并。
3. 根据需求轨迹上的五个代表位置及经纬度偏移网格生成悬停点，并保留历史
   P1/P2/P3 作为额外候选。高度为 DSM 加 50、150、250 米及附件最大允许高度。
   每个候选必须覆盖需求内全部轨迹检查点、阶段边界及额外的中继采样点，
   同时通过运输机—中继机接入链路和中继机—G01 回传链路。
4. 仅将绝对时间重叠且同一悬停点可完整覆盖的需求合并为服务窗口。
   保留每段需求的单独任务选项。服务窗口内按持续悬停和通信计能耗。
5. 由 O01 至悬停点、悬停点至 O01 的爬升、巡航和下降时间反推准备、起飞、
   到点、建链、服务、返航、机体周转和能源组件充电完成时刻。
   中继航段巡航海拔为 `max(沿程DSM最高点+50m, 起点海拔, 终点海拔)`。
6. 用区间覆盖 MILP 选择任务，并分配 2 架中继机和 6 组能源组件。
   若资源冲突，CP-SAT 联合求解运输架次的非负延迟和中继窗口，保持原运输
   资源编号，约束运输机占用、电池充电、硬交付时限、中继能耗及资源容量。
   各运输架次可以分别后移；原本分离但空间兼容的需求可在后移后形成重叠窗口。
   应用延迟后从第 1 步重新计算，直至完整覆盖或达到明确的求解边界。
7. 最终独立回放所有通信检查点，重新计算中继飞行、能耗、SOC、机体周转和
   能源组件充电占用，并执行问题二逐箱、逐段、运输资源和硬时限审计。

## 模型与求解边界

- 经纬度采用 EPSG:4326；高度为米，时间为相对任务起点的秒，能耗为 kWh。
  水平距离使用大圆距离；链路使用工作簿双向预算和 30 米间隔 DSM 视线采样。
- 中继并发接入容量未给定，假设同一悬停点可同时保障多架运输机。
- 延迟协调采用毫秒整数和向外取整的资源区间；每轮单架最多后移 14400 秒，
  且必须保留全部硬交付时限。CP-SAT 以返航储备 SOC 对充电时长作保守上界，
  最终任务按实际能耗、SOC 和分段充电曲线重新计算。
- 后移协调阶段用共享重叠时刻构造合并窗口；重新生成候选时允许连续相交的
  需求链。该协调模型采用更受限的充分条件，不证明所有可合并窗口的最优性。
- 悬停点是有限网格，按覆盖集合保留能耗、出发和返航有利的代表点。
  求解失败只说明当前候选和时移边界内没有得到可行解，不代表原题无解。
- `feasible=true` 要求通信检查点、运输、硬时限、中继物理和资源审计全部通过。
  `checkpoint_coverage_verified` 表示检查点覆盖通过；`continuity_certified=false`
  明确表示没有对采样点之间的全部连续时刻作认证。旧递归连续审计函数保留为
  可选分析工具。第四问现有入口要求连续认证，不能直接把本结果当作该认证。
- 达到迭代上限、无空间候选或时限内无可行排程时保存诊断，不伪造可行结果。

## 输出

- `screening.json`：输入来源、求解状态、延迟量、各项审计和指标。
- `trajectory_phases.csv`、`link_samples.csv`：四阶段轨迹和所有直连检查点。
- `direct_link_intervals.csv`、`gap_id_map.csv`：直连状态单元和合并后的中继需求。
- `relay_candidates.csv`、`relay_schedule.csv`：候选服务窗及已分配任务。
- `two_hop_link_audit.csv`：各检查点接入/回传两段损耗、预算及通过情况。
- `communication_audit.csv`、`relay_uncovered_gaps.csv`：检查点口径的保障区间及失败诊断。
- `transport_inherited_audit.csv`、`relay_resource_audit.csv`：调整后的运输时间轴、
  中继机体占用和能源组件充电时间轴。
- `iteration_history.csv`：每轮覆盖状态、冲突后移求解和停止原因。
- `problem3_submission.xlsx`、`routes_relays.png`、`problem3_program.zip`：提交表、图和程序包。

`timeline.py` 负责输入回放和时间轴协调；`solver.py` 负责轨迹、候选、固定时间轴
排程及导出；`physics.py` 负责物理计算；`audit.py` 负责独立审计。
程序包仍需要源 Excel、DEM 和所选问题二输出，保持仓库相对路径即可复现。

## 本次验证

使用默认 10 秒检查步长及 60 秒 CP-SAT 时限，结果保存在
`outputs/problem3/refactored/`（生成文件已忽略）：两轮计算后 `feasible=true`，
保留 25 个运输架次、80 箱货，后移其中 10 个架次；20 段需求由 10 个中继任务
覆盖。4012 个轨迹检查点、1698 次双跳链路检查、46 项硬时限全部通过，
运输和中继资源审计均无冲突。联合完成时间为 13182.538 秒，中继能耗为
5.112107 kWh，联合能耗为 79.739785 kWh。结果按检查点口径成立。

已通过 27 项回归测试：

```bash
.venv/bin/python -m unittest tests.test_problem3 tests.test_problem3_timeline \
  tests.test_problem23 tests.test_terrain_clearance -q
```

`screening.json` 记录实际 Python、NumPy、SciPy、Rasterio、OR-Tools 和
openpyxl 版本。有限求解时限可能影响得到的候选及延迟量。
