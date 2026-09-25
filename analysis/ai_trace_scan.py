#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对 paper/main.tex 做 AI 痕迹量化扫描（12 维度中可机检的部分）。

用法: python3 analysis/ai_trace_scan.py paper/main.tex
输出: JSON 到 stdout
"""
import json
import re
import statistics
import sys
from collections import Counter

TEX = sys.argv[1] if len(sys.argv) > 1 else "paper/main.tex"
raw = open(TEX, encoding="utf-8").read()


def strip_comments(s: str) -> str:
    out = []
    for line in s.split("\n"):
        i = 0
        buf = []
        while i < len(line):
            if line[i] == "%" and (i == 0 or line[i - 1] != "\\"):
                break
            buf.append(line[i])
            i += 1
        out.append("".join(buf))
    return "\n".join(out)


def drop_env(s: str, envs) -> str:
    for e in envs:
        s = re.sub(r"\\begin\{" + re.escape(e) + r"\}.*?\\end\{" +
                   re.escape(e) + r"\}", " ", s, flags=re.S)
    return s


body = strip_comments(raw)
# 去掉导言区
m = re.search(r"\\begin\{document\}", body)
body = body[m.end():] if m else body

# 单独抽出摘要
abs_m = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", body, re.S)
abstract_src = abs_m.group(1) if abs_m else ""

# 抽出全部 caption 文本
captions = re.findall(r"\\caption\{(.+?)\}\s*\n?\s*\\label", body, re.S)
captions = [c for c in captions]

# 抽出章节标题
sections = re.findall(r"\\(section|subsection|subsubsection)\{(.*?)\}", body)

# 正文：剔除数据/代码环境
prose = drop_env(body, [
    "tabular", "tabularx", "array", "longtable", "algorithm", "algorithmic",
    "equation", "align", "gather", "multline", "verbatim", "lstlisting",
    "thebibliography", "figure", "table",
])
# 剔除行内公式与常见命令
prose = re.sub(r"\$[^$]*\$", " ", prose)
prose = re.sub(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?(?=\{)", " ", prose)
prose = re.sub(r"\\[a-zA-Z@]+\*?", " ", prose)
prose = re.sub(r"[{}]", " ", prose)
prose = re.sub(r"\\[,%!]", " ", prose)

CJK = r"\u4e00-\u9fff"


def zh_only(s: str) -> str:
    return "".join(ch for ch in s if re.match("[" + CJK + r"]", ch))


def split_sentences(s: str):
    s = re.sub(r"\s+", " ", s)
    parts = re.split(r"(?<=[。！？；])", s)
    return [p.strip() for p in parts if zh_only(p)]


# ---------- 维度1：词汇层 ----------
AI_WORDS = [
    "值得注意的是", "综上所述", "由此可见", "在此基础上", "进一步分析表明",
    "有效地", "显著地", "极大地", "本文提出", "本文采用", "综合以上分析",
    "结果表明", "需要指出的是", "需要说明的是", "由表", "由图", "可见",
    "深入", "充分", "全面", "彻底", "显著", "极大", "凸显", "彰显",
    "锐减", "骤降", "压倒性", "无可争议", "严丝合缝", "卓越", "顶尖",
    "高度", "深度", "系统性地", "从根本上", "奠定了", "为后续",
    "不仅", "而且", "同时", "此外", "因此", "然而", "综上", "首先",
    "其次", "最后", "一是", "其二", "其一", "换言之", "总体而言",
    "本研究", "该方法", "本问", "本文", "通过", "为了",
]
full_zh = zh_only(prose)
word_counts = Counter()
for w in AI_WORDS:
    word_counts[w] = prose.count(w)

de_density = prose.count("的") / max(1, len(zh_only(prose)))
total_zh_chars = len(zh_only(prose))

# ---------- 维度2：句式层 ----------
sents = split_sentences(prose)
slen = [len(zh_only(s)) for s in sents]
long_ratio = sum(1 for x in slen if x > 40) / max(1, len(slen))
verylong_ratio = sum(1 for x in slen if x > 60) / max(1, len(slen))
transitions = ["首先", "其次", "再次", "然后", "此外", "因此", "然而",
               "同时", "进一步", "在此基础上", "综上", "可见", "需要"]
tcount = sum(prose.count(t) for t in transitions)
sent_head = Counter(s.strip()[:2] for s in sents if len(s.strip()) > 2)
head_benwen = sum(1 for s in sents if s.strip().startswith("本文"))
head_by = sum(1 for s in sents if s.strip().startswith("由") or
              s.strip().startswith("这"))

# ---------- 维度3：段落层 ----------
paras = []
for blk in re.split(r"\n\s*\n", prose):
    blk = blk.strip()
    if not blk:
        continue
    # 段落 = itemize/equation 被删后残留的行块；按行聚合
    for line in blk.split("\n"):
        line = line.strip()
        if len(zh_only(line)) >= 4:
            paras.append(line)
# 真正的“自然段”用源文件的连续非空行块更准
raw_paras = []
for blk in re.split(r"\n\s*\n", strip_comments(raw)[m.end() if m else 0:]):
    lines = [l.strip() for l in blk.split("\n") if l.strip()]
    if not lines:
        continue
    joined = " ".join(lines)
    if re.match(r"\\(begin|end|label|caption|centering|small|scriptsize|toprule)", joined):
        continue
    raw_paras.append(joined)

para_lens = []
for p in raw_paras:
    pp = drop_env(p, ["tabular", "tabularx", "algorithm", "algorithmic",
                      "equation", "align", "figure", "table"])
    pp = re.sub(r"\$[^$]*\$", " ", pp)
    pp = re.sub(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?(?=\{)", " ", pp)
    pp = re.sub(r"\\[a-zA-Z@]+\*?", " ", pp)
    n = len(zh_only(pp))
    if n >= 3:
        para_lens.append((n, pp.strip()[:60]))

plens = [x[0] for x in para_lens]
para_openers = Counter(x[1][:2] for x in para_lens if x[1])
template_open = sum(1 for x in para_lens
                    if x[1].startswith(("首先", "其次", "然后", "此外", "综上",
                                        "在本", "本文", "针对", "由")))

# ---------- 维度5：人味/个人判断 ----------
HUMAN = [
    "我们", "倾向于", "之所以", "而非", "取舍", "权衡", "妥协", "折中",
    "可能不成立", "可能失效", "不排除", "在一定程度上", "也许", "大约",
    "经验值", "本文认为", "本文判断", "建议", "不划算", "没有起作用",
    "未能", "无法", "局限", "不足", "缺陷", "有待", "后续可", "需要向评审",
    "客观声明", "不构成", "不构成", "互不支配", "真正被牺牲的是",
]
human_hits = {h: prose.count(h) for h in HUMAN if prose.count(h) > 0}

# ---------- 维度6：数据表述 ----------
nums = re.findall(r"\d+\.\d{3,}", prose)
num_hist = Counter(len(x.split(".")[1]) for x in nums)
pm = len(re.findall(r"±", prose))

# ---------- 维度9：引用 ----------
cites = re.findall(r"\\cite\{([^}]*)\}", body)
cite_per_sent = len(cites)
bib_n = len(re.findall(r"\\bibitem", body))
english_bib = 0
for b in re.findall(r"\\bibitem\{[^}]*\}\s*(.+)", body):
    if len(zh_only(b)) < 5:
        english_bib += 1

# ---------- 维度10：摘要量化 ----------
abs_zh = zh_only(abstract_src)
abs_numbers = re.findall(r"\d+\.?\d*", re.sub(r"\$[^$]*\$", " ", abstract_src))
abs_nums_strong = re.findall(
    r"\d+\.\d+|\d+(?:\.\d+)?\s*(?:%|kg|kWh|s\b|架次|箱)", abstract_src)

# ---------- 维度11：标配 ----------
has_pseudo = len(re.findall(r"\\begin\{algorithm\}", body))
has_alg = has_pseudo
checks = {
    "伪代码/算法": has_alg,
    "敏感性分析": prose.count("敏感性"),
    "稳健性检验": prose.count("稳健"),
    "误差/审计": prose.count("审计"),
    "基线对比": prose.count("对比表") + prose.count("基线"),
    "公式块数": len(re.findall(r"\\begin\{(equation|align|gather)\}", body)),
    "图数": len(re.findall(r"\\begin\{figure\}", body)),
    "表数": len(re.findall(r"\\begin\{table\}", body)),
    "参考文献数": bib_n,
    "英文文献数": english_bib,
    "假设条数": len(re.findall(r"\\item", body)),
    "热力图": prose.count("热力"),
    "龙卷风图": prose.count("龙卷风"),
    "技术路线图": prose.count("技术路线"),
    "创新点字样": prose.count("创新"),
}

# ---------- 章节篇幅 ----------
sec_stats = []
positions = []
for idx, mm in enumerate(re.finditer(r"\\section\{", body)):
    positions.append(mm.start())
for idx, st in enumerate(positions):
    en = positions[idx + 1] if idx + 1 < len(positions) else len(body)
    chunk = body[st:en]
    sec_stats.append({
        "title": re.sub(r"\\.{0,20}?\{|\}", "",
                        chunk.split("\n")[0])[:40],
        "chars": len(zh_only(chunk)),
    })
tot = sum(s["chars"] for s in sec_stats) or 1
for s in sec_stats:
    s["pct"] = round(100 * s["chars"] / tot, 1)

# ---------- 输出 ----------
out = {
    "chars_zh_total": total_zh_chars,
    "sentences": len(sents),
    "dim1_lexical": {
        "ai_word_counts": dict(sorted(word_counts.items(),
                                      key=lambda kv: -kv[1])),
        "ai_word_total_core": sum(
            word_counts[w] for w in [
                "值得注意的是", "综上所述", "由此可见", "在此基础上",
                "进一步分析表明", "有效地", "显著地", "极大地", "本文提出",
                "本文采用", "综合以上分析", "结果表明"]),
        "de_density": round(de_density * 100, 2),
    },
    "dim2_syntactic": {
        "avg_sent_len": round(statistics.mean(slen), 1),
        "median_sent_len": statistics.median(slen),
        "long_gt40_ratio": round(long_ratio * 100, 1),
        "long_gt60_ratio": round(verylong_ratio * 100, 1),
        "transition_per_100_sent": round(
            100 * tcount / max(1, len(sents)), 1),
        "transition_total": tcount,
        "sent_head_本文_pct": round(
            100 * head_benwen / max(1, len(sents)), 1),
        "top_heads": dict(sent_head.most_common(15)),
    },
    "dim3_paragraph": {
        "n": len(plens),
        "mean": round(statistics.mean(plens), 1),
        "std": round(statistics.pstdev(plens), 1),
        "cv": round(statistics.pstdev(plens) /
                    max(1.0, statistics.mean(plens)), 3),
        "min": min(plens),
        "max": max(plens),
        "template_open_pct": round(
            100 * template_open / max(1, len(plens)), 1),
        "openers": dict(para_openers.most_common(15)),
    },
    "dim5_human_markers": human_hits,
    "dim5_human_total": sum(human_hits.values()),
    "dim6_numbers": {
        "decimals_ge3_count": len(nums),
        "decimal_hist": dict(sorted(num_hist.items())),
        "plus_minus_count": pm,
    },
    "dim9_citations": {
        "cite_commands": cite_per_sent,
        "bib_items": bib_n,
        "english_items": english_bib,
        "inline_narrative_cite": prose.count("文献[") +
            len(re.findall(r"[A-Za-z一-龥]+等\[", prose)),
    },
    "dim10_abstract": {
        "abstract_zh_chars": len(abs_zh),
        "all_numbers": len(abs_numbers),
        "strong_quant": len(abs_nums_strong),
    },
    "dim11_inventory": checks,
    "chapter_balance": sec_stats,
    "captions": captions,
}
print(json.dumps(out, ensure_ascii=False, indent=1))
