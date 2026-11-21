# VK Mail Search

Hackathon prototype for searching a mailbox by meaning and keywords. The first backend version uses a lightweight BM25 baseline; semantic retrieval and reranking can be added behind the same API.

## Backend quick start

The dataset archive is expected one directory above this repository as `mipt_mail_search_participants.zip`. To use another location, set `MAIL_DATASET_ZIP`.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Open `http://localhost:8000/docs` for the interactive API page.

## Search API contract

`POST /search`

```json
{
  "query": "билет на поезд в Петербург",
  "synthetic_user": "box-...",
  "query_date": "2026-03-12",
  "limit": 20
}
```

`synthetic_user` is required: results are restricted to that mailbox. If `query_date` is provided, emails dated after it are excluded. `query_date` may be omitted. The response is:

```json
{
  "query": "билет на поезд в Петербург",
  "count": 1,
  "results": [
    {"doc_id": "...", "date": "2026-03-10", "snippet": "...", "score": 1.23}
  ]
}
```

`GET /health` returns the service status and indexed document count. `GET /mailboxes` lists available synthetic mailbox IDs and their message counts; `GET /mailboxes/{synthetic_user}/messages?offset=0&limit=50` provides messages for the prototype inbox. `GET /search?q=...&synthetic_user=...` is also available for quick browser integration. The interactive docs describe the exact request fields. CORS is enabled for local frontend development.

The repository intentionally does not contain the dataset archive; keep it outside Git and configure its path with `MAIL_DATASET_ZIP` if needed.
