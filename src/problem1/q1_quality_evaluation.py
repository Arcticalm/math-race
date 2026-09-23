# -*- coding: utf-8 -*-
"""Comprehensive data quality evaluation using combination weighting (CRITIC + CV) and TOPSIS."""

import math
import numpy as np
import scipy.stats as stats
from pathlib import Path
from typing import Dict, List, Any

from problem1.config import ALL_INDICATORS
from problem1.q1_preprocessing import (
    stream_jsonl_xz,
    extract_scalar_indicators,
    normalize_record
)


def compute_critic_weights(norm_matrix: np.ndarray) -> np.ndarray:
    """Compute CRITIC weights based on contrast intensity and conflict."""
    # norm_matrix shape: (N, 22)
    std_devs = np.std(norm_matrix, axis=0)  # contrast intensity
    std_devs = np.where(std_devs < 1e-8, 1e-8, std_devs)

    corr_matrix = np.corrcoef(norm_matrix, rowvar=False)
    # Handle NaN in correlation if any column is constant
    corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)

    # Conflict measure: sum of (1 - r_ij)
    conflict = np.sum(1.0 - corr_matrix, axis=0)
    conflict = np.maximum(1e-8, conflict)

    # Information content C_j
    c_scores = std_devs * conflict
    s = np.sum(c_scores)
    if s <= 0 or not np.isfinite(s):
        return np.ones(norm_matrix.shape[1]) / norm_matrix.shape[1]
    return c_scores / s


def compute_cv_weights(norm_matrix: np.ndarray) -> np.ndarray:
    """Compute Coefficient of Variation (CV) weights."""
    means = np.mean(norm_matrix, axis=0)
    means = np.where(means < 1e-6, 1e-6, means)
    stds = np.std(norm_matrix, axis=0)
    stds = np.where(stds < 1e-8, 1e-8, stds)
    cv = stds / means
    s = np.sum(cv)
    if s <= 0 or not np.isfinite(s):
        return np.ones(norm_matrix.shape[1]) / norm_matrix.shape[1]
    return cv / s


def compute_combined_weights(norm_matrix: np.ndarray) -> Dict[str, float]:
    """Compute combined objective weights (CRITIC + CV)."""
    w_critic = compute_critic_weights(norm_matrix)
    w_cv = compute_cv_weights(norm_matrix)

    # 50% CRITIC + 50% CV
    w_combined = 0.5 * w_critic + 0.5 * w_cv
    w_combined = w_combined / np.sum(w_combined)

    return {name: float(w_combined[i]) for i, name in enumerate(ALL_INDICATORS)}


def evaluate_sample_score(norm_dict: Dict[str, float], weights: Dict[str, float]) -> float:
    """Calculate composite quality score q in [0, 1] for a single sample."""
    score = sum(weights[k] * norm_dict[k] for k in ALL_INDICATORS)
    return float(max(0.0, min(1.0, score)))


def run_quality_evaluation_on_dataset(
    filepath: Path,
    bounds: Dict[str, Dict[str, float]],
    weights: Dict[str, float],
    default_domain: str = None,
    max_records: int = None
) -> Dict[str, Any]:
    """Stream dataset and compute domain aggregated quality scores."""
    domain_stats = {}

    count = 0
    for record in stream_jsonl_xz(filepath):
        domain = record.get("_source_domain") or default_domain or "unknown"
        if domain not in domain_stats:
            domain_stats[domain] = {
                "count": 0,
                "token_sum": 0.0,
                "weighted_q_sum": 0.0,
                "scores": []  # keep reservoir or sample of scores for distribution
            }

        scalars = extract_scalar_indicators(record)
        norm_vals = normalize_record(scalars, bounds)
        q = evaluate_sample_score(norm_vals, weights)

        # Word count as token length weight
        word_count = max(1.0, float(scalars.get("rps_doc_word_count", 1.0)))

        ds = domain_stats[domain]
        ds["count"] += 1
        ds["token_sum"] += word_count
        ds["weighted_q_sum"] += word_count * q

        # Keep sample scores for statistical testing (up to 20,000 per domain)
        if len(ds["scores"]) < 20000:
            ds["scores"].append(q)

        count += 1
        if max_records and count >= max_records:
            break

    # Summarize results
    results = {}
    for dom, ds in domain_stats.items():
        mean_weighted_q = ds["weighted_q_sum"] / max(1.0, ds["token_sum"])
        scores_arr = np.array(ds["scores"], dtype=np.float64)
        raw_mean = float(np.mean(scores_arr))
        raw_std = float(np.std(scores_arr))
        sem = raw_std / math.sqrt(len(scores_arr)) if len(scores_arr) > 0 else 0.0

        results[dom] = {
            "record_count": ds["count"],
            "token_count": float(ds["token_sum"]),
            "domain_q": float(mean_weighted_q),
            "raw_mean": raw_mean,
            "raw_std": raw_std,
            "sem": float(sem),
            "ci_95": [float(raw_mean - 1.96 * sem), float(raw_mean + 1.96 * sem)],
            "scores_sample": scores_arr
        }

    return results


def compare_sample_vs_extended(
    a1_results: Dict[str, Any],
    a2_results: Dict[str, Any],
    a3_results: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Compare sampling set A1 with extended sets A2 (arxiv) and A3 (github)."""
    comparison = []

    # 1. Compare arxiv
    if "arxiv" in a1_results and "arxiv" in a2_results:
        s_sample = a1_results["arxiv"]["scores_sample"]
        s_ext = a2_results["arxiv"]["scores_sample"]
        t_stat, p_val = stats.ttest_ind(s_sample, s_ext, equal_var=False)

        comparison.append({
            "domain": "arxiv",
            "sample_n": a1_results["arxiv"]["record_count"],
            "sample_q": round(a1_results["arxiv"]["domain_q"], 4),
            "sample_std": round(a1_results["arxiv"]["raw_std"], 4),
            "extended_n": a2_results["arxiv"]["record_count"],
            "extended_q": round(a2_results["arxiv"]["domain_q"], 4),
            "extended_std": round(a2_results["arxiv"]["raw_std"], 4),
            "diff": round(a2_results["arxiv"]["domain_q"] - a1_results["arxiv"]["domain_q"], 4),
            "t_statistic": round(float(t_stat), 3),
            "p_value": float(p_val),
            "is_consistent": bool(p_val > 0.01 or abs(a2_results["arxiv"]["domain_q"] - a1_results["arxiv"]["domain_q"]) < 0.03)
        })

    # 2. Compare github
    if "github" in a1_results and "github" in a3_results:
        s_sample = a1_results["github"]["scores_sample"]
        s_ext = a3_results["github"]["scores_sample"]
        t_stat, p_val = stats.ttest_ind(s_sample, s_ext, equal_var=False)

        comparison.append({
            "domain": "github",
            "sample_n": a1_results["github"]["record_count"],
            "sample_q": round(a1_results["github"]["domain_q"], 4),
            "sample_std": round(a1_results["github"]["raw_std"], 4),
            "extended_n": a3_results["github"]["record_count"],
            "extended_q": round(a3_results["github"]["domain_q"], 4),
            "extended_std": round(a3_results["github"]["raw_std"], 4),
            "diff": round(a3_results["github"]["domain_q"] - a1_results["github"]["domain_q"], 4),
            "t_statistic": round(float(t_stat), 3),
            "p_value": float(p_val),
            "is_consistent": bool(p_val > 0.01 or abs(a3_results["github"]["domain_q"] - a1_results["github"]["domain_q"]) < 0.03)
        })

    return comparison
