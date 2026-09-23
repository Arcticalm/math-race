# 与参考解题包（~/Downloads/D题/代码）的差异比对

> 目的：将参考解题包与本仓库的求解内容做逐问题比对，明确「已覆盖 / 未覆盖」「口径差异」「数值差异」，
> 作为补齐 Q2–Q4 或对齐 Q1 口径的依据。
>
> 比对对象：
> - 参考包：`~/Downloads/D题/代码`（`code/d_model_core.py` + `code/run_all.py` + `results/` + `figures/` + `source/*.tex`）
> - 本仓库：`src/problem1/`（已落地代码）+ `design/`（四问假设与口径文档）

---

## 0. 一句话结论

两边在**问题一**上建模口径几乎一致（结果相差 <0.2%），但参考包是**四问全做完的完整解题包**（Q1–Q4 均有代码 + 结果 + 图 + 论文 LaTeX），
本仓库**只有问题一落地了代码**，问题二/三/四目前仍停留在「假设与口径」文档阶段，尚未实现求解代码。

---

## 1. 覆盖范围对比（最大差异）

| 内容 | 参考包 | 本仓库 |
|---|---|---|
| 问题一（单点组批） | ✅ `d_model_core.py` 精确 DP | ✅ `src/problem1/solver.py` 精确 DP |
| 问题二（多点调度） | ✅ `greedy_merge` + `schedule_routes_flexible` | ⚠️ 仅 [problem2.md](problem2.md)，无代码 |
| 问题三（通信+中继） | ✅ LOS 链路预算 + 中继选址 + `schedule_q3` | ⚠️ 仅 [problem3.md](problem3.md)，无代码 |
| 问题四（任务分区） | ✅ KMeans 加权聚类 + 峰值资源核算 | ⚠️ 仅 [problem4.md](problem4.md)，无代码 |
| 论文文档 | ✅ 3 份 PDF + LaTeX 源码（`source/`） | ✅ `docs/` 数份 md/docx，无 LaTeX |
| 结果表格 | ✅ `results/` 8 个 CSV + `metrics.json` | ✅ `outputs/problem1/`（仅 Q1） |
| 图像 | ✅ `figures/` 6 张 | ✅ `outputs/problem1/` 4 张（仅 Q1） |

**核心差异：参考包是「四问闭环」，本仓库是「一问落地 + 三问设计」。**

---

## 2. 问题一：数值比对（两方都有代码）

两方 Q1 结果几乎重合，差异来自**距离口径**。

| 指标 | 本仓库「架次优先」 | 参考包 | 差异 |
|---|---|---|---|
| 往返架次 | 18 | 18 | 一致 |
| 总能耗 | 59.232 kWh | 59.122 kWh | +0.19% |
| 累计作业时间 | 32777.3 s | 32754.8 s | +0.07% |

### 差异根源

