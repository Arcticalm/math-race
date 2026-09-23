# 仓库指南

## 项目结构与模块组织

本仓库包含“算力约束下提升大语言模型能力的资源配置建模”项目的数据和文档。主要目录如下：

- `data/A_data_value/`：训练数据混合、领域映射和 SlimPajama 质量信号。
- `data/B_scaling_laws/`：模型缩放律、训练日志、检查点索引和补充实验。
- `data/C_efficiency_evolution/`：排行榜时间序列、模型元数据和逐模型评测结果。
- `docs/`：题目说明（`.pdf`）和结果提交模板（`.docx`）。
- `data/source_manifest.json`：数据来源、文件大小和版本备注。

`src/` 为预留的分析代码目录。新增脚本或笔记本应放在 `src/` 或清晰命名的顶层 `analysis/`、`scripts/` 目录中，不要混入 `data/`。

## 构建、测试与开发命令

目前未定义构建系统、包清单或自动化测试命令。可使用以下命令进行本地检查：

```bash
find data docs -type f                 # inventory inputs and deliverables
git diff --check                       # detect whitespace errors
python3 -m json.tool data/source_manifest.json >/dev/null
```

可直接阅读 `docs/数据说明.pdf` 了解字段、单位和来源。若新增可执行分析，应记录其运行环境和调用方式，并优先提供可复现的 `requirements.txt`、`pyproject.toml` 或锁定文件。

## 代码风格与命名约定

使用 UTF-8，并保留现有中文文件名；不要仅为转写成拼音而重命名源数据。新 Python 脚本使用四个空格缩进、具有描述性的 `snake_case` 名称和小型函数。除非属于正式交付物，否则不要将生成文件放入 `data/`；不要提交缓存、凭据或临时导出文件。

## 测试指南

目前没有既定的测试框架或覆盖率要求。修改数据时，应验证文件可读性、CSV 表头、行数、字段单位和缺失值；对 Parquet/JSONL 等大文件优先做结构检查而非整文件加载。新增代码时，应添加针对性的测试（例如 `tests/test_<module>.py`），并说明测试命令。

## 提交与拉取请求指南

提交信息遵循 `<type>(<scope>): <description>` 格式，描述使用英文祈使语气、小写开头且不加句号。例如：`docs: update result template`。

- 常用类型：`feat` 新功能、`fix` 修复、`docs` 文档、`refactor` 重构、`test` 测试、`build` 构建、`chore` 维护。
- 破坏接口、配置或数据格式时，在类型后加 `!`，例如 `feat(data)!: replace csv format`。
- 每个提交聚焦一项变更；不要提交生成文件、本地配置、缓存或凭据。

拉取请求应简述变更内容，列出受影响路径和验证命令及结果，关联相关 issue 或建模任务；修改 HTML 地图等可视化文件时附上截图。

## 数据处理与可复现性

将现有数据集视为源输入：保留原始值，并将清洗后或派生的数据单独记录。应在分析文档中记录数据来源、字段单位、半合成数据假设、筛选规则和软件版本，使结果能够在不修改原始数据的情况下复现。
