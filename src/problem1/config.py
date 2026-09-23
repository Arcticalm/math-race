# -*- coding: utf-8 -*-
"""Global configurations, file paths, and indicator metadata for Problem 1."""

from pathlib import Path

# Base directories
BASE_DIR = Path("/home/cc/-")
DATA_DIR = BASE_DIR / "real_attachments"
DOCS_DIR = BASE_DIR / "docs"
RESULTS_DIR = DOCS_DIR / "results"

# Data file paths
PATH_A1_SAMPLE = DATA_DIR / "A_data_value" / "slimpajama_quality_signal_sample.jsonl.xz"
PATH_A2_ARXIV = DATA_DIR / "A_data_value" / "slimpajama_quality_extended" / "arxiv_part-6777d8857c6e-000486.jsonl.xz"
PATH_A3_GITHUB = DATA_DIR / "A_data_value" / "slimpajama_quality_extended" / "github_part-6777d8857c6e-000275.jsonl.xz"

PATH_A4_TRAIN_MIX = DATA_DIR / "A_data_value" / "regmix_tables" / "train_mixture_1m.csv"
PATH_A5_TRAIN_LOSS = DATA_DIR / "A_data_value" / "regmix_tables" / "train_pile_loss_1m.csv"

PATH_A6_TEST_MIX_1M = DATA_DIR / "A_data_value" / "regmix_tables" / "test_mixture_1m.csv"
PATH_A7_TEST_LOSS_1M = DATA_DIR / "A_data_value" / "regmix_tables" / "test_pile_loss_1m.csv"
PATH_A8_TEST_MIX_60M = DATA_DIR / "A_data_value" / "regmix_tables" / "test_mixture_60m.csv"
PATH_A9_TEST_LOSS_60M = DATA_DIR / "A_data_value" / "regmix_tables" / "test_pile_loss_60m.csv"
PATH_A10_TEST_MIX_1B = DATA_DIR / "A_data_value" / "regmix_tables" / "test_mixture_1B.csv"
PATH_A11_TEST_LOSS_1B = DATA_DIR / "A_data_value" / "regmix_tables" / "test_pile_loss_1B.csv"

PATH_A12_EST_MIX_10B = DATA_DIR / "A_data_value" / "regmix_tables" / "est_mixture_10b.csv"
PATH_A13_EST_LOSS_10B = DATA_DIR / "A_data_value" / "regmix_tables" / "est_pile_loss_10b.csv"
PATH_A14_EST_MIX_70B = DATA_DIR / "A_data_value" / "regmix_tables" / "est_mixture_70b.csv"
PATH_A15_EST_LOSS_70B = DATA_DIR / "A_data_value" / "regmix_tables" / "est_pile_loss_70b.csv"

PATH_A16_DOMAIN_MAP = DATA_DIR / "A_data_value" / "domain_mapping_guide.csv"
PATH_A17_DOMAIN_SUMMARY = DATA_DIR / "A_data_value" / "regmix_domain_summary.csv"
PATH_A18_DOMAIN_SAMPLE = DATA_DIR / "A_data_value" / "regmix_domain_sample.jsonl.xz"

# List indicators (8)
LIST_INDICATORS = [
    "fineweb_edu",
    "fluency_en",
    "ad_en",
    "modernbert_cleanliness",
    "modernbert_readability",
    "modernbert_reasoning",
    "modernbert_professionalism",
    "qurater"
]

# Scalar indicators (14)
SCALAR_INDICATORS = [
    "dsir_books",
    "dsir_wiki",
    "dsir_math",
    "rps_doc_word_count",
    "rps_doc_num_sentences",
    "rps_doc_unigram_entropy",
    "rps_doc_frac_unique_words",
    "rps_doc_frac_no_alph_words",
    "rps_doc_frac_chars_top_2gram",
    "rps_doc_frac_chars_top_3gram",
    "rps_lines_uppercase_letter_fraction",
    "rps_lines_ending_with_terminal_punctution_mark",
    "rps_lines_numerical_chars_fraction",
    "rps_doc_mean_word_length"
]

ALL_INDICATORS = LIST_INDICATORS + SCALAR_INDICATORS

# Indicator direction specification:
# 'positive': higher is better (Min-Max: (x - min) / (max - min))
# 'negative': lower is better (Complement: (max - x) / (max - min))
# 'log_positive': heavy-tailed positive, apply log1p first, then positive Min-Max
INDICATOR_DIRECTIONS = {
    # 8 List-derived indicators
    "fineweb_edu": "positive",
    "fluency_en": "positive",
    "ad_en": "negative",  # ad score is negative, so complement
    "modernbert_cleanliness": "positive",
    "modernbert_readability": "positive",
    "modernbert_reasoning": "positive",
    "modernbert_professionalism": "positive",
    "qurater": "positive",

    # 14 Scalar indicators
    "dsir_books": "positive",  # log density ratio, closer to 0 is better
    "dsir_wiki": "positive",
    "dsir_math": "positive",
    "rps_doc_word_count": "log_positive",
    "rps_doc_num_sentences": "log_positive",
    "rps_doc_unigram_entropy": "positive",
    "rps_doc_frac_unique_words": "positive",
    "rps_doc_frac_no_alph_words": "negative",
    "rps_doc_frac_chars_top_2gram": "negative",
    "rps_doc_frac_chars_top_3gram": "negative",
    "rps_lines_uppercase_letter_fraction": "negative",
    "rps_lines_ending_with_terminal_punctution_mark": "positive",
    "rps_lines_numerical_chars_fraction": "negative",
    "rps_doc_mean_word_length": "positive"
}

# The 7 SlimPajama quality domains
QUALITY_DOMAINS = [
    "arxiv",
    "book",
    "c4",
    "commoncrawl",
    "github",
    "stackexchange",
    "wikipedia"
]

# The 17 The Pile mixture domains
MIXTURE_DOMAINS = [
    "arxiv",
    "freelaw",
    "nih_exporter",
    "pubmed_central",
    "wikipedia_en",
    "dm_mathematics",
    "github",
    "philpapers",
    "stackexchange",
    "enron_emails",
    "gutenberg_pg_19",
    "pile_cc",
    "ubuntu_irc",
    "europarl",
    "hackernews",
    "pubmed_abstracts",
    "uspto_backgrounds"
]

# The 13 domains monitored in validation loss tables
LOSS_DOMAINS = [
    "arxiv",
    "freelaw",
    "pubmed_central",
    "wikipedia_en",
    "dm_mathematics",
    "github",
    "stackexchange",
    "gutenberg_pg_19",
    "pile_cc",
    "ubuntu_irc",
    "hackernews",
    "pubmed_abstracts",
    "uspto_backgrounds"
]

# The 4 domains in mixture without direct loss column
UNMONITORED_LOSS_DOMAINS = [
    "nih_exporter",
    "philpapers",
    "enron_emails",
    "europarl"
]
