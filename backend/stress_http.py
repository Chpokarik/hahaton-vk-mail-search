"""Concurrent HTTP load check against the running local API."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import statistics
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


DEFAULT_ARCHIVE = Path(__file__).resolve().parents[2] / "mipt_mail_search_participants.zip"


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000/search")
    parser.add_argument("--workers", type=int, nargs="+", default=[8, 16, 32])
    parser.add_argument("--repeats", type=int, default=5, help="cycles through all public queries")
    args = parser.parse_args()

    with zipfile.ZipFile(DEFAULT_ARCHIVE) as archive:
        queries = [json.loads(line) for line in archive.read("queries_dev.jsonl").splitlines()]
    workload = [queries[index % len(queries)] for index in range(len(queries) * args.repeats)]

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
