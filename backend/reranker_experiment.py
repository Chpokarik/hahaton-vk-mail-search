"""Cross-validated feature reranker experiment on public qrels (no API calls)."""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
from fastembed import TextEmbedding

from app import STOPWORDS, search_engine, tokenize


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_PATH = Path(os.environ.get("MAIL_DATASET_ZIP", ROOT.parent / "mipt_mail_search_participants.zip"))
INDEX_PATH = Path(os.environ.get("MAIL_VECTOR_INDEX", Path(__file__).resolve().parent / ".cache" / "semantic-index.npz"))
MODEL_CACHE_PATH = Path(os.environ.get("MAIL_MODEL_CACHE", Path(__file__).resolve().parent / ".cache" / "fastembed"))
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
FEATURE_NAMES = [
    "bm25_score", "bm25_rank", "dense_score", "dense_rank", "coverage", "idf_coverage",
    "subject_coverage", "query_doc_len_ratio", "query_len", "doc_len_log", "subject_len_log",
    "matched_numeric", "phrase_pair_coverage", "rrf_score",
]


def metrics(ranked: list[str], relevant: set[str]) -> tuple[float, float, float, float]:
    if not relevant:
        return 0.0, 0.0, 0.0, 0.0
    r10 = len(set(ranked[:10]) & relevant) / len(relevant)
    r100 = len(set(ranked[:100]) & relevant) / len(relevant)
    dcg = sum(1 / math.log2(rank + 2) for rank, docid in enumerate(ranked[:10]) if docid in relevant)
    idcg = sum(1 / math.log2(rank + 2) for rank in range(min(10, len(relevant))))
    ndcg = dcg / idcg if idcg else 0.0
    mrr = next((1 / (rank + 1) for rank, docid in enumerate(ranked[:10]) if docid in relevant), 0.0)
    return r10, r100, ndcg, mrr


def read_data() -> tuple[list[dict[str, Any]], dict[str, set[str]], dict[str, dict[str, Any]]]:
    with zipfile.ZipFile(ARCHIVE_PATH) as archive:
        queries = [json.loads(line) for line in archive.read("queries_dev.jsonl").splitlines()]
        rel_rows = [json.loads(line) for line in archive.read("qrels_dev.jsonl").splitlines()]
        documents = [json.loads(line) for line in archive.read("documents.jsonl").splitlines()]
    qrels: dict[str, set[str]] = defaultdict(set)
    for row in rel_rows:
        if row.get("relevance", 0) > 0:
            qrels[row["query_id"]].add(row["doc_id"])
    return queries, qrels, {doc["doc_id"]: doc for doc in documents}


