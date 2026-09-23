# 仓库指南

## 项目结构与模块组织

本仓库包含无人机应急物资运输与通信数学建模项目的数据和文档。主要目录如下：

- `data/无人机应急物资运输基础数据/`：描述无人机、通信链路、物资需求、服务区和调度输入的 Excel 工作簿。
- `data/镇龙乡地理空间数据/`：GIS 源数据，包括 CSV/MAT 图层、GeoTIFF 格式 DEM、地图 HTML 文件及其说明 PDF。
- `docs/`：建模题目说明（`.docx`）和结果提交模板（`.xlsx`）。

目前没有应用源代码目录或测试目录。新增分析、脚本或笔记本时，应放在清晰命名的顶层目录（例如 `analysis/` 或 `scripts/`）中，不要混入 `data/`。

## 构建、测试与开发命令

目前未定义构建系统、包清单或自动化测试命令。可使用以下命令进行本地检查：

```bash
find data docs -type f                 # inventory inputs and deliverables
git diff --check                       # detect whitespace errors
python -m zipfile -t path/to/file.xlsx # validate an Excel container
```

可在浏览器中打开 `data/镇龙乡地理空间数据/镇龙乡地理空间详情地图.html` 查看地图。若新增可执行分析，应记录其运行环境和调用方式，并优先提供可复现的 `requirements.txt`、`pyproject.toml` 或锁定文件。

## 代码风格与命名约定

使用 UTF-8，并保留现有中文文件名；不要仅为转写成拼音而重命名源数据。新脚本使用四个空格缩进、具有描述性的 `snake_case` 名称和小型函数。除非属于正式交付物，否则不要将生成文件放入 `data/`；不要提交缓存、凭据或临时导出文件。

## 测试指南

目前没有既定的测试框架或覆盖率要求。修改数据时，应验证文件可读性、工作表或图层名称、行数、坐标单位和缺失值。新增代码时，应添加针对性的测试（例如 `tests/test_<module>.py`），并说明测试命令。

## 提交与拉取请求指南

提交信息遵循 `<type>(<scope>): <description>` 格式，描述使用英文祈使语气、小写开头且不加句号。例如：`docs: update result template`。

- 常用类型：`feat` 新功能、`fix` 修复、`docs` 文档、`refactor` 重构、`test` 测试、`build` 构建、`chore` 维护。
- 破坏接口、配置或数据格式时，在类型后加 `!`，例如 `feat(data)!: replace csv format`。
- 每个提交聚焦一项变更；不要提交生成文件、本地配置、缓存或凭据。

拉取请求应简述变更内容，列出受影响路径和验证命令及结果，关联相关 issue 或建模任务；修改 HTML 地图等可视化文件时附上截图。

## 数据处理与可复现性

将现有数据集视为源输入：保留原始值，并将清洗后或派生的数据单独记录。应在分析文档中记录坐标参考系、单位、假设和软件版本，使结果能够在不修改原始数据的情况下复现。
