# -*- coding: utf-8 -*-
"""End-to-end execution pipeline for Problem 1."""

import json
import sys
import time
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from problem1.config import (
    ALL_INDICATORS,
    QUALITY_DOMAINS,
    PATH_A1_SAMPLE,
    PATH_A2_ARXIV,
    PATH_A3_GITHUB,
    RESULTS_DIR
)
from problem1.q1_preprocessing import (
    stream_jsonl_xz,
    extract_scalar_indicators,
    compute_normalization_bounds,
    save_normalization_bounds,
    normalize_record
)
from problem1.q1_quality_evaluation import (
    compute_combined_weights,
    run_quality_evaluation_on_dataset,
    compare_sample_vs_extended
)
from problem1.q1_conflict_resolution import (
    analyze_conflicts_in_dataset
)
from problem1.q1_domain_mapping import (
    build_17_domain_quality_vector,
    save_17_domain_quality
)
from problem1.q1_mixture_modeling import (
    run_full_mixture_pipeline
)


def main():
    start_time = time.time()
    print("=" * 70)
    print(">>> [Problem 1] Starting End-to-End Modeling Pipeline")
    print("=" * 70)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------
    # Step 1: Normalization Bounds Calibration
    # -------------------------------------------------------------
    print("\n[Step 1/5] Calibrating Normalization Bounds on A1 Sample Set...")
    bounds_path = RESULTS_DIR / "normalization_bounds.json"
    bounds = compute_normalization_bounds(PATH_A1_SAMPLE, p_low=0.5, p_high=99.5)
    save_normalization_bounds(bounds, bounds_path)
    print(f"  ✓ Calibrated 22 indicators bounds. Saved to {bounds_path.name}")

    # -------------------------------------------------------------
    # Step 2: Combination Weighting & Quality Evaluation
    # -------------------------------------------------------------
    print("\n[Step 2/5] Computing Objective Weights (CRITIC + CV) on A1...")
    # Collect calibration matrix from A1
    calib_list = []
    for rec in stream_jsonl_xz(PATH_A1_SAMPLE):
        sc = extract_scalar_indicators(rec)
        norm_v = normalize_record(sc, bounds)
        calib_list.append([norm_v[k] for k in ALL_INDICATORS])
        if len(calib_list) >= 15000:
            break
    import numpy as np
    calib_mat = np.array(calib_list, dtype=np.float64)
    weights = compute_combined_weights(calib_mat)

    weights_path = RESULTS_DIR / "indicator_weights.json"
    with open(weights_path, "w", encoding="utf-8") as f:
        json.dump(weights, f, indent=2, ensure_ascii=False)
    print("  ✓ Top 5 Indicator Weights:")
    sorted_w = sorted(weights.items(), key=lambda x: x[1], reverse=True)
    for k, w in sorted_w[:5]:
        print(f"    - {k:40s}: {w*100:.2f}%")

    print("\n  Evaluating 7 Domains on A1 Sample Set (51,230 records)...")
    a1_results = run_quality_evaluation_on_dataset(PATH_A1_SAMPLE, bounds, weights)

    print("  Evaluating Full Extended Set A2 (arxiv: 17,523 records)...")
    a2_results = run_quality_evaluation_on_dataset(
        PATH_A2_ARXIV, bounds, weights, default_domain="arxiv"
    )

    print("  Evaluating Full Extended Set A3 (github: 203,752 records)...")
    a3_results = run_quality_evaluation_on_dataset(
        PATH_A3_GITHUB, bounds, weights, default_domain="github"
    )

    # Statistical Comparison
    comparison = compare_sample_vs_extended(a1_results, a2_results, a3_results)
    comp_path = RESULTS_DIR / "sample_vs_extended_comparison.json"
    with open(comp_path, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2, ensure_ascii=False)

    print("\n  ✓ Quality Comparison Table (Sample A1 vs Extended A2/A3):")
    print(f"    {'Domain':<12} {'Sample N':<10} {'Sample Q':<10} {'Extended N':<12} {'Extended Q':<12} {'Diff':<8} {'p-value':<10}")
    print("    " + "-" * 75)
    for c in comparison:
        print(f"    {c['domain']:<12} {c['sample_n']:<10} {c['sample_q']:<10} {c['extended_n']:<12} {c['extended_q']:<12} {c['diff']:<8} {c['p_value']:<10.4f}")

    # Export domain quality table (incorporating full extended data for arxiv and github)
    final_domain_q_7 = {}
    for dom in QUALITY_DOMAINS:
        if dom == "arxiv" and "arxiv" in a2_results:
            final_domain_q_7[dom] = a2_results["arxiv"]["domain_q"]
        elif dom == "github" and "github" in a3_results:
            final_domain_q_7[dom] = a3_results["github"]["domain_q"]
        else:
            final_domain_q_7[dom] = a1_results[dom]["domain_q"]

    # -------------------------------------------------------------
    # Step 3: Quality Conflict Analysis & Adaptive Resolution
    # -------------------------------------------------------------
    print("\n[Step 3/5] Performing Conflict Analysis & Adaptive Resolution...")
    conflict_res_a1 = analyze_conflicts_in_dataset(PATH_A1_SAMPLE, bounds, weights, conflict_threshold=0.25)
    conflict_path = RESULTS_DIR / "conflict_analysis_summary.json"
    with open(conflict_path, "w", encoding="utf-8") as f:
        json.dump(conflict_res_a1, f, indent=2, ensure_ascii=False)

    print("  ✓ Domain Conflict Summary on A1 Sample Set:")
    print(f"    {'Domain':<15} {'Total Records':<15} {'Conflict Rate':<15} {'Mean CI':<10} {'Q_base':<10} {'Q_resolved':<12}")
    print("    " + "-" * 80)
    for dom, ds in conflict_res_a1["domain_summary"].items():
        print(f"    {dom:<15} {ds['total_records']:<15} {ds['conflict_rate']*100:.2f}%{'':<9} {ds['mean_ci']:<10} {ds['mean_q_base']:<10} {ds['mean_q_resolved']:<12}")

    # Update 7 domain quality with resolved scores
    resolved_domain_q_7 = {}
    for dom in QUALITY_DOMAINS:
        ds = conflict_res_a1["domain_summary"].get(dom, {})
        resolved_domain_q_7[dom] = ds.get("mean_q_resolved", final_domain_q_7[dom])

    # -------------------------------------------------------------
    # Step 4: Cross-System Domain Mapping (7 Domains -> 17 Domains)
    # -------------------------------------------------------------
    print("\n[Step 4/5] Mapping 7 SlimPajama Quality Domains to 17 The Pile Mixture Domains...")
    q_17 = build_17_domain_quality_vector(resolved_domain_q_7)
    q17_path = RESULTS_DIR / "q1_domain_quality_scores_17"
    save_17_domain_quality(q_17, q17_path)

    print("  ✓ Final 17-Domain Quality Vector Q_17:")
    for dom, score in sorted(q_17.items(), key=lambda x: x[1], reverse=True):
        print(f"    - {dom:25s}: {score:.4f}")

    # -------------------------------------------------------------
    # Step 5: Simplex Mixture Modeling & Multi-Scale Extrapolation
    # -------------------------------------------------------------
    print("\n[Step 5/5] Fitting 17-Domain Mixture Model & Evaluating Multi-Scale Generalization...")
    mixture_res = run_full_mixture_pipeline(q_17)

    mix_path = RESULTS_DIR / "mixture_modeling_results.json"
    with open(mix_path, "w", encoding="utf-8") as f:
        json.dump(mixture_res, f, indent=2, ensure_ascii=False)

    print("\n  ✓ Multi-Scale Evaluation Results (Train -> Test -> Extrapolation):")
    print(f"    {'Scale Split':<14} {'Samples':<10} {'Actual Loss':<14} {'Baseline R²':<14} {'Quality R²':<14} {'Spearman':<10}")
    print("    " + "-" * 78)
    for r in mixture_res["evaluation_results"]:
        print(f"    {r['split']:<14} {r['samples']:<10} {r['actual_mean_loss']:<14.4f} {r['baseline_r2']:<14.4f} {r['quality_r2']:<14.4f} {r['quality_spearman']:<10.4f}")

    print("\n  ✓ Top 5 Most Effective Domains (Lowest Standalone Loss b_i):")
    for d in mixture_res["domain_utilities"][:5]:
        print(f"    - {d['domain']:25s}: standalone loss = {d['standalone_loss_b']:.4f}, Q = {d['quality_Q']:.4f}")

    print("\n  ✓ Optimal Training Mixture p* (Realistic Capacity-Constrained & Diversity-Regularized):")
    top_p_real = sorted(mixture_res["optimal_recipes"]["realistic_regularized"].items(), key=lambda x: x[1], reverse=True)
    for dom, w in top_p_real:
        if w > 0.01:
            print(f"    - {dom:25s}: {w*100:6.2f}%")
    print(f"    -> Predicted 1M Loss: {mixture_res['optimal_recipes']['realistic_loss']:.4f}")

    print("\n  ✓ Theoretical Unconstrained Corner Solution (for comparison):")
    top_p_corner = sorted(mixture_res["optimal_recipes"]["unconstrained_corner"].items(), key=lambda x: x[1], reverse=True)
    for dom, w in top_p_corner:
        if w > 0.01:
            print(f"    - {dom:25s}: {w*100:6.2f}%")
    print(f"    -> Predicted 1M Loss: {mixture_res['optimal_recipes']['unconstrained_loss']:.4f}")

    elapsed = time.time() - start_time
    print("\n" + "=" * 70)
    print(f">>> [Problem 1] Pipeline Successfully Completed in {elapsed:.2f} seconds!")
    print(f">>> All deliverables generated in: {RESULTS_DIR}")
    print("=" * 70)


if __name__ == "__main__":
    main()
