# -*- coding: utf-8 -*-
"""Unit tests for Problem 1 modules."""

import sys
import unittest
import numpy as np
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from problem1.config import ALL_INDICATORS, MIXTURE_DOMAINS, QUALITY_DOMAINS
from problem1.q1_preprocessing import (
    scalarize_list_indicator
)
from problem1.q1_quality_evaluation import (
    compute_combined_weights
)
from problem1.q1_conflict_resolution import (
    compute_conflict_index,
    compute_resolved_score
)
from problem1.q1_domain_mapping import (
    build_17_domain_quality_vector
)
from problem1.q1_mixture_modeling import (
    SimplexMixtureModel
)


class TestProblem1(unittest.TestCase):

    def test_scalarize_list_indicator(self):
        # 1. fineweb_edu
        self.assertAlmostEqual(scalarize_list_indicator("fineweb_edu", [2.5]), 2.5)

        # 2. fluency_en: [non-fluent, fluent]
        self.assertGreater(scalarize_list_indicator("fluency_en", [0.0, 5.0]), 0.9)
        self.assertLess(scalarize_list_indicator("fluency_en", [5.0, 0.0]), 0.1)

        # 3. ad_en: [non-ad, ad]
        self.assertGreater(scalarize_list_indicator("ad_en", [0.0, 5.0]), 0.9)

        # 4. modernbert ordinal expectation
        # when logits peak at index 5
        self.assertGreater(scalarize_list_indicator("modernbert_cleanliness", [-10, -10, -10, -10, -10, 10]), 4.9)
        # when logits peak at index 0
        self.assertLess(scalarize_list_indicator("modernbert_cleanliness", [10, -10, -10, -10, -10, -10]), 0.1)

    def test_critic_and_cv_weights(self):
        np.random.seed(42)
        X = np.random.uniform(0.1, 0.9, size=(100, 22))
        w = compute_combined_weights(X)
        self.assertEqual(len(w), 22)
        total_w = sum(w.values())
        self.assertAlmostEqual(total_w, 1.0, places=5)
        for k, v in w.items():
            self.assertGreater(v, 0.0)

    def test_conflict_index(self):
        # Case 1: Cog high, Surf low -> high conflict
        norm_dict_conflict = {k: 0.9 for k in ALL_INDICATORS}
        for k in ["fluency_en", "ad_en", "modernbert_readability", "rps_doc_frac_chars_top_2gram", "rps_lines_ending_with_terminal_punctution_mark"]:
            norm_dict_conflict[k] = 0.1

        ci, s_cog, s_surf = compute_conflict_index(norm_dict_conflict)
        self.assertGreater(ci, 0.5)

        # Test resolved score penalty
        q_base = 0.8
        q_resolved = compute_resolved_score(q_base, ci, tau_domain=0.20, decay_lambda=0.5)
        self.assertLess(q_resolved, q_base)

    def test_domain_mapping(self):
        mock_q_7 = {dom: 0.5 + 0.05 * i for i, dom in enumerate(QUALITY_DOMAINS)}
        q_17 = build_17_domain_quality_vector(mock_q_7)
        self.assertEqual(len(q_17), 17)
        for dom in MIXTURE_DOMAINS:
            self.assertIn(dom, q_17)
            self.assertTrue(0.0 <= q_17[dom] <= 1.0)

    def test_simplex_mixture_model(self):
        np.random.seed(42)
        N, D = 50, 17
        P = np.random.dirichlet(np.ones(D), size=N)
        true_b = np.linspace(4.5, 6.5, D)
        y = P @ true_b + np.random.normal(0, 0.05, size=N)

        model = SimplexMixtureModel(alpha=1e-3, include_quality=False)
        model.fit(P, y)
        preds = model.predict(P)
        self.assertEqual(len(preds), N)

        opt_p, opt_loss = model.optimize_recipe()
        self.assertAlmostEqual(np.sum(opt_p), 1.0, places=5)
        self.assertTrue(np.all(opt_p >= -1e-6))
        self.assertLess(opt_loss, np.mean(y))

    def test_conflict_comparison(self):
        from problem1.q1_conflict_resolution import compare_conflict_sample_vs_extended
        a1_mock = {
            "arxiv": {"total_records": 1000, "conflict_rate": 0.14, "mean_ci": 0.18, "mean_q_base": 0.63, "mean_q_resolved": 0.62},
            "github": {"total_records": 2000, "conflict_rate": 0.15, "mean_ci": 0.15, "mean_q_base": 0.47, "mean_q_resolved": 0.46}
        }
        a2_mock = {
            "arxiv": {"total_records": 10000, "conflict_rate": 0.13, "mean_ci": 0.178, "mean_q_base": 0.63, "mean_q_resolved": 0.62}
        }
        a3_mock = {
            "github": {"total_records": 50000, "conflict_rate": 0.148, "mean_ci": 0.148, "mean_q_base": 0.47, "mean_q_resolved": 0.46}
        }
        comp = compare_conflict_sample_vs_extended(a1_mock, a2_mock, a3_mock)
        self.assertEqual(len(comp), 2)
        self.assertTrue(comp[0]["is_consistent"])
        self.assertTrue(comp[1]["is_consistent"])

    def test_transfer_matrix(self):
        N, D, K = 30, 17, 13
        P = np.random.dirichlet(np.ones(D), size=N)
        B_true = np.random.uniform(3.0, 6.0, size=(D, K))
        L = P @ B_true + np.random.normal(0, 0.01, size=(N, K))
        reg = P.T @ P + 1e-3 * np.eye(D)
        B_est = np.linalg.solve(reg, P.T @ L)
        self.assertEqual(B_est.shape, (D, K))


if __name__ == "__main__":
    unittest.main()

