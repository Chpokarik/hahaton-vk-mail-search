# VK Mail Search

Hackathon prototype for finding a letter in a mailbox from a natural-language request. [Сценарий защиты](#сценарий-защиты).

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

The search engine extracts one receipt day from dates such as «20 ноября 2026», «20.11.2026», ISO dates, and relative dates such as «вчера». It intersects the selected mailbox's term index with that day's index, then ranks candidates with BM25, Russian lemmatization, a subject boost, and query-term coverage. Without a recognized receipt day, the API retrieves up to 150 candidates each from BM25 and local 128M Potion embeddings. It combines the candidates and reranks them with LightGBM. If the model or index is unavailable, search uses BM25. Query processing and inference run locally.

The public development set contains 99 queries and 565 relevance labels. The same query set was used for both rows in this table.

| Mode | Recall@10 | Recall@100 | nDCG@10 | MRR@10 |
| --- | ---: | ---: | ---: | ---: |
| BM25 baseline | 0.5239 | 0.8637 | 0.3665 | 0.3582 |
| Integrated search | 0.8879 | 0.9923 | 0.9304 | 0.9503 |

The organizers measure final quality and latency on their private benchmark. The local integrated HTTP stress test used 495 requests at each of 8, 32, and 64 concurrent clients. It completed without errors for both workloads. At 64 clients, p99 was 39.6 ms on the public queries and 736.5 ms after removing the receipt-date phrases.

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

- `GET /health` — service status, indexed document count, and whether dense retrieval and reranking loaded.
- `GET /mailboxes` — available synthetic mailboxes and message counts.
- `GET /mailboxes/{synthetic_user}/messages?offset=0&limit=50` — inbox page. Use `preview=true` for lightweight inbox previews.
- `GET /mailboxes/{synthetic_user}/messages/{doc_id}` — full message in the selected mailbox. With an older backend, the frontend retrieves it through the paginated inbox.
- `GET /search?q=...&synthetic_user=...` — simple browser-friendly search.

The frontend can call the API directly from a local development server; CORS is enabled.

## Evaluate the integrated engine

Run from `backend/` after installing the backend dependencies:

```bash
python evaluate.py --latency-repeats 5
MAIL_RECEIPT_DATES=0 python evaluate.py --mode lexical --latency-repeats 5
```

This reports Recall@10, Recall@100, nDCG@10, MRR@10, and in-process p50/p95/p99 latency for the public queries.

## Enable hybrid retrieval

Use the same archive for index generation and API startup. Install the optional dependencies, build the index once, and restart the API:

```bash
cd backend
pip install -r requirements-search-lab.txt
python build_semantic_index.py
```

The build downloads the 128M embedding model and creates `backend/.cache/semantic-index.npz`. The corpus, model weights, and generated vectors stay outside Git. On the provided archive, the index contains 25,832 text chunks. `GET /health` reports `semantic_search` and `reranker` readiness. Set `MAIL_SEMANTIC_ENABLED=0` to run date-aware BM25 without the optional model.

The included LightGBM model was trained on the public relevance labels. Reproduce the upstream experiment with receipt-date parsing disabled to compare the hybrid reranker against the original lexical baseline. The experiment trains separate models for the held-out queries and mailboxes.

```bash
MAIL_RECEIPT_DATES=0 python reranker_experiment.py --depth 150
```

Stress the running API with both the original workload and a workload with the explicit receipt-date phrases removed. The second command measures performance of the hybrid path:

```bash
python stress_http.py --workers 8 32 64 --repeats 5
python stress_http.py --workers 8 32 64 --repeats 5 --without-receipt-dates
```

## Dataset

The ZIP archive is deliberately not stored in Git. It contains pseudonymized emails, public queries, and qrels. Keep it outside the repository and never commit it.

## Сценарий защиты

### Текст на 90 секунд

**0:00–0:15. Задача.** «В почте мы помним смысл письма и когда оно пришло. Точная тема обычно забывается. Мы сделали поиск, которому можно написать: “Какие заказы пришли вчера?”»

**0:15–0:45. Живой показ.** Откройте самый большой ящик. Поставьте «Поиск до» на 21 ноября 2026 года. Введите «Какие заказы пришли вчера?». Покажите, что приложение само вычислило 20 ноября, и откройте одно из двух писем. Добавьте его в «Избранное» и покажите, как быстро к нему вернуться. Если нужно сэкономить время, нажмите готовый пример «Заказы от 20 ноября 2026».

**0:45–1:05. Как устроен поиск.** «Сначала определяем ящик и дату. Если день указан в запросе, ищем только среди полученных в этот день писем и сортируем по BM25 с русской морфологией. Если точного дня нет, объединяем результаты поиска по словам и поискового индекса на эмбеддингах, а LightGBM уточняет порядок. Обработка выполняется на сервере, прямо на машине с архивом».

**1:05–1:25. Доказательство.** «На 99 публичных запросах Recall@10 вырос с 52,4% до 88,8%, а nDCG@10 — с 0,367 до 0,930. Recall@100 достиг 99,2%. Эти цифры получили на публичных запросах с датами. Под нагрузкой в 64 клиента локальный p99 составил 40 мс на этих запросах и 737 мс на нагрузке для гибридного режима. Финальный замер проведут организаторы».

**1:25–1:30. Финал.** «Прототип работает в браузере. На ноутбуке список и письмо видны рядом, на телефоне письмо открывается во весь экран. Для показа есть HTTPS-ссылка и локальная копия».

### Что могут спросить

- **Что здесь умного?** Запрос раскладывается на тему и дату получения. «Вчера» зависит от даты отсчёта. Гибридный режим сопоставляет запрос с текстом, даже когда формулировки отличаются.
- **Откуда цифры про гибрид?** В отдельном эксперименте с удержанием целых ящиков LightGBM дал Recall@10 54,9% и nDCG@10 0,466. Сильный прирост в итоговой таблице относится к запросам, где можно выделить день. Это два разных замера.
- **Как считали скорость?** Замеряем время ответа локального HTTP API на повторяемой нагрузке. В команды выше входят исходные запросы и отдельная нагрузка для гибридного пути.
- **Почему модель разрешена?** Мультиязычная Potion содержит 128 млн параметров. Веса скачиваются при сборке индекса. Запросы и тексты обрабатываются локально.
- **Что будет без весов?** Работает BM25 с русской морфологией и определением дня. В `/health` видно, какой режим доступен.
- **Какой следующий шаг?** Расширить распознавание диапазонов дат и сделать отдельный оценочный набор для запросов без даты.
- **Пример запроса без даты.** В ящике `box-12259a301ee2` введите «Как оплатить муниципальное жильё». Гибрид выводит вверх счета за найм муниципального фонда.