- 本仓库 [solver.py](src/problem1/solver.py#L164) 用**球面大圆距离**（haversine，R=6 371 008.8 m）。
- 参考包 `d_model_core.py` 用 `pyproj.Geod`（WGS84 **椭球**测地线）。

在本仓库所在纬度，椭球测地线比球面大圆略短约 0.3%（例：S001 本仓库 3063.4 m，参考 3054.0 m）。

**能耗模型公式本身两边完全一致**：`E_hor = Euse·d/L(q)` + `E_up = m·g·h/(3.6e6·η)`，
因此这 0.2% 纯粹是测距方式造成，**不是建模分歧**。

---

## 3. 问题一口径差异

### 3.1 本仓库比参考更严谨的地方

- **航程约束单独校验**：本仓库 `max_safe_payload` / `_is_feasible` 同时检查「单程距离 ≤ 载荷等效航程」与「≤ 空载返航航程」；
  参考包 `safe_payload` 只查总能耗 ≤ 返航余量，**不查航程**。
- **多目标**：本仓库对比架次/能耗/时间三种字典序策略 + 非支配判断；参考只做单一字典序 `(架次,能耗,时间)`。
- **敏感性更全**：本仓库在返航余量之外，另加「水平能耗率 ×0.8 / ×1.2」敏感性；参考只做返航余量单因素。
- **输出对齐提交模板**：本仓库直接生成 `problem1_submission.xlsx`；参考只有 CSV。

### 3.2 参考比本仓库更稳妥的地方

- 参考 `safe_payload` 采用与 `route_eval` 一致的**总能耗二分母搜索**；
  本仓库 `max_safe_payload` 额外叠了航程检查，若附件航程数据与能耗口径不匹配，两套约束可能打架（本仓库更保守）。
  这并非 bug，但论文中需说明「航程约束」与「能耗约束」谁主导。

---

## 4. 问题二/三/四：参考已求解，本仓库尚未实现

参考包在这三问上已有可复现的具体方案，对应本仓库 [problem2.md](problem2.md)、[problem3.md](problem3.md)、[problem4.md](problem4.md)
中标注【待补充】的开放选择如下：

### 4.1 Q2（多点调度）

- 方法：把 Q1 单点架次用 `greedy_merge` 贪心合并成 ≤3 服务区的多点架次，再 `schedule_routes_flexible`
  按「硬截止优先、其次期望时间、再优先级」分配到实体无人机 + 共享电池（含两阶段充电）。
- 结果：18 架次、makespan 10620 s、硬截止违约 0、10 箱迟于期望时间。

### 4.2 Q3（通信 + 中继）

- 方法：LOS 用 30m DEM 沿线判定遮挡 + FSPL 链路预算；中继悬停点离散到「服务区节点 / 两两中点 × 离地 100/200/300m」候选集；
  `schedule_q3` 做运输 + 中继联合调度。
- 结果：3 个服务区可直连、12 个需中继。

### 4.3 Q4（任务分区）

- 方法：`lon/lat/工作量` 标准化后 KMeans（工作量权重 ×0.45），K=2/3 两方案，按峰值占用核算 A/B/C 无人机与电池需求。
- 结果：分区表见参考包 `results/q4_partition.csv`。

> 对应本仓库 [problem2.md](problem2.md) §2.6、[problem3.md](problem3.md) §2.6 问的「MILP / 列生成 / 启发式」——
> 参考包实际选了**贪心合并 + 优先级列表启发式**，未做全局最优。

---

## 5. 参考包独有、本仓库缺失的内容

1. Q2 的多点组批与实体资源调度（`greedy_merge` + `schedule_routes_flexible` + `charge_time` 两阶段充电）。
2. Q3 的通信链路预算全链路（`los_clear` / `fspl_db` / `link_ok` / `candidate_relays` / `schedule_q3`）。
3. Q4 的 KMeans 分区 + 峰值资源核算（`peak()` 区间峰值函数）。
4. 6 张图：DEM 节点图、安全载荷热图、Q2 甘特图、直连占比图、敏感性曲线、分区工作量图。
5. 3 份论文文档的 LaTeX 源码（完整解题过程 / 答案分析 / 20 分钟讲解稿）。

---

## 6. 本仓库独有、参考包没有的内容

1. **工程化程度高**：dataclass + 类型标注 + 路径从 `__file__` 解析 + `tests/`；
   参考包把 `ROOT='/mnt/data/d_decoded'` 硬编码死，`run_all.py` 还 `sys.path.insert(0,'/mnt/data')`，换机器不改成该路径跑不起来。
2. **提交模板对齐**：直接生成 `problem1_submission.xlsx`。
3. **能耗模型文献说明**：[docs/无人机能耗模型说明.md](../docs/无人机能耗模型说明.md) 有 Dorling / Zhang 的引用，参考包没有。
4. **假设显式化**：[design/](README.md) 四份文档把【假设】/【题面规则】/【数据口径】分得很清，比参考包 README 里的几句口径说明严谨。

---

## 7. 后续建议

- 若目标为「补上 Q2–Q4 求解」，可将参考包 `d_model_core.py` 里的 `greedy_merge`、`schedule_routes_flexible`、
  `schedule_q3`、KMeans 分区逻辑移植进本仓库 `src/` 的工程化骨架（其数据字段映射、能耗公式与本仓库一致，移植成本低），
  并把路径改成 `ROOT = Path(__file__)…` 写法。
- 若想先对齐 Q1 数值，把 [solver.py](src/problem1/solver.py#L164) 的 haversine 换成 `pyproj.Geod.inv` 即可（公式层面无分歧）。
- 隐患提示：参考包 `debug_report.md` 与 README 均承认「通信采样当前 60 s，正式提交建议缩到 5 s 复核」，
  说明其 Q3 结果只是**快速基线**，不是最终精度——对应 [problem3.md](problem3.md) §2.1 对「连续通信离散化步长」的顾虑，参考包自己也没解决到位。
