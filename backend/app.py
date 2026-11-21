"""Minimal mail-search API and BM25 baseline for the hackathon corpus."""

from __future__ import annotations

import json
import math
import os
import re
import zipfile
from collections import Counter, defaultdict
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


TOKEN_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)
SUBJECT_RE = re.compile(r"^\s*(?:тема|subject)\s*[:：]\s*(.*)$", re.IGNORECASE | re.MULTILINE)
DEFAULT_ARCHIVE = Path(__file__).resolve().parents[2] / "mipt_mail_search_participants.zip"
USE_LEMMAS = os.environ.get("MAIL_LEMMATIZE", "1") != "0"
MAILBOX_LOCAL_IDF = os.environ.get("MAIL_MAILBOX_IDF", "1") != "0"
SUBJECT_BOOST = float(os.environ.get("MAIL_SUBJECT_BOOST", "0.25"))
COVERAGE_BOOST = float(os.environ.get("MAIL_COVERAGE_BOOST", "2"))
BM25_K1 = float(os.environ.get("MAIL_BM25_K1", "1.5"))
BM25_B = float(os.environ.get("MAIL_BM25_B", "0.75"))
STOPWORDS = {
    "а", "без", "бы", "в", "вам", "вас", "весь", "во", "вот", "все", "всего", "всех", "вы",
    "где", "да", "для", "до", "его", "ее", "если", "есть", "еще", "же", "за", "и", "из",
    "или", "им", "их", "к", "как", "ко", "когда", "кто", "ли", "мне", "мы", "на", "над",
    "нам", "нас", "не", "него", "нее", "нет", "ни", "них", "но", "ну", "о", "об", "один",
    "он", "она", "они", "оно", "от", "по", "под", "при", "про", "с", "со", "так", "такой",
    "там", "те", "тем", "то", "того", "тоже", "той", "только", "том", "ты", "у", "уже", "хотя",
    "чего", "чем", "что", "чтобы", "эта", "эти", "это", "я",
}


@lru_cache(maxsize=250_000)
def normalize_token(token: str) -> str:
    token = token.lower().replace("ё", "е")
    if not USE_LEMMAS or not CYRILLIC_RE.search(token):
        return token
    # Lazy import keeps the baseline usable without optional morphology packages.
    global _morph
    if _morph is None:
        from pymorphy3 import MorphAnalyzer

        _morph = MorphAnalyzer()
    return _morph.parse(token)[0].normal_form


_morph: Any = None


def tokenize(text: str) -> list[str]:
    return [normalize_token(token) for token in TOKEN_RE.findall(text)]


def read_documents() -> list[dict[str, Any]]:
    archive = Path(os.environ.get("MAIL_DATASET_ZIP", DEFAULT_ARCHIVE))
    if not archive.is_file():
        raise RuntimeError(
            f"Dataset archive not found at {archive}. Set MAIL_DATASET_ZIP to its path."
        )
    with zipfile.ZipFile(archive) as zf:
        with zf.open("documents.jsonl") as stream:
            return [json.loads(line) for line in stream]


