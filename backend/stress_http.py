"""Concurrent HTTP load check against the running local API."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import statistics
import time
import urllib.request
import zipfile
from datetime import date
from pathlib import Path
from typing import Any


from query_dates import parse_receipt_query


DEFAULT_ARCHIVE = Path(__file__).resolve().parents[2] / "mipt_mail_search_participants.zip"


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000/search")
    parser.add_argument("--workers", type=int, nargs="+", default=[8, 16, 32])
    parser.add_argument("--repeats", type=int, default=5, help="cycles through all public queries")
    parser.add_argument("--without-receipt-dates", action="store_true", help="exercise hybrid retrieval")
    args = parser.parse_args()
    if args.repeats < 1 or min(args.workers) < 1:
        parser.error("repeats and worker counts must be positive")

    archive_path = Path(os.environ.get("MAIL_DATASET_ZIP", DEFAULT_ARCHIVE))
    with zipfile.ZipFile(archive_path) as archive:
        queries = [json.loads(line) for line in archive.read("queries_dev.jsonl").splitlines()]
    if args.without_receipt_dates:
        for query in queries:
            reference = date.fromisoformat(query["query_date"]) if query.get("query_date") else None
            query["query"] = parse_receipt_query(query["query"], reference).text
    workload = queries * args.repeats

    def request(query: dict[str, Any]) -> float:
        body = json.dumps(
            {
                "query": query["query"],
                "synthetic_user": query["synthetic_user"],
                "query_date": query.get("query_date"),
                "limit": 20,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            args.url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read())
            if response.status != 200 or "results" not in result:
                raise RuntimeError(f"unexpected response status/body: {response.status}")
        return time.perf_counter() - started

    for workers in args.workers:
        latencies: list[float] = []
        errors: list[str] = []
        started = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(request, query) for query in workload]
            for future in concurrent.futures.as_completed(futures):
                try:
                    latencies.append(future.result())
                except Exception as exc:
                    errors.append(str(exc))
        elapsed = time.perf_counter() - started
        if not latencies:
            raise SystemExit(f"all HTTP requests failed for {workers} workers: {errors[:3]}")
        print(
            f"workers={workers} requests={len(workload)} errors={len(errors)} "
            f"wall_s={elapsed:.2f} throughput={len(workload) / elapsed:.1f}/s "
            f"p50={statistics.median(latencies) * 1000:.1f}ms "
            f"p95={percentile(latencies, 0.95) * 1000:.1f}ms "
            f"p99={percentile(latencies, 0.99) * 1000:.1f}ms "
            f"max={max(latencies) * 1000:.1f}ms"
        )
        if errors:
            print("first_errors:", errors[:3])


if __name__ == "__main__":
    main()