def build_examples(depth: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, set[str]]]:
    queries, qrels, docs = read_data()
    index = np.load(INDEX_PATH, allow_pickle=False)
    chunk_ids = index["doc_ids"]
    mailbox_ids = index["mailbox_ids"]
    vectors = index["vectors"].astype(np.float32, copy=False)
    model = TextEmbedding(
        model_name=MODEL_NAME,
        cache_dir=str(MODEL_CACHE_PATH),
        threads=int(os.environ.get("MAIL_EMBED_THREADS", "4")),
    )
    examples: list[dict[str, Any]] = []
    query_meta: list[dict[str, Any]] = []

    for query in queries:
        query_id = query["query_id"]
        mailbox = query["synthetic_user"]
        query_day = date.fromisoformat(query["query_date"]) if query.get("query_date") else None
        terms = tokenize(query["query"])
        unique_terms = list(dict.fromkeys(terms))
        coverage_terms = set(unique_terms) - STOPWORDS

        lexical_rows = search_engine.search(query["query"], mailbox, query_day, depth)
        lexical_by_id = {row["doc_id"]: row for row in lexical_rows}
        qvec = np.asarray(next(model.query_embed(query["query"])), dtype=np.float32)
        qvec /= max(float(np.linalg.norm(qvec)), 1e-12)
        mask = mailbox_ids == mailbox
        chunk_scores = vectors[mask] @ qvec
        current_ids = chunk_ids[mask]
        dense_by_doc: dict[str, float] = {}
        for doc_id, score in zip(current_ids, chunk_scores):
            doc_id = str(doc_id)
            doc_date = docs[doc_id].get("doc_dt")
            if query_day and doc_date and date.fromisoformat(doc_date) > query_day:
                continue
            dense_by_doc[doc_id] = max(dense_by_doc.get(doc_id, -1.0), float(score))
        dense_order = sorted(dense_by_doc, key=lambda docid: (-dense_by_doc[docid], docid))[:depth]
        dense_rank = {docid: rank for rank, docid in enumerate(dense_order, 1)}

        candidate_ids = set(lexical_by_id) | set(dense_order)
        lexical_rank = {docid: rank for rank, docid in enumerate(lexical_by_id, 1)}
        mailbox_index = search_engine.mailbox_postings.get(mailbox, {})
        doc_count = max(1, search_engine.mailbox_doc_counts.get(mailbox, 1))
        query_numbers = {term for term in unique_terms if term.isdigit()}
        query_pairs = set(zip(unique_terms, unique_terms[1:]))

        # Precompute one token sequence per candidate so phrase adjacency is measured after lemmatization.
        token_sequences = {docid: tokenize(docs[docid].get("doc", "")) for docid in candidate_ids}
        for docid in sorted(candidate_ids):
            lexical_row = lexical_by_id.get(docid)
            doc_terms = set(search_engine.term_freqs[docid])
            subject_terms = set(search_engine.subject_freqs[docid])
            matched = doc_terms & coverage_terms
            idf_coverage = sum(
                math.log(1 + (doc_count - len(mailbox_index.get(term, ())) + 0.5) /
                         (len(mailbox_index.get(term, ())) + 0.5))
                for term in matched
            )
            sequence = token_sequences[docid]
            doc_pairs = set(zip(sequence, sequence[1:]))
            phrase_coverage = len(query_pairs & doc_pairs) / max(1, len(query_pairs))
            subject_coverage = len(subject_terms & coverage_terms) / max(1, len(coverage_terms))
            dlen = search_engine.lengths[docid]
            slen = sum(search_engine.subject_freqs[docid].values())
            brank = lexical_rank.get(docid, 0)
            drank = dense_rank.get(docid, 0)
            rrf = (1 / (60 + brank) if brank else 0) + (0.1 / (60 + drank) if drank else 0)
            features = [
                lexical_row["score"] if lexical_row else 0.0,
                brank / depth if brank else 2.0,
                dense_by_doc.get(docid, 0.0),
                drank / depth if drank else 2.0,
                len(matched) / max(1, len(coverage_terms)),
                idf_coverage,
                subject_coverage,
                len(terms) / max(1, dlen),
                len(terms),
                math.log1p(dlen),
                math.log1p(slen),
                len(query_numbers & (doc_terms)),
                phrase_coverage,
                rrf,
            ]
            examples.append({
                "query_id": query_id,
                "mailbox": mailbox,
                "doc_id": docid,
                "features": features,
                "label": int(docid in qrels.get(query_id, set())),
            })
        query_meta.append({"query_id": query_id, "mailbox": mailbox, "candidates": sorted(candidate_ids)})

    return examples, query_meta, qrels


def make_ranker() -> lgb.LGBMRanker:
    return lgb.LGBMRanker(
        objective="lambdarank",
        metric="ndcg",
        n_estimators=250,
        learning_rate=0.05,
        num_leaves=15,
        max_depth=5,
        min_child_samples=10,
        reg_lambda=2.0,
        random_state=42,
        n_jobs=4,
        verbosity=-1,
    )


