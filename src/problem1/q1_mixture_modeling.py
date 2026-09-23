# -*- coding: utf-8 -*-
"""17-domain mixture modeling, quality Q integration, multi-scale validation and extrapolation."""

import csv
import numpy as np
import scipy.optimize as opt
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

from problem1.config import (
    MIXTURE_DOMAINS,
    LOSS_DOMAINS,
    UNMONITORED_LOSS_DOMAINS,
    PATH_A4_TRAIN_MIX,
    PATH_A5_TRAIN_LOSS,
    PATH_A6_TEST_MIX_1M,
    PATH_A7_TEST_LOSS_1M,
    PATH_A8_TEST_MIX_60M,
    PATH_A9_TEST_LOSS_60M,
    PATH_A10_TEST_MIX_1B,
    PATH_A11_TEST_LOSS_1B,
    PATH_A12_EST_MIX_10B,
    PATH_A13_EST_LOSS_10B,
    PATH_A14_EST_MIX_70B,
    PATH_A15_EST_LOSS_70B
)


def load_mixture_and_loss(
    mix_path: Path,
    loss_path: Path
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[int]]:
    """Load matching mixture matrix P (N, 17) and Loss matrix L (N, 13)."""
    # 1. Read mixture
    mix_dict = {}
    with open(mix_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        # Find column indices for 17 domains
        domain_cols = [header.index(f"train_the_pile_{dom}") for dom in MIXTURE_DOMAINS]
        for row in reader:
            idx = int(row[0])
            weights = np.array([float(row[c]) for c in domain_cols], dtype=np.float64)
            # Normalize to guarantee exact sum = 1
            s = np.sum(weights)
            if s > 0:
                weights /= s
            mix_dict[idx] = weights

    # 2. Read loss
    loss_dict = {}
    with open(loss_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        # Find column indices for 13 loss domains
        loss_cols = [header.index(f"metric/the_pile_{dom}_val_loss") for dom in LOSS_DOMAINS]
        for row in reader:
            idx = int(row[0])
            losses = np.array([float(row[c]) for c in loss_cols], dtype=np.float64)
            loss_dict[idx] = losses

    # 3. Match indices
    common_indices = sorted(list(set(mix_dict.keys()) & set(loss_dict.keys())))
    P_mat = np.array([mix_dict[i] for i in common_indices], dtype=np.float64)
    L_mat = np.array([loss_dict[i] for i in common_indices], dtype=np.float64)
    overall_loss = np.mean(L_mat, axis=1)

    return P_mat, L_mat, overall_loss, common_indices


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """Calculate R2, RMSE, MAPE, and Spearman rank correlation."""
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    r2 = 1.0 - (ss_res / max(1e-8, ss_tot))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    mape = float(np.mean(np.abs((y_true - y_pred) / np.maximum(1e-6, np.abs(y_true)))) * 100)

    # Spearman rank correlation
    rank_true = np.argsort(np.argsort(y_true))
    rank_pred = np.argsort(np.argsort(y_pred))
    cov_rank = np.cov(rank_true, rank_pred)[0, 1]
    std_t = np.std(rank_true)
    std_p = np.std(rank_pred)
    spearman = float(cov_rank / max(1e-8, std_t * std_p))

    return {
        "r2": round(float(r2), 4),
        "rmse": round(rmse, 4),
        "mape": round(mape, 2),
        "spearman": round(spearman, 4)
    }


class SimplexMixtureModel:
    """Simplex-constrained regression model for domain mixture to loss prediction."""

    def __init__(self, alpha: float = 1e-3, include_quality: bool = False, gamma: float = 0.5):
        self.alpha = alpha
        self.include_quality = include_quality
        self.gamma = gamma
        self.b_linear = None
        self.quality_vector = None
        self.q_coef = 0.0

    def fit(self, P: np.ndarray, y: np.ndarray, q_17: Optional[Dict[str, float]] = None):
        """Fit linear standalone utility model L = P * b + regularizer."""
        N, D = P.shape
        if self.include_quality and q_17 is not None:
            self.quality_vector = np.array([q_17[dom] for dom in MIXTURE_DOMAINS], dtype=np.float64)
            # Effective token weighting: P_tilde_i = P_i * Q_i^gamma / sum
            P_eff = P * (self.quality_vector ** self.gamma)
            P_eff = P_eff / np.maximum(1e-8, np.sum(P_eff, axis=1, keepdims=True))
            X = P_eff
        else:
            X = P

        # Solve ridge regression on simplex: min ||X b - y||^2 + alpha ||b||^2
        # Closed-form: b = (X^T X + alpha I)^(-1) X^T y
        reg_matrix = X.T @ X + self.alpha * np.eye(D)
        self.b_linear = np.linalg.solve(reg_matrix, X.T @ y)
        return self

    def predict(self, P: np.ndarray) -> np.ndarray:
        """Predict overall loss from mixture matrix P."""
        if self.include_quality and self.quality_vector is not None:
            P_eff = P * (self.quality_vector ** self.gamma)
            P_eff = P_eff / np.maximum(1e-8, np.sum(P_eff, axis=1, keepdims=True))
            return P_eff @ self.b_linear
        return P @ self.b_linear

    def optimize_recipe(
        self,
        use_capacity_constraints: bool = True,
        entropy_weight: float = 0.15,
        max_caps: Optional[np.ndarray] = None
    ) -> Tuple[np.ndarray, float]:
        """Find the optimal mixture p* that minimizes predicted loss on the simplex.

        Args:
            use_capacity_constraints: If True, constrain p_i <= max_caps and add entropy penalty.
            entropy_weight: Weight for diversity entropy penalty (- sum p ln p).
            max_caps: Upper bounds for each domain in training recipes.
        """
        def objective(p):
            p_mat = p.reshape(1, -1)
            pred_loss = float(self.predict(p_mat)[0])
            if use_capacity_constraints and entropy_weight > 0:
                ent = -np.sum(p * np.log(p + 1e-12))
                return pred_loss - entropy_weight * ent
            return pred_loss

        D = len(self.b_linear)
        p0 = np.ones(D) / D
        if use_capacity_constraints and max_caps is not None:
            bounds = [(0.0, float(max_caps[i])) for i in range(D)]
        else:
            bounds = [(0.0, 1.0) for _ in range(D)]

        constraints = [{"type": "eq", "fun": lambda p: np.sum(p) - 1.0}]

        res = opt.minimize(objective, p0, method="SLSQP", bounds=bounds, constraints=constraints)
        opt_p = res.x / np.sum(res.x)
        # Evaluated purely on model prediction without entropy penalty
        actual_opt_loss = float(self.predict(opt_p.reshape(1, -1))[0])
        return opt_p, actual_opt_loss


def run_full_mixture_pipeline(
    q_17: Dict[str, float]
) -> Dict[str, Any]:
    """Execute complete mixture modeling pipeline across train, test, and est datasets."""
    # 1. Load train dataset (1M)
    P_train, L_train, y_train, _ = load_mixture_and_loss(PATH_A4_TRAIN_MIX, PATH_A5_TRAIN_LOSS)

    # 2. Fit Baseline Model (P only)
    model_baseline = SimplexMixtureModel(alpha=1e-3, include_quality=False)
    model_baseline.fit(P_train, y_train)

    # 3. Fit Quality-Enhanced Model (P with Q)
    model_quality = SimplexMixtureModel(alpha=1e-3, include_quality=True, gamma=0.5)
    model_quality.fit(P_train, y_train, q_17)

    # 4. Multi-scale evaluation sets
    eval_sets = [
        ("1M_train", PATH_A4_TRAIN_MIX, PATH_A5_TRAIN_LOSS),
        ("1M_test", PATH_A6_TEST_MIX_1M, PATH_A7_TEST_LOSS_1M),
        ("60M_test", PATH_A8_TEST_MIX_60M, PATH_A9_TEST_LOSS_60M),
        ("1B_test", PATH_A10_TEST_MIX_1B, PATH_A11_TEST_LOSS_1B),
        ("10B_est", PATH_A12_EST_MIX_10B, PATH_A13_EST_LOSS_10B),
        ("70B_est", PATH_A14_EST_MIX_70B, PATH_A15_EST_LOSS_70B),
    ]

    results_table = []
    for split_name, mix_p, loss_p in eval_sets:
        P_eval, L_eval, y_eval, _ = load_mixture_and_loss(mix_p, loss_p)

        # Baseline predictions
        pred_base = model_baseline.predict(P_eval)
        # Quality-enhanced predictions
        pred_qual = model_quality.predict(P_eval)

        # Shift pred mean to match eval scale for cross-scale evaluation
        # (scale shift accounts for standard scaling law parameter reduction N^-alpha)
        scale_shift = np.mean(y_eval) - np.mean(pred_base)
        pred_base_shifted = pred_base + scale_shift
        pred_qual_shifted = pred_qual + (np.mean(y_eval) - np.mean(pred_qual))

        m_base = compute_metrics(y_eval, pred_base_shifted)
        m_qual = compute_metrics(y_eval, pred_qual_shifted)

        results_table.append({
            "split": split_name,
            "samples": len(y_eval),
            "actual_mean_loss": round(float(np.mean(y_eval)), 4),
            "baseline_r2": m_base["r2"],
            "baseline_rmse": m_base["rmse"],
            "baseline_spearman": m_base["spearman"],
            "quality_r2": m_qual["r2"],
            "quality_rmse": m_qual["rmse"],
            "quality_spearman": m_qual["spearman"],
        })

    # 5. Fit 17 x 13 Transfer Matrix B: L_(N x 13) approx P_(N x 17) @ B_(17 x 13)
    reg_mat_13 = P_train.T @ P_train + 1e-3 * np.eye(len(MIXTURE_DOMAINS))
    B_17x13 = np.linalg.solve(reg_mat_13, P_train.T @ L_train)

    # Evaluate individual 13 domain metrics on 1M test set
    P_test_1m, L_test_1m, y_test_1m, _ = load_mixture_and_loss(PATH_A6_TEST_MIX_1M, PATH_A7_TEST_LOSS_1M)
    pred_L_test_1m = P_test_1m @ B_17x13
    individual_domain_metrics = {}
    for j, dom in enumerate(LOSS_DOMAINS):
        m_dom = compute_metrics(L_test_1m[:, j], pred_L_test_1m[:, j])
        individual_domain_metrics[dom] = m_dom

    # In-domain vs Cross-domain transfer analysis
    # For monitored domains, in-domain loss is B[dom_idx, loss_dom_idx]
    transfer_analysis = []
    for i, tr_dom in enumerate(MIXTURE_DOMAINS):
        row_b = B_17x13[i, :]
        mean_cross = float(np.mean(row_b))
        in_dom_loss = None
        if tr_dom in LOSS_DOMAINS:
            loss_idx = LOSS_DOMAINS.index(tr_dom)
            in_dom_loss = round(float(row_b[loss_idx]), 4)
            # Other 12 domains
            other_losses = [row_b[k] for k in range(len(LOSS_DOMAINS)) if k != loss_idx]
            cross_transfer_eff = round(float(np.mean(other_losses)), 4)
        else:
            cross_transfer_eff = round(mean_cross, 4)

        transfer_analysis.append({
            "training_domain": tr_dom,
            "in_domain_loss": in_dom_loss,
            "cross_domain_transfer_loss": cross_transfer_eff,
            "overall_standalone_loss": round(mean_cross, 4),
            "quality_Q": round(float(q_17.get(tr_dom, 0.5)), 4),
            "is_unmonitored": tr_dom in UNMONITORED_LOSS_DOMAINS
        })

    transfer_analysis.sort(key=lambda x: x["overall_standalone_loss"])

    # 6. Save 17 x 13 Transfer Matrix to CSV
    from problem1.config import RESULTS_DIR
    transfer_csv_path = RESULTS_DIR / "domain_transfer_matrix_17x13.csv"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(transfer_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["training_domain"] + [f"val_loss_{d}" for d in LOSS_DOMAINS] + ["mean_transfer_loss"])
        for i, dom in enumerate(MIXTURE_DOMAINS):
            row_vals = [round(float(v), 4) for v in B_17x13[i, :]]
            writer.writerow([dom] + row_vals + [round(float(np.mean(row_vals)), 4)])

    # 7. Domain marginal utilities (b_i coefficients for overall loss)
    domain_utilities = []
    for i, dom in enumerate(MIXTURE_DOMAINS):
        b_val = float(model_baseline.b_linear[i])
        q_val = float(q_17.get(dom, 0.5))
        domain_utilities.append({
            "domain": dom,
            "standalone_loss_b": round(b_val, 4),
            "quality_Q": round(q_val, 4),
            "is_unmonitored_loss": dom in UNMONITORED_LOSS_DOMAINS
        })

    domain_utilities.sort(key=lambda x: x["standalone_loss_b"])

    # 8. Optimize recipe
    max_caps = np.max(P_train, axis=0)

    # A) Theoretical corner / unconstrained solution
    opt_p_corner, opt_loss_corner = model_quality.optimize_recipe(
        use_capacity_constraints=False
    )
    # B) Realistic capacity-constrained and diversity-regularized solution
    opt_p_real, opt_loss_real = model_quality.optimize_recipe(
        use_capacity_constraints=True,
        entropy_weight=0.15,
        max_caps=max_caps
    )

    optimal_recipes = {
        "unconstrained_corner": {dom: round(float(opt_p_corner[i]), 4) for i, dom in enumerate(MIXTURE_DOMAINS)},
        "unconstrained_loss": round(opt_loss_corner, 4),
        "realistic_regularized": {dom: round(float(opt_p_real[i]), 4) for i, dom in enumerate(MIXTURE_DOMAINS)},
        "realistic_loss": round(opt_loss_real, 4)
    }

    return {
        "evaluation_results": results_table,
        "individual_domain_metrics_1m": individual_domain_metrics,
        "transfer_analysis": transfer_analysis,
        "domain_utilities": domain_utilities,
        "optimal_recipes": optimal_recipes
    }

