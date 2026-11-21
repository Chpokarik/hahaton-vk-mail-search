"""Evaluate the local search engine against the public development qrels.

Run from backend/: python evaluate.py [--latency-repeats 5]
This uses only the local corpus and does not call an external service.
"""

from __future__ import annotations

import argparse
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

from app import search_engine


DEFAULT_ARCHIVE = Path(__file__).resolve().parents[2] / "mipt_mail_search_participants.zip"


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def load_benchmark(path: Path) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    with zipfile.ZipFile(path) as archive:
        queries = [json.loads(line) for line in archive.read("queries_dev.jsonl").splitlines()]
        qrels_rows = [json.loads(line) for line in archive.read("qrels_dev.jsonl").splitlines()]
    qrels: dict[str, set[str]] = defaultdict(set)
    for row in qrels_rows:
        if row.get("relevance", 0) > 0:
            qrels[row["query_id"]].add(row["doc_id"])
    return queries, qrels


def evaluate(limit: int, repeats: int) -> dict[str, float | int]:
    archive_path = Path(os.environ.get("MAIL_DATASET_ZIP", DEFAULT_ARCHIVE))
    queries, qrels = load_benchmark(archive_path)
    per_query: list[tuple[float, float, float, float]] = []
    latencies: list[float] = []

    for query in queries:
        relevant = qrels.get(query["query_id"], set())
        as_of = query.get("query_date")

        started = time.perf_counter()
        results = search_engine.search(
            query["query"],
            query["synthetic_user"],
            date.fromisoformat(as_of) if as_of else None,
            limit,
        )
        elapsed = time.perf_counter() - started
        ids = [row["doc_id"] for row in results]

        def recall_at(k: int) -> float:
            return len(set(ids[:k]) & relevant) / len(relevant) if relevant else 0.0

        dcg = sum(1 / math.log2(rank + 2) for rank, doc_id in enumerate(ids[:10]) if doc_id in relevant)
        ideal = sum(1 / math.log2(rank + 2) for rank in range(min(10, len(relevant))))
        ndcg10 = dcg / ideal if ideal else 0.0
        mrr10 = next((1 / (rank + 1) for rank, doc_id in enumerate(ids[:10]) if doc_id in relevant), 0.0)
        per_query.append((recall_at(10), recall_at(100), ndcg10, mrr10))
        latencies.append(elapsed)

        # Repeat a warmed query to collect a more stable in-process latency sample.
        for _ in range(max(0, repeats - 1)):
            started = time.perf_counter()
            search_engine.search(
                query["query"],
                query["synthetic_user"],
                date.fromisoformat(as_of) if as_of else None,
                limit,
            )
            latencies.append(time.perf_counter() - started)

    mean = lambda column: statistics.fmean(row[column] for row in per_query)
    return {
        "queries": len(queries),
        "qrels": sum(map(len, qrels.values())),
        "Recall@10": mean(0),
        "Recall@100": mean(1),
        "nDCG@10": mean(2),
        "MRR@10": mean(3),
        "latency_samples": len(latencies),
        "latency_p50_ms": statistics.median(latencies) * 1000,
        "latency_p95_ms": percentile(latencies, 0.95) * 1000,
        "latency_p99_ms": percentile(latencies, 0.99) * 1000,
        "latency_max_ms": max(latencies, default=0.0) * 1000,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100, help="maximum candidates returned per query")
    parser.add_argument("--latency-repeats", type=int, default=5, help="warm in-process runs per query")
    args = parser.parse_args()
    for key, value in evaluate(args.limit, args.latency_repeats).items():
        print(f"{key}: {value:.4f}" if isinstance(value, float) else f"{key}: {value}")


if __name__ == "__main__":
    main()
