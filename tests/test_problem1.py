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
    scalarize_list_indicator,
    normalize_record,
    compute_normalization_bounds
)
from problem1.q1_quality_evaluation import (
    compute_critic_weights,
    compute_cv_weights,
    compute_combined_weights,
    evaluate_sample_score
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


if __name__ == "__main__":
    unittest.main()
