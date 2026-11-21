"""Shared candidate features for offline training and online reranking."""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

FEATURE_NAMES = [
    "bm25_score", "bm25_rank", "dense_score", "dense_rank", "coverage", "idf_coverage",
    "subject_coverage", "query_doc_len_ratio", "query_len", "doc_len_log", "subject_len_log",
    "matched_numeric", "phrase_pair_coverage", "rrf_score",
]


class CandidateFeatures:
    """Prepare the query's features once for all candidates from this mailbox."""

    def __init__(
        self,
        engine: Any,
        mailbox: str,
        terms: list[str],
        stopwords: set[str],
        depth: int,
    ) -> None:
        self.engine = engine
        self.depth = depth
        self.query_len = len(terms)
        unique_terms = list(dict.fromkeys(terms))
        self.pairs = tuple(pairwise(unique_terms))
        self.numbers = tuple(term for term in unique_terms if term.isdigit())
        mailbox_index = engine.mailbox_postings.get(mailbox, {})
        doc_count = max(1, engine.mailbox_doc_counts.get(mailbox, 1))
        self.idf = {}
        for term in unique_terms:
            if term not in stopwords:
                df = len(mailbox_index.get(term, ()))
                self.idf[term] = math.log(1 + (doc_count - df + 0.5) / (df + 0.5))

    def for_document(
        self,
        doc_id: str,
        *,
        lexical_score: float = 0.0,
        lexical_rank: int = 0,
        dense_score: float = 0.0,
        dense_rank: int = 0,
    ) -> list[float]:
        terms = self.engine.term_freqs[doc_id]
        subject = self.engine.subject_freqs[doc_id]
        matched = [term for term in self.idf if term in terms]
        coverage_size = max(1, len(self.idf))
        available_pairs = {left: right for left, right in self.pairs if left in terms and right in terms}
        matched_pairs = set()
        if available_pairs:
            for left, right in pairwise(self.engine.token_sequences[doc_id]):
                if available_pairs.get(left) == right:
                    matched_pairs.add(left)
                    if len(matched_pairs) == len(available_pairs):
                        break

        doc_len = self.engine.lengths[doc_id]
        rrf = (1 / (60 + lexical_rank) if lexical_rank else 0.0) + (
            0.1 / (60 + dense_rank) if dense_rank else 0.0
        )
        return [
            lexical_score,
            lexical_rank / self.depth if lexical_rank else 2.0,
            dense_score,
            dense_rank / self.depth if dense_rank else 2.0,
            len(matched) / coverage_size,
            sum(self.idf[term] for term in matched),
            sum(term in subject for term in self.idf) / coverage_size,
            self.query_len / max(1, doc_len),
            self.query_len,
            math.log1p(doc_len),
            math.log1p(sum(subject.values())),
            sum(term in terms for term in self.numbers),
            len(matched_pairs) / max(1, len(self.pairs)),
            rrf,
        ]
