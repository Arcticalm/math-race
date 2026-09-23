# 算力约束下提升大语言模型能力的资源配置建模

本仓库用于存放“算力约束下提升大语言模型能力的资源配置建模”竞赛题目的数据、说明材料和结果模板。数据按题目 A、B、C 组织，覆盖训练数据配比、模型缩放律和模型效率演化。

## 目录说明

- `data/A_data_value/`：RegMix 训练/测试混合数据、领域映射与 SlimPajama 质量信号。
- `data/B_scaling_laws/`：Pythia、Cerebras-GPT 等模型的训练轨迹、缩放律基线及补充实验数据。
- `data/C_efficiency_evolution/`：开放模型排行榜时间序列、模型元数据、原始 Parquet 和逐模型详细评测结果。
- `docs/`：题目说明 PDF 和结果提交模板 DOCX。
- `data/source_manifest.json`：数据文件、来源、大小和版本备注的清单。

## 数据格式

仓库提供 `.csv`、`.jsonl.xz`、`.parquet`、`.json`、`.pdf` 和 `.docx` 文件。使用前请阅读 `docs/数据说明.pdf`，并保留字段单位、数据来源和原始数据结构。

## 快速查看

可先查看以下文件了解数据来源和各题数据范围：

```text
docs/数据说明.pdf
data/source_manifest.json
```

贡献和提交规范请参阅 [AGENTS.md](AGENTS.md) 与 [commit-conventions.md](commit-conventions.md)。
