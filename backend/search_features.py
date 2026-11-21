"""Shared candidate features for offline training and online reranking."""

from __future__ import annotations

import math
from typing import Any

FEATURE_NAMES = [
    "bm25_score", "bm25_rank", "dense_score", "dense_rank", "coverage", "idf_coverage",
    "subject_coverage", "query_doc_len_ratio", "query_len", "doc_len_log", "subject_len_log",
    "matched_numeric", "phrase_pair_coverage", "rrf_score",
]


def candidate_features(
    engine: Any,
    query: str,
    doc_id: str,
    *,
    lexical_score: float = 0.0,
    lexical_rank: int = 0,
    dense_score: float = 0.0,
    dense_rank: int = 0,
    depth: int = 100,
    tokenizer: Any,
    stopwords: set[str],
) -> list[float]:
    terms = tokenizer(query)
    unique_terms = list(dict.fromkeys(terms))
    coverage_terms = set(unique_terms) - stopwords
    doc_terms = set(engine.term_freqs[doc_id])
    subject_terms = set(engine.subject_freqs[doc_id])
    matched = doc_terms & coverage_terms
    mailbox = engine.by_id[doc_id]["synthetic_user"]
    mailbox_index = engine.mailbox_postings.get(mailbox, {})
    doc_count = max(1, engine.mailbox_doc_counts.get(mailbox, 1))
    idf_coverage = sum(
        math.log(
            1
            + (doc_count - len(mailbox_index.get(term, ())) + 0.5)
            / (len(mailbox_index.get(term, ())) + 0.5)
        )
        for term in matched
    )
    sequence = engine.token_sequences[doc_id]
    query_pairs = set(zip(unique_terms, unique_terms[1:]))
    matched_pairs = {
        (sequence[index - 1], sequence[index])
        for index in range(1, len(sequence))
        if (sequence[index - 1], sequence[index]) in query_pairs
    }
    phrase_coverage = len(matched_pairs) / max(1, len(query_pairs))
    subject_coverage = len(subject_terms & coverage_terms) / max(1, len(coverage_terms))
    doc_len = engine.lengths[doc_id]
    subject_len = sum(engine.subject_freqs[doc_id].values())
    rrf = (1 / (60 + lexical_rank) if lexical_rank else 0.0) + (
        0.1 / (60 + dense_rank) if dense_rank else 0.0
    )
    query_numbers = {term for term in unique_terms if term.isdigit()}
    return [
        lexical_score,
        lexical_rank / depth if lexical_rank else 2.0,
        dense_score,
        dense_rank / depth if dense_rank else 2.0,
        len(matched) / max(1, len(coverage_terms)),
        idf_coverage,
        subject_coverage,
        len(terms) / max(1, doc_len),
        len(terms),
        math.log1p(doc_len),
        math.log1p(subject_len),
        len(query_numbers & doc_terms),
        phrase_coverage,
        rrf,
    ]
