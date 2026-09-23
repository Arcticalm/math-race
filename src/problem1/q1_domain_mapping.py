# -*- coding: utf-8 -*-
"""Cross-system domain mapping from 7 SlimPajama quality domains to 17 The Pile mixture domains."""

import csv
import json
import numpy as np
from pathlib import Path
from typing import Dict

from problem1.config import MIXTURE_DOMAINS

# Reference semantic interpolation weights for inferred domains
# Mapping 11 inferred domains into linear combination of the 7 quality domains:
# [arxiv, book, c4, commoncrawl, github, stackexchange, wikipedia]
INFERRED_WEIGHTS = {
    # Academic & Scientific literature
    "pubmed_central": {"arxiv": 0.70, "wikipedia": 0.30},
    "pubmed_abstracts": {"arxiv": 0.70, "wikipedia": 0.30},
    "nih_exporter": {"arxiv": 0.50, "wikipedia": 0.50},
    "uspto_backgrounds": {"arxiv": 0.60, "wikipedia": 0.40},
    "philpapers": {"book": 0.60, "arxiv": 0.40},

    # Mathematical & Algorithmic
    "dm_mathematics": {"arxiv": 0.60, "stackexchange": 0.40},

    # Formal & Legal & Parliamentary
    "freelaw": {"wikipedia": 0.50, "book": 0.50},
    "europarl": {"wikipedia": 0.60, "c4": 0.40},

    # Technical Web & Discussion
    "hackernews": {"stackexchange": 0.60, "c4": 0.40},
    "ubuntu_irc": {"stackexchange": 0.50, "c4": 0.50},

    # Conversational & Web
    "enron_emails": {"c4": 0.60, "commoncrawl": 0.40}
}


def build_17_domain_quality_vector(
    domain_q_7: Dict[str, float]
) -> Dict[str, float]:
    """Map quality scores from 7 SlimPajama domains to 17 The Pile mixture domains."""
    q_17 = {}

    for dom in MIXTURE_DOMAINS:
        # 1. Direct mapping
        if dom in domain_q_7:
            q_17[dom] = float(domain_q_7[dom])
        # 2. Near direct mapping
        elif dom == "wikipedia_en" and "wikipedia" in domain_q_7:
            q_17[dom] = float(domain_q_7["wikipedia"])
        elif dom == "gutenberg_pg_19" and "book" in domain_q_7:
            q_17[dom] = float(domain_q_7["book"])
        elif dom == "pile_cc" and "commoncrawl" in domain_q_7:
            q_17[dom] = float(domain_q_7["commoncrawl"])
        # 3. Inferred mapping
        elif dom in INFERRED_WEIGHTS:
            interp_w = INFERRED_WEIGHTS[dom]
            val = sum(domain_q_7[k] * w for k, w in interp_w.items() if k in domain_q_7)
            q_17[dom] = float(val)
        else:
            # Fallback average
            q_17[dom] = float(np.mean(list(domain_q_7.values())))

    return q_17


def save_17_domain_quality(q_17: Dict[str, float], out_path: Path) -> None:
    """Save 17-domain quality scores to JSON and CSV."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path.with_suffix(".json"), "w", encoding="utf-8") as f:
        json.dump(q_17, f, indent=2, ensure_ascii=False)

    with open(out_path.with_suffix(".csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["domain", "quality_score_Q"])
        for dom, q in q_17.items():
            w.writerow([dom, round(q, 4)])
