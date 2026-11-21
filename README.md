# VK Mail Search

Hackathon prototype for finding a letter in a mailbox from a natural-language request.

## Current backend

The live `/search` endpoint parses an explicitly requested receipt date (including «вчера» relative to `query_date`) and searches only that mailbox's messages from that day. Other queries use a local BM25 engine with Russian lemmatization, mailbox-specific statistics, subject and term-coverage boosts, and, when the ignored local vector index is present, local Potion embeddings plus a LightGBM reranker. Search inference is local; no request goes to a model API. Without the optional vector cache, the date-aware BM25 path remains available.

On the 99 public queries (565 relevance labels), the date-aware API gets `Recall@10=0.8879`, `Recall@100=0.9923`, `nDCG@10=0.9304`, and `MRR@10=0.9503`. This benchmark explicitly asks about receipt dates, so the engine resolves that constraint from the query and mailbox metadata. With receipt-date parsing disabled, Potion plus the LightGBM reranker gets `nDCG@10=0.485` and `MRR@10=0.494` across three five-fold query-held-out splits on the same public queries; whole-mailbox holdout gives `nDCG@10=0.479` and `MRR@10=0.489`. This is an ablation, not an evaluation on a separate no-date qrel set. The organizers' private benchmark may have a different query mix.

| Mode on public queries | Recall@10 | Recall@100 | nDCG@10 | MRR@10 |
| --- | ---: | ---: | ---: | ---: |
| BM25 lexical baseline | 0.5239 | 0.8637 | 0.3665 | 0.3582 |
| Date-aware integrated API | 0.8879 | 0.9923 | 0.9304 | 0.9503 |

The table uses the public date-heavy queries. Use the held-out hybrid ablation above to assess the reranker without receipt-date parsing.

On this machine, 495 HTTP requests at each concurrency level completed with zero errors. At 64 workers, p99 was 46.6 ms for the public receipt-date queries and 544.1 ms when those date phrases were removed to exercise hybrid retrieval. The latter is a latency workload only; it has no matching quality labels. Both are strictly below the 1-second requirement in these runs; remeasure on the final deployment machine.

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
python evaluate.py --latency-repeats 5
```

This reports Recall@10, Recall@100, nDCG@10, MRR@10, and in-process p50/p95/p99 latency for the public queries. `--mode lexical` measures the active lexical path. For the original lexical baseline, run `MAIL_RECEIPT_DATES=0 python evaluate.py --mode lexical`. The bundled reranker was trained on public relevance labels, so use held-out evaluation for the hybrid path.

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
MAIL_RECEIPT_DATES=0 MAIL_LEMMATIZE=1 MAIL_MAILBOX_IDF=1 MAIL_SUBJECT_BOOST=0.25 MAIL_COVERAGE_BOOST=2 python reranker_experiment.py --depth 150
```

The reranker experiment uses five-fold query-held-out and mailbox-held-out evaluation. Disable receipt-date parsing for this comparison so it measures the hybrid retrieval/reranking path. Its default configuration is 150 trees, five leaves, max depth 3, 30 minimum child samples, and L2 regularization 8. To retrain a model from the full public set, pass `--save-model ranker_model.txt`; evaluate held-out metrics before replacing the tracked model.

The default embedding model is `minishlab/potion-multilingual-128M`, and the search endpoint retrieves 150 lexical and 150 dense candidates by default. You can override these settings with `MAIL_EMBEDDING_MODEL` and `MAIL_CANDIDATE_DEPTH`; rebuild the vector index and ranker together when changing the embedding model or candidate depth.

## Dataset

The ZIP archive is deliberately not stored in Git. It contains pseudonymized emails, public queries, and qrels. Keep it outside the repository and never commit it.
