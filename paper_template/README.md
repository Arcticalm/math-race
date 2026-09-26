# “华为杯”第二十三届中国研究生数学建模竞赛论文模板（前两页 LaTeX 版）

本目录根据 **《附件3：“华为杯”第二十三届中国研究生数学建模竞赛论文模板.doc》** 的前两页规范，采用 LaTeX (XeLaTeX + ctex) 进行像素级精准复刻，确保符合研赛组委会格式要求。

---

## 一、文件结构

```text
paper_template/
├── README.md               # 模板使用与配置说明文档（本文件）
├── template.tex            # 独立可编译的完整文档（生成前两页）
├── template.pdf            # 编译生成的高清双页 PDF 样稿
├── cover_pages.tex         # 模块化片段（可直接通过 \input 引入主论文）
└── figures/                # 提取自原 Word 模板的原生高清徽标
    ├── logo_cpipc.png      # 中国研究生创新实践系列大赛 Logo
    ├── logo_contest.png    # 中国研究生数学建模竞赛会徽
    ├── logo_huawei.jpg     # 华为 Logo
    └── logo_xjtu.png       # 西安交通大学校徽（已精准裁剪为独立圆形校徽）
```

---

## 二、页面排版规范说明

| 页面 | 标题 / 模块 | 格式要求与实现细节 |
| :--- | :--- | :--- |
| **第一页**<br>(页码标为 **0**) | 顶部四徽标 | 创新大赛、数模会徽、华为、西安交大校徽并排居中对齐，高度按原文档精准校准为 1.8~2.1 cm |
| | 大赛及竞赛标题 | 居中三行：<br>1. “中国研究生创新实践系列大赛”（小二，加粗）<br>2. ““华为杯”第二十三届中国研究生”（二号，加粗）<br>3. “数学建模竞赛”（二号，加粗） |
| | 队伍信息三线表 | 宽度 14.7 cm，行距舒展，含“学校”、“参赛队号”、“队员姓名”（跨三行，编号 1、2、3）；外框及主分隔线为 1.5pt，队员子分隔线为 1.0pt |
| | 页脚页码 | 页面底部正中显示单数字 `0` |
| **第二页**<br>(页码标为 **1**) | 顶部大赛与竞赛标题 | 格式与第一页保持一致（小二/二号加粗居中） |
| | 题目栏 | “题  目：”（小二隶书/楷体），后接下划线或下划线包裹的题目文字（三号宋体加粗居中） |
| | 摘要标题 | “摘  要：”（小二隶书/楷体，居中） |
| | 摘要正文 | 小四号宋体，1.3 倍行距，首行缩进 |
| | 关键词栏 | “关键词：”（小二隶书/楷体，左顶格），后接小四宋体关键词（以 `\quad` 分隔） |
| | 页脚页码 | 页面底部正中显示单数字 `1` |

---

## 三、快速使用方法

### 1. 独立编译前两页样稿

在当前目录直接使用 `xelatex` 编译即可：

```bash
cd paper_template
xelatex template.tex
```

编译完成后即可在当前目录下获得 `template.pdf`。

### 2. 参数宏自定义

在 `template.tex` 或主文档导言区，通过修改/定义以下宏变量，即可快速填充参赛信息：

```latex
\newcommand{\SchoolName}{南京理工大学}                                 % 学校名称
\newcommand{\TeamNumber}{102880001}                                     % 参赛队号
\newcommand{\MemberA}{张三}                                             % 队员1姓名
\newcommand{\MemberB}{李四}                                             % 队员2姓名
\newcommand{\MemberC}{王五}                                             % 队员3姓名
\newcommand{\PaperTitle}{山区洪涝灾害下无人机应急物资运输与通信协同优化建模研究} % 论文题目
\newcommand{\PaperKeywords}{应急物资运输\quad 联合调度\quad 非线性能耗\quad 整数规划} % 关键词
\newcommand{\AbstractContent}{%
此处粘贴您的论文摘要正文……
}
```

---

## 四、嵌入到已有论文主干（例如 `paper/main.tex`）

若您已有完整的数学建模论文（如本仓库的 `paper/` 目录），无需复制整套代码，只需两步即可将本模板的前两页无缝接入：

### 步骤 1：主文档导言区声明必要宏包与图片路径

确保您的 `main.tex` 导言区已包含以下宏包：

```latex
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{multirow}
\usepackage{array}
\usepackage[normalem]{ulem}
```

### 步骤 2：在 `\begin{document}` 之后引入前两页

```latex
\begin{document}

% 指定前两页徽标路径并载入模板
\newcommand{\CoverFiguresPath}{../paper_template/figures/}
\input{../paper_template/cover_pages.tex}

% -------------------------------------------------------------
% 此处开始论文正文（第一章 / 一、问题重述...）
% -------------------------------------------------------------
\section{一、问题重述与背景分析}
...
```

---

## 五、字体兼容性与高级配置

- **通用跨平台兼容（默认）**：
  模板默认采用 `ctex` 基础字库（`\heiti`、`\songti`、`\kaishu`），在 Linux、macOS、Windows 及 Overleaf 上均可**开箱即用，零依赖、零编译报错**。
- **还原 Word 原版字体（Windows / 已安装华文与隶书字体的系统）**：
  若希望 100% 还原 Word 模板的“华文新魏”大标题与“隶书”摘要/题目提示字，只需解开 `template.tex`（或在主文档中）中的字体定义注释：
  ```latex
  \setCJKfamilyfont{hwxinwei}{STXinwei}
  \renewcommand{\hwxinwei}{\CJKfamily{hwxinwei}}
  \setCJKfamilyfont{hwlishu}{SimLi}
  \renewcommand{\hwlishu}{\CJKfamily{hwlishu}}
  ```
