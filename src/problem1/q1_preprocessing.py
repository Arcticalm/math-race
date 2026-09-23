# -*- coding: utf-8 -*-
"""Data preprocessing pipeline for 22 quality indicators in SlimPajama datasets."""

import json
import lzma
import math
import numpy as np
from pathlib import Path
from typing import Dict, Generator, Any, List, Optional

from problem1.config import (
    LIST_INDICATORS,
    SCALAR_INDICATORS,
    ALL_INDICATORS,
    INDICATOR_DIRECTIONS
)


def softmax(logits: List[float]) -> np.ndarray:
    """Compute numerically stable softmax probabilities with NaN handling."""
    arr = np.array(logits, dtype=np.float64)
    # If all are NaN or invalid, return uniform distribution
    if not np.any(np.isfinite(arr)):
        return np.ones(len(arr)) / max(1, len(arr))
    # Replace non-finite with minimal value
    arr = np.nan_to_num(arr, nan=-100.0, posinf=50.0, neginf=-100.0)
    exp_arr = np.exp(arr - np.max(arr))
    s = np.sum(exp_arr)
    if s <= 0 or not np.isfinite(s):
        return np.ones(len(arr)) / max(1, len(arr))
    return exp_arr / s


def scalarize_list_indicator(name: str, value: Any) -> float:
    """Scalarize 8 multi-dimensional list indicators with robust fallback."""
    if not isinstance(value, list) or len(value) == 0:
        if value is None or not np.isfinite(value):
            return 0.0
        return float(value)

    # Check if all elements in value are non-finite
    finite_vals = [v for v in value if v is not None and np.isfinite(v)]
    if len(finite_vals) == 0:
        # Fallback neutral default for each indicator
        if name in ("fineweb_edu", "modernbert_cleanliness", "modernbert_readability", "modernbert_reasoning", "modernbert_professionalism"):
            return 2.5
        elif name == "qurater":
            return 1.5
        elif name in ("fluency_en", "ad_en"):
            return 0.5
        return 0.0

    if name == "fineweb_edu":
        v = value[0]
        return float(v) if v is not None and np.isfinite(v) else 2.5

    elif name == "fluency_en":
        # 2-class logits: [non-fluent, fluent] -> return probability of fluent
        probs = softmax(value)
        p = float(probs[1]) if len(probs) >= 2 else float(probs[0])
        return p if np.isfinite(p) else 0.5

    elif name == "ad_en":
        # 2-class logits: [non-ad, ad] -> return probability of ad
        probs = softmax(value)
        p = float(probs[1]) if len(probs) >= 2 else float(probs[0])
        return p if np.isfinite(p) else 0.5

    elif name.startswith("modernbert_"):
        # 6-class ordinal logits (0 to 5) -> return expected score in [0, 5]
        probs = softmax(value)
        scores = np.arange(len(probs), dtype=np.float64)
        s = float(np.sum(scores * probs))
        return s if np.isfinite(s) else 2.5

    elif name == "qurater":
        # 4-class ordinal logits (0 to 3) -> return expected score in [0, 3]
        probs = softmax(value)
        scores = np.arange(len(probs), dtype=np.float64)
        s = float(np.sum(scores * probs))
        return s if np.isfinite(s) else 1.5

    v = value[0]
    return float(v) if v is not None and np.isfinite(v) else 0.0


def extract_scalar_indicators(record: Dict[str, Any]) -> Dict[str, float]:
    """Extract and scalarize all 22 indicators from a JSON record with NaN safety."""
    scalars = {}
    for name in LIST_INDICATORS:
        raw_val = record.get(name)
        val = scalarize_list_indicator(name, raw_val)
        scalars[name] = val if np.isfinite(val) else 0.0

    for name in SCALAR_INDICATORS:
        raw_val = record.get(name)
        if raw_val is None:
            scalars[name] = 0.0
        else:
            try:
                f_val = float(raw_val)
                scalars[name] = f_val if np.isfinite(f_val) else 0.0
            except (ValueError, TypeError):
                scalars[name] = 0.0

    return scalars


def stream_jsonl_xz(filepath: Path) -> Generator[Dict[str, Any], None, None]:
    """Stream decompression of .jsonl.xz file line by line."""
    with lzma.open(filepath, "rt", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                yield json.loads(line_str)


def compute_normalization_bounds(
    sample_path: Path,
    p_low: float = 0.5,
    p_high: float = 99.5,
    max_records: Optional[int] = None
) -> Dict[str, Dict[str, float]]:
    """Compute robust normalization bounds (Winsorization percentiles) from sample set."""
    collected = {k: [] for k in ALL_INDICATORS}
    
    count = 0
    for record in stream_jsonl_xz(sample_path):
        scalars = extract_scalar_indicators(record)
        for k, v in scalars.items():
            if INDICATOR_DIRECTIONS.get(k) == "log_positive":
                collected[k].append(math.log1p(max(0.0, v)))
            else:
                collected[k].append(v)
        count += 1
        if max_records and count >= max_records:
            break

    bounds = {}
    for k in ALL_INDICATORS:
        arr = np.array(collected[k], dtype=np.float64)
        arr = arr[np.isfinite(arr)]
        if len(arr) == 0:
            arr = np.array([0.0, 1.0])
        low_val = float(np.percentile(arr, p_low))
        high_val = float(np.percentile(arr, p_high))
        if high_val <= low_val:
            high_val = low_val + 1e-6
        bounds[k] = {
            "low": low_val,
            "high": high_val,
            "direction": INDICATOR_DIRECTIONS[k]
        }

    return bounds


def normalize_record(
    scalars: Dict[str, float],
    bounds: Dict[str, Dict[str, float]]
) -> Dict[str, float]:
    """Normalize and direction-standardize 22 indicators into [0, 1] (higher is better)."""
    norm_dict = {}
    for k, val in scalars.items():
        b = bounds[k]
        low = b["low"]
        high = b["high"]
        direction = b["direction"]

        v = math.log1p(max(0.0, val)) if direction == "log_positive" else val
        # Clip to [low, high]
        v_clipped = max(low, min(high, v))
        # Min-Max standard ratio in [0, 1]
        ratio = (v_clipped - low) / (high - low)

        # Apply direction transformation
        if direction in ("positive", "log_positive"):
            norm_dict[k] = float(ratio)
        elif direction == "negative":
            # Complement transformation for negative indicators: 1 - ratio
            norm_dict[k] = float(1.0 - ratio)
        else:
            norm_dict[k] = float(ratio)

    return norm_dict


def save_normalization_bounds(bounds: Dict[str, Dict[str, float]], out_path: Path) -> None:
    """Save normalization parameters to JSON file."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(bounds, f, indent=2, ensure_ascii=False)


def load_normalization_bounds(in_path: Path) -> Dict[str, Dict[str, float]]:
    """Load normalization parameters from JSON file."""
    with open(in_path, "r", encoding="utf-8") as f:
        return json.load(f)
