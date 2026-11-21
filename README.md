# VK Mail Search

Hackathon prototype for finding a letter in a mailbox from a natural-language request.

## Current backend

The live `/search` endpoint currently uses a local BM25 engine with Russian lemmatization (`pymorphy3`), mailbox-specific document statistics, a small subject boost, and a query-term coverage boost. It makes no model/API calls. The API contract below remains stable while retrieval experiments continue.

The public development set has 99 queries and 565 relevance labels. The current lexical configuration gets about `Recall@10=0.52`, `Recall@100=0.86`, `nDCG@10=0.37`, and `MRR@10=0.36` in the local evaluator. Results are a development signal, not a promise about the hidden benchmark.

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

This reports Recall@10, Recall@100, nDCG@10, MRR@10, and in-process p50/p95/p99 latency for the public queries.

## Optional local semantic-search experiments

Experiments use a compact multilingual embedding model on the local machine. The model weights are downloaded once during setup; query text is not sent to an inference API. The generated model cache and vector index stay under the ignored `backend/.cache/` directory and are not committed.

```bash
cd backend
pip install -r requirements-search-lab.txt
python build_semantic_index.py
MAIL_LEMMATIZE=1 MAIL_MAILBOX_IDF=1 MAIL_SUBJECT_BOOST=0.25 MAIL_COVERAGE_BOOST=2 python evaluate_dense.py
MAIL_LEMMATIZE=1 MAIL_MAILBOX_IDF=1 MAIL_SUBJECT_BOOST=0.25 MAIL_COVERAGE_BOOST=2 python reranker_experiment.py --depth 100
```

The semantic and reranker scripts are experiments for measuring candidate recall and ranking quality; the live `/search` route remains the lexical implementation until a hybrid version is integrated and verified end-to-end.

## Dataset

The ZIP archive is deliberately not stored in Git. It contains pseudonymized emails, public queries, and qrels. Keep it outside the repository and never commit it.
