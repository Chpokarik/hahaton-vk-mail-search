"""Offline experiment: compare semantic-only retrieval and BM25+dense RRF."""

from __future__ import annotations

import json
import math
import os
import statistics
import time
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from fastembed import TextEmbedding

from app import search_engine


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_PATH = Path(os.environ.get("MAIL_DATASET_ZIP", ROOT.parent / "mipt_mail_search_participants.zip"))
INDEX_PATH = Path(os.environ.get("MAIL_VECTOR_INDEX", Path(__file__).resolve().parent / ".cache" / "semantic-index.npz"))
MODEL_CACHE_PATH = Path(os.environ.get("MAIL_MODEL_CACHE", Path(__file__).resolve().parent / ".cache" / "fastembed"))
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def metric_rows(ranked: list[str], qrels: dict[str, set[str]], query_id: str) -> tuple[float, float, float, float]:
    relevant = qrels.get(query_id, set())
    if not relevant:
        return 0.0, 0.0, 0.0, 0.0
    recall10 = len(set(ranked[:10]) & relevant) / len(relevant)
    recall100 = len(set(ranked[:100]) & relevant) / len(relevant)
    dcg = sum(1 / math.log2(rank + 2) for rank, doc_id in enumerate(ranked[:10]) if doc_id in relevant)
    ideal = sum(1 / math.log2(rank + 2) for rank in range(min(10, len(relevant))))
    ndcg = dcg / ideal if ideal else 0.0
    mrr = next((1 / (rank + 1) for rank, doc_id in enumerate(ranked[:10]) if doc_id in relevant), 0.0)
    return recall10, recall100, ndcg, mrr


def aggregate(rows: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return tuple(statistics.fmean(row[i] for row in rows) for i in range(4))  # type: ignore[return-value]


def main() -> None:
    with zipfile.ZipFile(ARCHIVE_PATH) as archive:
        queries = [json.loads(line) for line in archive.read("queries_dev.jsonl").splitlines()]
        qrels_rows = [json.loads(line) for line in archive.read("qrels_dev.jsonl").splitlines()]
        documents = [json.loads(line) for line in archive.read("documents.jsonl").splitlines()]
    qrels: dict[str, set[str]] = defaultdict(set)
    for row in qrels_rows:
        if row.get("relevance", 0) > 0:
            qrels[row["query_id"]].add(row["doc_id"])
    docs = {doc["doc_id"]: doc for doc in documents}

    index = np.load(INDEX_PATH, allow_pickle=False)
    chunk_ids = index["doc_ids"]
    mailboxes = index["mailbox_ids"]
    vectors = index["vectors"].astype(np.float32, copy=False)
    model = TextEmbedding(
        model_name=MODEL_NAME,
        cache_dir=str(MODEL_CACHE_PATH),
        threads=int(os.environ.get("MAIL_EMBED_THREADS", "4")),
    )

    semantic_rankings: list[list[str]] = []
    lexical_rankings: list[list[str]] = []
    query_latencies: list[float] = []
    for query in queries:
        started = time.perf_counter()
        qvec = np.asarray(next(model.query_embed(query["query"])), dtype=np.float32)
        qvec /= max(float(np.linalg.norm(qvec)), 1e-12)
        mask = mailboxes == query["synthetic_user"]
        chunk_scores = vectors[mask] @ qvec
        selected_ids = chunk_ids[mask]
        query_day = date.fromisoformat(query["query_date"]) if query.get("query_date") else None
        best_by_doc: dict[str, float] = {}
        for doc_id, score in zip(selected_ids, chunk_scores):
            doc_id = str(doc_id)
            doc_date = docs[doc_id].get("doc_dt")
            if query_day and doc_date and date.fromisoformat(doc_date) > query_day:
                continue
            best_by_doc[doc_id] = max(best_by_doc.get(doc_id, -1.0), float(score))
        dense = sorted(best_by_doc, key=lambda doc_id: (-best_by_doc[doc_id], doc_id))
        semantic_rankings.append(dense[:100])
        query_latencies.append(time.perf_counter() - started)

        lexical = search_engine.search(
            query["query"], query["synthetic_user"], query_day, 100
        )
        lexical_rankings.append([row["doc_id"] for row in lexical])

    semantic_metrics = aggregate([
        metric_rows(ranking, qrels, query["query_id"])
        for ranking, query in zip(semantic_rankings, queries)
    ])
    print("semantic_only", " ".join(f"{name}={value:.4f}" for name, value in zip(("R@10", "R@100", "nDCG@10", "MRR@10"), semantic_metrics)))

    for lexical_weight, dense_weights in ((1.0, (0.1, 0.2, 0.3, 0.5)), (2.0, (0.05, 0.1, 0.2, 0.3, 0.5))):
        for dense_weight in dense_weights:
            per_query = []
            for query, lexical, dense in zip(queries, lexical_rankings, semantic_rankings):
                fused: dict[str, float] = defaultdict(float)
                for rank, doc_id in enumerate(lexical, 1):
                    fused[doc_id] += lexical_weight / (60 + rank)
                for rank, doc_id in enumerate(dense, 1):
                    fused[doc_id] += dense_weight / (60 + rank)
                ranked = sorted(fused, key=lambda doc_id: (-fused[doc_id], doc_id))
                per_query.append(metric_rows(ranked, qrels, query["query_id"]))
            values = aggregate(per_query)
            print(
                f"rrf lexical={lexical_weight:g} dense={dense_weight:g} "
                + " ".join(f"{name}={value:.4f}" for name, value in zip(("R@10", "R@100", "nDCG@10", "MRR@10"), values))
            )

    ordered = sorted(query_latencies)
    print(
        "query_vector_latency_ms",
        f"p50={statistics.median(ordered)*1000:.2f}",
        f"p95={ordered[math.ceil(.95*len(ordered))-1]*1000:.2f}",
        f"p99={ordered[math.ceil(.99*len(ordered))-1]*1000:.2f}",
        f"max={max(ordered)*1000:.2f}",
    )


if __name__ == "__main__":
    main()
