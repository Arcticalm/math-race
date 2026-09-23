# -*- coding: utf-8 -*-
"""Quality conflict definition, diagnosis, and domain-adaptive resolution model."""

import math
import numpy as np
from pathlib import Path
from typing import Dict, Tuple, Any, List

from problem1.q1_preprocessing import (
    stream_jsonl_xz,
    extract_scalar_indicators,
    normalize_record
)
from problem1.q1_quality_evaluation import evaluate_sample_score

# Indicator sub-groups for conflict detection
COG_INDICATORS = [
    "fineweb_edu",
    "modernbert_reasoning",
    "modernbert_professionalism",
    "dsir_math",
    "rps_doc_unigram_entropy"
]

SURF_INDICATORS = [
    "fluency_en",
    "ad_en",
    "modernbert_readability",
    "rps_doc_frac_chars_top_2gram",
    "rps_lines_ending_with_terminal_punctution_mark"
]


def compute_conflict_index(norm_dict: Dict[str, float]) -> Tuple[float, float, float]:
    """Compute cognitive value, surface quality, and conflict index CI."""
    s_cog = float(np.mean([norm_dict[k] for k in COG_INDICATORS]))
    s_surf = float(np.mean([norm_dict[k] for k in SURF_INDICATORS]))
    ci = abs(s_cog - s_surf)
    return ci, s_cog, s_surf


def compute_resolved_score(
    q_base: float,
    ci: float,
    tau_domain: float = 0.20,
    decay_lambda: float = 0.5
) -> float:
    """Compute conflict-resolved quality score with domain-adaptive tolerance."""
    excess_conflict = max(0.0, ci - tau_domain)
    # Exponential discount for abnormal conflict
    resolved_q = q_base * math.exp(-decay_lambda * excess_conflict)
    return float(max(0.0, min(1.0, resolved_q)))


def analyze_conflicts_in_dataset(
    filepath: Path,
    bounds: Dict[str, Dict[str, float]],
    weights: Dict[str, float],
    conflict_threshold: float = 0.25,
    default_domain: str = None,
    max_records: int = None
) -> Dict[str, Any]:
    """Analyze conflict rates, distribution, and representative cases."""
    domain_conflicts = {}
    representative_samples = []

    count = 0
    for record in stream_jsonl_xz(filepath):
        domain = record.get("_source_domain") or default_domain or "unknown"
        if domain not in domain_conflicts:
            domain_conflicts[domain] = {
                "total": 0,
                "conflict_count": 0,
                "ci_list": [],
                "q_base_list": [],
                "q_resolved_list": []
            }

        scalars = extract_scalar_indicators(record)
        norm_vals = normalize_record(scalars, bounds)
        q_base = evaluate_sample_score(norm_vals, weights)
        ci, s_cog, s_surf = compute_conflict_index(norm_vals)

        # Baseline domain tolerance ~ 0.20
        q_resolved = compute_resolved_score(q_base, ci, tau_domain=0.20, decay_lambda=0.5)

        dc = domain_conflicts[domain]
        dc["total"] += 1
        is_conflict = ci > conflict_threshold
        if is_conflict:
            dc["conflict_count"] += 1

        if len(dc["ci_list"]) < 20000:
            dc["ci_list"].append(ci)
            dc["q_base_list"].append(q_base)
            dc["q_resolved_list"].append(q_resolved)

        # Collect high conflict cases for reporting
        if is_conflict and len(representative_samples) < 10:
            text_preview = record.get("content", "")[:120].replace("\n", " ")
            representative_samples.append({
                "id": record.get("id", "N/A"),
                "domain": domain,
                "s_cog": round(s_cog, 4),
                "s_surf": round(s_surf, 4),
                "conflict_index": round(ci, 4),
                "q_base": round(q_base, 4),
                "q_resolved": round(q_resolved, 4),
                "text_snippet": text_preview
            })

        count += 1
        if max_records and count >= max_records:
            break

    # Summaries
    summary = {}
    for dom, dc in domain_conflicts.items():
        ci_arr = np.array(dc["ci_list"])
        qb_arr = np.array(dc["q_base_list"])
        qr_arr = np.array(dc["q_resolved_list"])

        summary[dom] = {
            "total_records": dc["total"],
            "conflict_count": dc["conflict_count"],
            "conflict_rate": round(dc["conflict_count"] / max(1, dc["total"]), 4),
            "mean_ci": round(float(np.mean(ci_arr)), 4),
            "std_ci": round(float(np.std(ci_arr)), 4),
            "mean_q_base": round(float(np.mean(qb_arr)), 4),
            "mean_q_resolved": round(float(np.mean(qr_arr)), 4),
            "q_diff_pct": round(float((np.mean(qr_arr) - np.mean(qb_arr)) / max(1e-6, np.mean(qb_arr)) * 100), 2)
        }

    return {
        "domain_summary": summary,
        "representative_samples": representative_samples
    }


def compare_conflict_sample_vs_extended(
    a1_conflict_summary: Dict[str, Any],
    a2_conflict_summary: Dict[str, Any],
    a3_conflict_summary: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Compare conflict statistics between A1 sample and A2/A3 extended sets."""
    comparisons = []

    # 1. Compare arxiv
    s_arxiv = a1_conflict_summary.get("arxiv")
    e_arxiv = a2_conflict_summary.get("arxiv")
    if s_arxiv and e_arxiv:
        diff_rate = round(e_arxiv["conflict_rate"] - s_arxiv["conflict_rate"], 4)
        diff_ci = round(e_arxiv["mean_ci"] - s_arxiv["mean_ci"], 4)
        comparisons.append({
            "domain": "arxiv",
            "sample_n": s_arxiv["total_records"],
            "sample_conflict_rate": s_arxiv["conflict_rate"],
            "sample_mean_ci": s_arxiv["mean_ci"],
            "sample_q_base": s_arxiv["mean_q_base"],
            "sample_q_resolved": s_arxiv["mean_q_resolved"],
            "extended_n": e_arxiv["total_records"],
            "extended_conflict_rate": e_arxiv["conflict_rate"],
            "extended_mean_ci": e_arxiv["mean_ci"],
            "extended_q_base": e_arxiv["mean_q_base"],
            "extended_q_resolved": e_arxiv["mean_q_resolved"],
            "diff_conflict_rate": diff_rate,
            "diff_mean_ci": diff_ci,
            "is_consistent": bool(abs(diff_rate) < 0.05 and abs(diff_ci) < 0.03)
        })

    # 2. Compare github
    s_github = a1_conflict_summary.get("github")
    e_github = a3_conflict_summary.get("github")
    if s_github and e_github:
        diff_rate = round(e_github["conflict_rate"] - s_github["conflict_rate"], 4)
        diff_ci = round(e_github["mean_ci"] - s_github["mean_ci"], 4)
        comparisons.append({
            "domain": "github",
            "sample_n": s_github["total_records"],
            "sample_conflict_rate": s_github["conflict_rate"],
            "sample_mean_ci": s_github["mean_ci"],
            "sample_q_base": s_github["mean_q_base"],
            "sample_q_resolved": s_github["mean_q_resolved"],
            "extended_n": e_github["total_records"],
            "extended_conflict_rate": e_github["conflict_rate"],
            "extended_mean_ci": e_github["mean_ci"],
            "extended_q_base": e_github["mean_q_base"],
            "extended_q_resolved": e_github["mean_q_resolved"],
            "diff_conflict_rate": diff_rate,
            "diff_mean_ci": diff_ci,
            "is_consistent": bool(abs(diff_rate) < 0.05 and abs(diff_ci) < 0.03)
        })

    return comparisons

