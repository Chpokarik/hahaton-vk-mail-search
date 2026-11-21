# VK Mail Search

Hackathon prototype for finding a letter in a mailbox from a natural-language request.

## Run the web demo

Start the backend using the instructions below. If the organizers’ archive is in Downloads, run the following command from `backend/` with the virtual environment activated:

```bash
MAIL_DATASET_ZIP="$HOME/Downloads/mipt_mail_search_participants.zip" uvicorn app:app --port 8000
```

In a second terminal, from the repository root, use Node.js 22.12+:

```bash
npm --prefix frontend ci
npm --prefix frontend run dev
```

Open the URL Vite prints (normally `http://localhost:5173`). For the live demo, in the largest mailbox:

1. Click «Заказы от 20 ноября 2026». The results show the day parsed from the query.
2. Set «Поиск до» to 21 November 2026 and search for «Какие заказы пришли вчера?». It resolves to the same receipt date.
3. Open a result and click the bookmark icon. Open «Избранное» to find the letter again. Bookmarks are scoped to the chosen mailbox and stored in the current browser.

The default API address is `http://localhost:8000`. To use a backend on another laptop, copy `frontend/.env.example` to `frontend/.env.local`, set `VITE_API_BASE_URL` to a reachable URL such as `http://192.168.1.10:8000`, and restart Vite. Run Uvicorn with `--host 0.0.0.0` when using a backend across the local network.

### Build for static hosting

```bash
VITE_API_BASE_URL=https://your-api.example npm --prefix frontend run build
```

Publish `frontend/dist/` to a static host such as GitHub Pages. The API needs separate hosting with HTTPS and access to the dataset archive. Vite embeds the API URL at build time.

### Serve the whole demo from one host

Build a same-origin frontend and serve it alongside the API:

```bash
VITE_API_BASE_URL=/ npm --prefix frontend run build
cd backend
MAIL_SERVE_FRONTEND=1 MAIL_DATASET_ZIP="/path/to/mipt_mail_search_participants.zip" uvicorn app:app --port 8780
```

Use port 8780 as the origin for your HTTPS host. For a temporary demo, run this in a separate terminal:

```bash
ssh -o ServerAliveInterval=30 -R 80:127.0.0.1:8780 nokey@localhost.run
```

Use the HTTPS URL printed by SSH. Keep the tunnel and Uvicorn running during the demo. The free domain can rotate. The ZIP remains on the origin machine.

## Current backend

The search engine extracts one receipt day from dates such as «20 ноября 2026», «20.11.2026», ISO dates, and relative dates such as «вчера». It intersects the selected mailbox's term index with that day's index, then ranks candidates with BM25, Russian lemmatization, a subject boost, and query-term coverage. Searches without a recognized day retain mailbox-wide retrieval. Inference runs locally without a model API.

The public development set contains 99 queries and 565 relevance labels.

| Mode | Recall@10 | Recall@100 | nDCG@10 | MRR@10 |
| --- | ---: | ---: | ---: | ---: |
| BM25 baseline | 0.5239 | 0.8637 | 0.3665 | 0.3582 |
| BM25 with receipt-date parsing | 0.8879 | 0.9923 | 0.9304 | 0.9503 |

The organizers measure final quality and latency on their private benchmark.

## Start the backend

Keep `mipt_mail_search_participants.zip` one directory above this repository, or set `MAIL_DATASET_ZIP` to another path.
Use Python 3.12 for the setup below.

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

The response contains `count`, `received_on` (the extracted receipt date or `null`), and `results` with `doc_id`, `date`, `subject`, `snippet`, and `score`. `synthetic_user` is required so results stay within the selected mailbox. `query_date` is an inclusive upper bound and the reference day for relative dates. When omitted, relative dates use the server's current day. Letters with unknown receipt dates can appear in general results, and an explicit receipt day requires a known matching date.

Other routes:

- `GET /health` — service status and indexed document count.
- `GET /mailboxes` — available synthetic mailboxes and message counts.
- `GET /mailboxes/{synthetic_user}/messages?offset=0&limit=50` — inbox page.
- `GET /mailboxes/{synthetic_user}/messages/{doc_id}` — full message in the selected mailbox. With an older backend, the frontend retrieves it through the paginated inbox.
- `GET /search?q=...&synthetic_user=...` — simple browser-friendly search.

The frontend can call the API directly from a local development server; CORS is enabled.

## Evaluate the live lexical engine

Run from `backend/` after installing the backend dependencies:

```bash
python evaluate.py --latency-repeats 5
MAIL_RECEIPT_DATES=0 python evaluate.py --latency-repeats 5
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
