FROM node:22-bookworm

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN npm --prefix frontend ci
COPY frontend/ ./frontend/
RUN VITE_API_BASE_URL=/ VITE_DEMO_MODE=synthetic npm --prefix frontend run build

COPY backend/ ./backend/
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r backend/requirements.txt \
    && mkdir -p backend/.cache \
    && /opt/venv/bin/python backend/generate_demo_corpus.py \
    && mv /tmp/mail-demo.zip backend/.cache/mail-demo.zip

ENV PATH="/opt/venv/bin:${PATH}" \
    MAIL_DATASET_ZIP=/app/backend/.cache/mail-demo.zip \
    MAIL_SEMANTIC_ENABLED=0 \
    MAIL_SERVE_FRONTEND=1

WORKDIR /app/backend
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000}"]
