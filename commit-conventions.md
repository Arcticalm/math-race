# Git Commit 提交规范

本项目建议使用类似 Conventional Commits 的格式书写提交信息，使提交历史清晰、便于检索，也方便后续生成变更日志。

## 基本格式

```text
<type>(<scope>): <description>
```

例如：

```text
feat(amp): add motion discriminator configuration
fix(mimic): correct root quaternion conversion
docs: update training instructions
```

各部分说明：

- `type`：提交类型，说明本次提交的主要目的。
- `scope`：影响范围，可选，例如 `amp`、`mimic`、`g1`、`frog_rl`。
- `description`：简短描述本次修改，建议使用英文、祈使语气，并以小写字母开头。

## 常用提交类型

| 类型 | 用途 | 示例 |
| --- | --- | --- |
| `feat` | 新增功能或能力 | `feat(amp): add recovery motion support` |
| `fix` | 修复 Bug 或错误行为 | `fix(train): preserve checkpoint path when resuming` |
| `docs` | 只修改文档 | `docs: add motion data conversion guide` |
| `refactor` | 重构代码，不改变外部行为 | `refactor(runners): extract checkpoint loading` |
| `perf` | 性能优化 | `perf(storage): reduce motion data copies` |
| `test` | 新增或修改测试 | `test(utils): add config validation tests` |
| `build` | 修改构建、安装或依赖配置 | `build: update package requirements` |
| `ci` | 修改 CI/CD 配置或流程 | `ci: run syntax checks on pull requests` |
| `style` | 不影响代码逻辑的格式调整 | `style: format training scripts` |
| `chore` | 其他维护性修改 | `chore: update gitignore rules` |
| `revert` | 回滚之前的提交 | `revert: revert feat(amp) motion support` |

## 如何选择类型

- 增加用户或训练流程可使用的新能力，使用 `feat`。
- 修复当前行为中的错误，使用 `fix`。
- 仅调整代码结构且功能和接口不变，使用 `refactor`。
- 仅提升运行效率或降低资源消耗，使用 `perf`。
- 仅修改 Markdown、注释或说明文字，使用 `docs`。
- 修改测试本身，使用 `test`；修改测试框架、构建脚本或依赖配置时，分别使用 `ci` 或 `build`。
- 无法归入上述类别的日常维护，使用 `chore`。

## 破坏性变更

如果提交会破坏现有接口、配置格式、命令行参数或数据格式，在类型后添加 `!`：

```text
feat(config)!: replace csv motion config format
```

也可以在提交信息正文中明确说明：

```text
feat(config): rename motion_data fields

BREAKING CHANGE: csv_paths is now required and must contain one path.
```

## 多行提交信息

当修改较复杂时，可以补充正文和脚注：

```text
fix(mimic): handle the final interpolated frame

The previous implementation skipped the last input frame when the output
frequency was lower than the input frequency.

Refs: #123
```

标题建议保持简短，正文说明修改原因和影响，不要只重复代码改了什么。

## 推荐写法

- 使用明确、具体的动词，例如 `add`、`fix`、`remove`、`update`、`refactor`。
- 一次提交尽量只做一类事情，避免把功能修改、格式化和无关清理混在一起。
- 描述实际结果，不写空泛的 `update code` 或 `fix bug`。
- 不要在提交标题末尾添加句号。
- 提交前检查 `git diff`，确认没有提交临时文件、模型输出或本地配置。

## 示例对照

```text
# 推荐
feat(g1): add 23-dof robot configuration
fix(mimic): validate csv joint names before replay
docs: document NPZ motion fields

# 不推荐
update code
fix bug
Feat: New Feature.
```