class MailSearch:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.by_id = {doc["doc_id"]: doc for doc in documents}
        self.lengths: dict[str, int] = {}
        self.term_freqs: dict[str, Counter[str]] = {}
        self.subject_freqs: dict[str, Counter[str]] = {}
        self.postings: dict[str, set[str]] = defaultdict(set)
        self.mailbox_postings: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        self.mailbox_doc_counts: Counter[str] = Counter()
        self.mailbox_length_sums: Counter[str] = Counter()
        for doc in documents:
            tokens = tokenize(doc.get("doc", ""))
            doc_id = doc["doc_id"]
            mailbox = doc["synthetic_user"]
            self.lengths[doc_id] = len(tokens)
            self.mailbox_doc_counts[mailbox] += 1
            self.mailbox_length_sums[mailbox] += len(tokens)
            freqs = Counter(tokens)
            self.term_freqs[doc_id] = freqs
            subject_match = SUBJECT_RE.search(doc.get("doc", ""))
            self.subject_freqs[doc_id] = Counter(tokenize(subject_match.group(1))) if subject_match else Counter()
            for term in freqs:
                self.postings[term].add(doc_id)
                self.mailbox_postings[mailbox][term].add(doc_id)
        self.avg_len = sum(self.lengths.values()) / max(1, len(self.lengths))
        self.mailbox_avg_len = {
            mailbox: self.mailbox_length_sums[mailbox] / count
            for mailbox, count in self.mailbox_doc_counts.items()
        }

    def search(self, query: str, mailbox: str, as_of: date | None, limit: int) -> list[dict[str, Any]]:
        terms = tokenize(query)
        if not terms:
            return []
        coverage_terms = set(terms) - STOPWORDS
        candidate_ids: set[str] = set()
        mailbox_index = self.mailbox_postings.get(mailbox, {})
        for term in set(terms):
            candidate_ids.update(mailbox_index.get(term, ()))

        n_docs = self.mailbox_doc_counts.get(mailbox, 0) if MAILBOX_LOCAL_IDF else len(self.documents)
        avg_len = self.mailbox_avg_len.get(mailbox, self.avg_len) if MAILBOX_LOCAL_IDF else self.avg_len
        k1, b = BM25_K1, BM25_B
        scored: list[tuple[float, dict[str, Any]]] = []
        for doc_id in candidate_ids:
            doc = self.by_id[doc_id]
            raw_date = doc.get("doc_dt")
            if as_of is not None and raw_date:
                try:
                    if date.fromisoformat(raw_date) > as_of:
                        continue
                except ValueError:
                    pass
            freqs = self.term_freqs[doc_id]
            length = self.lengths[doc_id]
            score = 0.0
            for term in terms:
                tf = freqs.get(term, 0)
                if not tf:
                    continue
                df = len(mailbox_index.get(term, ())) if MAILBOX_LOCAL_IDF else len(self.postings.get(term, ()))
                idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                denom = tf + k1 * (1 - b + b * length / max(avg_len, 1))
                score += idf * tf * (k1 + 1) / denom
                if SUBJECT_BOOST:
                    subject_tf = self.subject_freqs[doc_id].get(term, 0)
                    if subject_tf:
                        subject_denom = subject_tf + k1 * (1 - b + b * 8 / 12)
                        subject_score = idf * subject_tf * (k1 + 1) / subject_denom
                        score += SUBJECT_BOOST * subject_score
            if COVERAGE_BOOST and coverage_terms:
                covered = sum(1 for term in coverage_terms if freqs.get(term, 0))
                score *= 1 + COVERAGE_BOOST * covered / len(coverage_terms)
            if score:
                scored.append((score, doc))

        scored.sort(key=lambda item: (-item[0], item[1]["doc_id"]))
        return [
            {
                "doc_id": doc["doc_id"],
                "date": doc.get("doc_dt"),
                "snippet": doc.get("doc", "")[:500],
                "score": round(score, 6),
            }
            for score, doc in scored[:limit]
        ]


app = FastAPI(title="VK Mail Search", version="0.1.0")
search_engine = MailSearch(read_documents())
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    synthetic_user: str = Field(min_length=1)
    query_date: date | None = None
    limit: int = Field(default=20, ge=1, le=100)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "documents": len(search_engine.documents)}


@app.get("/mailboxes")
def mailboxes() -> dict[str, Any]:
    counts = Counter(doc["synthetic_user"] for doc in search_engine.documents)
    return {"mailboxes": [{"synthetic_user": user, "count": count} for user, count in sorted(counts.items())]}


@app.get("/mailboxes/{synthetic_user}/messages")
def messages(
    synthetic_user: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    mailbox_docs = [doc for doc in search_engine.documents if doc["synthetic_user"] == synthetic_user]
    if not mailbox_docs:
        raise HTTPException(status_code=404, detail="Unknown mailbox")
    mailbox_docs.sort(key=lambda doc: doc.get("doc_dt") or "", reverse=True)
    page = mailbox_docs[offset : offset + limit]
    return {
        "synthetic_user": synthetic_user,
        "total": len(mailbox_docs),
        "messages": [
            {"doc_id": doc["doc_id"], "date": doc.get("doc_dt"), "text": doc.get("doc", "")}
            for doc in page
        ],
    }


@app.post("/search")
def search(request: SearchRequest) -> dict[str, Any]:
    if not any(doc["synthetic_user"] == request.synthetic_user for doc in search_engine.documents):
        raise HTTPException(status_code=404, detail="Unknown mailbox")
    results = search_engine.search(
        request.query, request.synthetic_user, request.query_date, request.limit
    )
    return {"query": request.query, "results": results, "count": len(results)}


@app.get("/search")
def search_get(
    q: str = Query(min_length=1, max_length=1000),
    synthetic_user: str = Query(min_length=1),
    query_date: date | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    return search(SearchRequest(query=q, synthetic_user=synthetic_user, query_date=query_date, limit=limit))