def report(label: str, rows: list[tuple[float, float, float, float]]) -> None:
    vals = tuple(statistics.fmean(row[i] for row in rows) for i in range(4))
    print(label, " ".join(f"{name}={value:.4f}" for name, value in zip(("R@10", "R@100", "nDCG@10", "MRR@10"), vals)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth", type=int, default=100, help="lexical and dense candidates per query")
    args = parser.parse_args()
    examples, query_meta, qrels = build_examples(args.depth)
    by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for example in examples:
        by_query[example["query_id"]].append(example)
    queries = [meta["query_id"] for meta in query_meta]
    all_ids = {meta["query_id"]: meta["candidates"] for meta in query_meta}
    print(f"queries={len(queries)} candidates={len(examples)} positives={sum(x['label'] for x in examples)}")

    def shuffled_folds() -> list[list[str]]:
        ids = queries[:]
        random.Random(42).shuffle(ids)
        return [ids[i::5] for i in range(5)]

    folds = shuffled_folds()
    predictions: dict[str, list[tuple[str, float]]] = {}
    feature_rows: dict[str, list[dict[str, Any]]] = {}
    for fold in folds:
        valid = set(fold)
        train_queries = [qid for qid in queries if qid not in valid]
        train_rows = [row for qid in train_queries for row in by_query[qid]]
        group = [len(by_query[qid]) for qid in train_queries]
        X = np.asarray([row["features"] for row in train_rows], dtype=np.float32)
        y = np.asarray([row["label"] for row in train_rows], dtype=np.int32)
        ranker = make_ranker()
        ranker.fit(X, y, group=group)
        for qid in fold:
            rows = by_query[qid]
            scores = ranker.predict(np.asarray([row["features"] for row in rows], dtype=np.float32))
            predictions[qid] = [(row["doc_id"], float(score)) for row, score in zip(rows, scores)]
            feature_rows[qid] = rows

    baseline_rows = []
    hybrid_rows = []
    reranked_rows = []
    for qid in queries:
        rows = feature_rows[qid]
        relevant = qrels.get(qid, set())
        bm25 = sorted(rows, key=lambda row: (row["features"][1], row["doc_id"]))
        hybrid = sorted(rows, key=lambda row: (-row["features"][13], row["doc_id"]))
        reranked = sorted(predictions[qid], key=lambda item: (-item[1], item[0]))
        baseline_rows.append(metrics([row["doc_id"] for row in bm25], relevant))
        hybrid_rows.append(metrics([row["doc_id"] for row in hybrid], relevant))
        reranked_rows.append(metrics([docid for docid, _ in reranked], relevant))

    report("candidate_union_bm25_rank", baseline_rows)
    report("candidate_union_rrf", hybrid_rows)
    report("lambdamart_5fold_cv", reranked_rows)

    # Mailbox-held-out folds are a stricter generalization check than random query splits.
    mailbox_predictions: dict[str, list[tuple[str, float]]] = {}
    for mailbox in sorted({meta["mailbox"] for meta in query_meta}):
        valid_queries = [meta["query_id"] for meta in query_meta if meta["mailbox"] == mailbox]
        train_queries = [qid for qid in queries if qid not in set(valid_queries)]
        train_rows = [row for qid in train_queries for row in by_query[qid]]
        ranker = make_ranker()
        ranker.fit(
            np.asarray([row["features"] for row in train_rows], dtype=np.float32),
            np.asarray([row["label"] for row in train_rows], dtype=np.int32),
            group=[len(by_query[qid]) for qid in train_queries],
        )
        for qid in valid_queries:
            rows = by_query[qid]
            scores = ranker.predict(np.asarray([row["features"] for row in rows], dtype=np.float32))
            mailbox_predictions[qid] = [(row["doc_id"], float(score)) for row, score in zip(rows, scores)]
    mailbox_rows = []
    for qid, preds in mailbox_predictions.items():
        ranked = [docid for docid, _ in sorted(preds, key=lambda item: (-item[1], item[0]))]
        mailbox_rows.append(metrics(ranked, qrels.get(qid, set())))
    report("lambdamart_mailbox_holdout", mailbox_rows)


if __name__ == "__main__":
    main()
