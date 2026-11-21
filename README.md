# VK Mail Search

Hackathon prototype for finding a letter in a mailbox from a natural-language request.

## Current backend

The live `/search` endpoint always has a local BM25 engine with Russian lemmatization (`pymorphy3`), mailbox-specific document statistics, a subject boost, and a query-term coverage boost. If the ignored local vector index and model cache exist, it also uses local multilingual embeddings and the included LightGBM reranker. No search request is sent to an inference API. Without the vector cache, the endpoint falls back to BM25. The API contract below remains stable while retrieval experiments continue.

The public development set has 99 queries and 565 relevance labels. The improved lexical configuration gets about `Recall@10=0.52`, `Recall@100=0.86`, `nDCG@10=0.37`, and `MRR@10=0.36`. With Potion multilingual embeddings, 150 candidates per retrieval path, and the regularized LightGBM reranker, three five-fold query-held-out splits average `Recall@10=0.57`, `Recall@100=0.86`, `nDCG@10=0.48`, and `MRR@10=0.48`. Holding out whole mailboxes gives `Recall@10=0.55`, `Recall@100=0.84`, `nDCG@10=0.47`, and `MRR@10=0.47`. These are development signals, not a promise about the hidden benchmark.

On the local hackathon machine, the HTTP stress run completed 495 requests at each concurrency level with zero errors. p99 latency was 335 ms at 8 workers, 312 ms at 16, 415 ms at 32, and 756 ms at 64. This is one development machine/run; repeat on the target deployment hardware.

## Start the backend

Keep `mipt_mail_search_participants.zip` one directory above this repository, or set `MAIL_DATASET_ZIP` to another path.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
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

The response contains `count` and `results`, each with `doc_id`, `date`, `snippet`, and `score`. `synthetic_user` is required so results stay within the selected mailbox. `query_date` excludes emails with a known later date; it may be omitted.

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

This reports Recall@10, Recall@100, nDCG@10, MRR@10, and in-process p50/p95/p99 latency for the public queries. Use `--mode lexical` for the BM25 baseline. When the full public-set reranker is loaded, active-mode scores are in-sample; use `reranker_experiment.py` for held-out quality estimates.

To load-test the running HTTP API with repeated public queries:

```bash
python stress_http.py --workers 8 16 32 64 --repeats 5
```

## Optional local semantic-search experiments

The semantic model is Potion multilingual embeddings run locally. Model weights are downloaded once during setup; query text is not sent to an inference API. The generated model cache and vector index stay under the ignored `backend/.cache/` directory and are not committed. The included `backend/ranker_model.txt` is trained on the public qrels and is used automatically when both the matching vector index and model cache exist. Install the optional search dependencies to enable the hybrid path; otherwise the API falls back to BM25.

```bash
cd backend
pip install -r requirements-search-lab.txt
python build_semantic_index.py
MAIL_LEMMATIZE=1 MAIL_MAILBOX_IDF=1 MAIL_SUBJECT_BOOST=0.25 MAIL_COVERAGE_BOOST=2 python evaluate_dense.py
MAIL_LEMMATIZE=1 MAIL_MAILBOX_IDF=1 MAIL_SUBJECT_BOOST=0.25 MAIL_COVERAGE_BOOST=2 python reranker_experiment.py --depth 100
```

The reranker experiment uses five-fold query-held-out and mailbox-held-out evaluation. To retrain a model from the full public set, pass `--save-model ranker_model.txt`; evaluate the held-out metrics before replacing the tracked model.

The default embedding model is `minishlab/potion-multilingual-128M`, and the search endpoint retrieves 150 lexical and 150 dense candidates by default. You can override these settings with `MAIL_EMBEDDING_MODEL` and `MAIL_CANDIDATE_DEPTH`; rebuild the vector index and ranker together when changing the embedding model or candidate depth.

## Dataset

The ZIP archive is deliberately not stored in Git. It contains pseudonymized emails, public queries, and qrels. Keep it outside the repository and never commit it.
