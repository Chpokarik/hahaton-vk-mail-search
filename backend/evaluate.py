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
CONTROL_DIR = Path(__file__).resolve().parent / "benchmark_controls"


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


def load_controls() -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    queries = [json.loads(line) for line in (CONTROL_DIR / "queries.jsonl").read_text().splitlines()]
    rows = [json.loads(line) for line in (CONTROL_DIR / "qrels.jsonl").read_text().splitlines()]
    qrels: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.get("relevance", 0) > 0:
            qrels[row["query_id"]].add(row["doc_id"])
    return queries, qrels


def evaluate(
    limit: int, repeats: int, mode: str, suite: str = "public", worst: int = 0
) -> list[dict[str, float | int | str | None]]:
    archive_path = Path(os.environ.get("MAIL_DATASET_ZIP", DEFAULT_ARCHIVE))
    selected = ("public", "controls") if suite == "both" else (suite,)
    reports = []
    search_method = search_engine.search_lexical if mode == "lexical" else search_engine.search

    for suite_name in selected:
        queries, qrels = load_benchmark(archive_path) if suite_name == "public" else load_controls()
        by_kind: dict[str, list[tuple[float, float, float, float]]] = defaultdict(list)
        latencies: dict[str, list[float]] = defaultdict(list)
        query_losses: list[tuple[float, str, str, str]] = []
        query_kinds = {
            query["query_id"]: (
                "with_receipt_date"
                if search_engine.parse_query(
                    query["query"],
                    date.fromisoformat(query["query_date"]) if query.get("query_date") else None,
                ).day
                else "without_receipt_date"
            )
            for query in queries
        }
        for query in queries:
            relevant = qrels.get(query["query_id"], set())
            as_of = query.get("query_date")
            reference_day = date.fromisoformat(as_of) if as_of else None

            started = time.perf_counter()
            results = search_method(
                query["query"],
                query["synthetic_user"],
                reference_day,
                limit,
            )
            elapsed = time.perf_counter() - started
            ids = [row["doc_id"] for row in results]

            def recall_at(k: int) -> float:
                return len(set(ids[:k]) & relevant) / len(relevant) if relevant else 0.0

            dcg = sum(1 / math.log2(rank + 2) for rank, doc_id in enumerate(ids[:10]) if doc_id in relevant)
            ideal = sum(1 / math.log2(rank + 2) for rank in range(min(10, len(relevant))))
            ndcg10 = dcg / ideal if ideal else 0.0
            if worst and ndcg10 < 1:
                query_losses.append((ndcg10, query["query_id"], as_of or "", query["query"]))
            mrr10 = next((1 / (rank + 1) for rank, doc_id in enumerate(ids[:10]) if doc_id in relevant), 0.0)
            kind = query_kinds[query["query_id"]]
            by_kind[kind].append((recall_at(10), recall_at(100), ndcg10, mrr10))
            latencies[kind].append(elapsed)

            # Repeat a warmed query to collect a more stable in-process latency sample.
            for _ in range(max(0, repeats - 1)):
                started = time.perf_counter()
                search_method(
                    query["query"],
                    query["synthetic_user"],
                    reference_day,
                    limit,
                )
                latencies[kind].append(time.perf_counter() - started)

        for ndcg, query_id, as_of, query_text in sorted(query_losses)[:worst]:
            print(f"{suite_name} nDCG@10={ndcg:.4f} {query_id} {as_of} {query_text}")
        for kind in ("with_receipt_date", "without_receipt_date"):
            rows = by_kind[kind]
            samples = latencies[kind]
            mean = lambda column: statistics.fmean(row[column] for row in rows) if rows else None
            reports.append({
                "suite": suite_name, "group": kind, "mode": mode,
                "queries": len(rows),
                "qrels": sum(len(qrels.get(query["query_id"], ())) for query in queries if query_kinds[query["query_id"]] == kind),
                "Recall@10": mean(0), "Recall@100": mean(1), "nDCG@10": mean(2), "MRR@10": mean(3),
                "latency_samples": len(samples),
                "latency_p50_ms": statistics.median(samples) * 1000 if samples else None,
                "latency_p95_ms": percentile(samples, 0.95) * 1000 if samples else None,
                "latency_p99_ms": percentile(samples, 0.99) * 1000 if samples else None,
                "latency_max_ms": max(samples, default=0.0) * 1000 if samples else None,
            })
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100, help="maximum candidates returned per query")
    parser.add_argument("--latency-repeats", type=int, default=5, help="warm in-process runs per query")
    parser.add_argument("--mode", choices=("active", "lexical"), default="active")
    parser.add_argument("--suite", choices=("public", "controls", "both"), default="public")
    parser.add_argument("--worst", type=int, default=0, help="show the lowest-scoring queries per suite")
    args = parser.parse_args()
    if args.worst < 0:
        parser.error("--worst must be non-negative")
    for report in evaluate(args.limit, args.latency_repeats, args.mode, args.suite, args.worst):
        print("\n".join(f"{key}: {value:.4f}" if isinstance(value, float) else f"{key}: {value}" for key, value in report.items()))
        print()
    if args.mode == "active" and search_engine.ranker is not None:
        print("note: the included reranker is trained on public qrels; use reranker_experiment.py for held-out metrics")


if __name__ == "__main__":
    main()
