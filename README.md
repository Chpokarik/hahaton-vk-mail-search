# VK Mail Search

Hackathon prototype for finding a letter in a mailbox from a natural-language request.

## Current backend

The live `/search` endpoint parses an explicitly requested receipt date (including «вчера» relative to `query_date`). When present, the backend first restricts both BM25 and semantic candidates to that mailbox and receipt day, then fuses and reranks the candidate union. It does not treat an unanchored event date as a receipt filter. Other queries use the same local BM25 and semantic retrieval without the exact-day restriction. Search inference is local; no request goes to a model API. Without the optional vector cache, the date-aware BM25 path remains available. The request and response contract is unchanged.

The 99 public queries (565 relevance labels) all contain an explicit receipt date. Thus they cannot measure general no-date semantic search. On this same set, lexical date-filtered search gets `Recall@10=0.8879`, `Recall@100=0.9923`, `nDCG@10=0.9304`, and `MRR@10=0.9503`. The date-constrained hybrid API gets `0.8911`, `1.0000`, `0.9373`, and `0.9600`, respectively; this is an in-sample result because the bundled ranker has seen the public labels. Date-constrained candidate generation plus a five-fold query-held-out ranker reaches `nDCG@10=0.9584` / `MRR@10=0.9798`; whole-mailbox holdout gives `0.8988` / `0.9116`, showing that generalization to unseen mailboxes still needs work.

For a separate small diagnostic, eight hand-labeled queries use five mailboxes absent from the public query set. The active hybrid gets `nDCG@10=0.6100`, `MRR@10=0.6012` on the seven queries with no receipt-date filter; lexical gets `0.6113` / `0.6333`. These labels are transparent but limited controls, not a substitute for organizer qrels. One additional control has an event date in the body and an explicit receipt date in the query; the search correctly applies only the receipt-date filter. See [benchmark_controls/README.md](backend/benchmark_controls/README.md).

| Mode on public queries | Recall@10 | Recall@100 | nDCG@10 | MRR@10 |
| --- | ---: | ---: | ---: | ---: |
| BM25 without receipt-date parsing (ablation) | 0.5239 | 0.8637 | 0.3665 | 0.3582 |
| BM25 with exact receipt-day filter | 0.8879 | 0.9923 | 0.9304 | 0.9503 |
| Date-constrained hybrid API (in-sample) | 0.8911 | 1.0000 | 0.9373 | 0.9600 |

All rows use the same 99 public queries and 565 relevance labels; only the first row removes the parsed receipt-date constraint.

On this machine, the updated API completed 495 HTTP requests with zero errors at 64 workers. After moving the day restriction ahead of dense scoring, end-to-end client-observed p99 was 282.5 ms for receipt-date queries and 906.0 ms when those phrases were removed to exercise the general hybrid path; the corresponding maxima were 285.9 ms and 941.5 ms. `stress_http.py` measures the full local HTTP round trip, including client overhead. Both p99 values are below the 1-second requirement, though the no-date workload has little headroom; target deployment hardware still needs its own measurement.

## Start the backend

Keep `mipt_mail_search_participants.zip` one directory above this repository, or set `MAIL_DATASET_ZIP` to another path.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-search-lab.txt
python build_semantic_index.py
uvicorn app:app --port 8000
```

Open `http://localhost:8000/docs` for interactive API documentation.

## Search API

`POST /search`

```json
{
  "query": "когда вернут деньги за билет",
  "synthetic_user": "box-...",
  "query_date": "2026-03-12",
  "limit": 20
}
```

The response contains `count` and `results`, each with `doc_id`, `date`, `snippet`, and `score`. `synthetic_user` is required so results stay within the selected mailbox. `query_date` excludes later mail and provides the reference day for relative dates such as «вчера»; it may be omitted.

Other routes:

- `GET /health` — service status and indexed document count.
- `GET /mailboxes` — available synthetic mailboxes and message counts.
- `GET /mailboxes/{synthetic_user}/messages?offset=0&limit=50` — inbox page.
- `GET /search?q=...&synthetic_user=...` — simple browser-friendly search.

The frontend can call the API directly from a local development server; CORS is enabled.

## Evaluate the live lexical engine

Run from `backend/` after installing the backend dependencies:

```bash
python evaluate.py --suite both --latency-repeats 5
```

This reports Recall@10, Recall@100, nDCG@10, MRR@10, and in-process p50/p95/p99 latency separately for queries with and without a parsed receipt date. `--suite public` measures organizer labels, `--suite controls` measures the documented diagnostic set, and `--suite both` prints both without combining them. `--mode lexical` compares against BM25. The bundled reranker was trained on public relevance labels, so use held-out evaluation for the hybrid path.

To load-test the running HTTP API with repeated public queries:

```bash
python stress_http.py --workers 8 16 32 64 --repeats 5
python stress_http.py --workers 8 32 64 --repeats 5 --without-receipt-dates
```

## Optional local semantic-search experiments

The semantic model is Potion multilingual embeddings run locally. Model weights are downloaded once during setup; query text is not sent to an inference API. The generated model cache and vector index stay under the ignored `backend/.cache/` directory and are not committed. The included `backend/ranker_model.txt` is trained on the public qrels and is used automatically when both the matching vector index and model cache exist. Install the optional search dependencies to enable the hybrid path; otherwise the API falls back to BM25.

```bash
cd backend
pip install -r requirements-search-lab.txt
python build_semantic_index.py
MAIL_RECEIPT_DATES=0 MAIL_LEMMATIZE=1 MAIL_MAILBOX_IDF=1 MAIL_SUBJECT_BOOST=0.25 MAIL_COVERAGE_BOOST=2 python evaluate_dense.py
MAIL_LEMMATIZE=1 MAIL_MAILBOX_IDF=1 MAIL_SUBJECT_BOOST=0.25 MAIL_COVERAGE_BOOST=2 python reranker_experiment.py --depth 150
```

The reranker experiment applies the same exact receipt-day constraint to semantic candidates and reports five-fold query-held-out and mailbox-held-out results. Its default configuration is 150 trees, five leaves, max depth 3, 30 minimum child samples, and L2 regularization 8. To train a model from the full public set, pass `--save-model ranker_model.txt`; evaluate held-out and control metrics before replacing the tracked model.

The default embedding model is `minishlab/potion-multilingual-128M`, and the search endpoint retrieves 150 lexical and 150 dense candidates by default. You can override these settings with `MAIL_EMBEDDING_MODEL` and `MAIL_CANDIDATE_DEPTH`; rebuild the vector index and ranker together when changing the embedding model or candidate depth.

## Dataset

The ZIP archive is deliberately not stored in Git. It contains pseudonymized emails, public queries, and qrels. Keep it outside the repository and never commit it.
