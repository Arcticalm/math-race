# 第二至第四问统一结果

三份工作簿分别记录第二问独立运输方案、第三问运输与中继联合方案、第四问冻结后的分区资源配置。
计算指标、适用范围和资源缺口详见 [完整报告](final/REPORT.md)。

## 提交与审计

- [第二问提交表](problem2_submission.xlsx)
- [第三问提交表](problem3_submission.xlsx)
- [第四问提交表](problem4_submission.xlsx)
- [提交包](unified_results.zip) · [可运行程序](unified_program.zip)
- [文件清单与 SHA-256](deliverables.json)

## 图表

与 `outputs/problem23` 对应的第二问图：

- [运输路线](routes.png) · [资源甘特图](resource_gantt.png) · [逐箱送达](delivery_times.png)
- [完成时间权衡](time_priority_tradeoff.png) · [巡航净空](terrain_clearance.png)

第三、四问扩展图：

- [运输与中继路线](q3_routes_relays.png) · [联合资源甘特图](q3_resource_gantt.png)
- [第三问逐箱送达](q3_delivery_times.png) · [连续通信时序](q3_communication_timeline.png)
- [第三问巡航净空](q3_terrain_clearance.png) · [分区地图](q4_partitions.png)
- [分区资源需求与库存](q4_inventory.png) · [联合方案权衡](q3_tradeoff.png)

图中候选点只代表已认证或已审计的搜索结果；红点是当前选中方案。
第二问和第三问分别来自不同运行，原始方案及审计表保存在 `final/`。
