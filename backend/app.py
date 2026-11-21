"""Minimal mail-search API and BM25 baseline for the hackathon corpus."""

from __future__ import annotations

import json
import math
import os
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

# Dense mail vectors are small enough that one BLAS thread per request avoids
# oversubscribing the CPU when many searches arrive at once.
os.environ.setdefault("OPENBLAS_NUM_THREADS", os.environ.get("MAIL_BLAS_THREADS", "1"))
os.environ.setdefault("OMP_NUM_THREADS", os.environ.get("MAIL_OMP_THREADS", "1"))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field

from query_dates import ReceiptQuery, parse_receipt_query
from receipt_ranking import ReceiptRanker


TOKEN_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)
SUBJECT_RE = re.compile(r"^\s*(?:тема|subject)\s*[:：]\s*(.*)$", re.IGNORECASE | re.MULTILINE)
DEFAULT_ARCHIVE = Path(__file__).resolve().parents[2] / "mipt_mail_search_participants.zip"
USE_LEMMAS = os.environ.get("MAIL_LEMMATIZE", "1") != "0"
MAILBOX_LOCAL_IDF = os.environ.get("MAIL_MAILBOX_IDF", "1") != "0"
SUBJECT_BOOST = float(os.environ.get("MAIL_SUBJECT_BOOST", "0.25"))
COVERAGE_BOOST = float(os.environ.get("MAIL_COVERAGE_BOOST", "2"))
USE_RECEIPT_DATES = os.environ.get("MAIL_RECEIPT_DATES", "1") != "0"
USE_RECEIPT_RERANK = os.environ.get("MAIL_RECEIPT_RERANK", "1") != "0"
BM25_K1 = float(os.environ.get("MAIL_BM25_K1", "1.5"))
BM25_B = float(os.environ.get("MAIL_BM25_B", "0.75"))
SEMANTIC_MODEL = os.environ.get(
    "MAIL_EMBEDDING_MODEL", "minishlab/potion-multilingual-128M"
)
VECTOR_INDEX_PATH = Path(os.environ.get("MAIL_VECTOR_INDEX", Path(__file__).resolve().parent / ".cache" / "semantic-index.npz"))
MODEL_CACHE_PATH = Path(os.environ.get("MAIL_MODEL_CACHE", Path(__file__).resolve().parent / ".cache" / "fastembed"))
RANKER_PATH = Path(os.environ.get("MAIL_RANKER_PATH", Path(__file__).resolve().parent / "ranker_model.txt"))
CANDIDATE_DEPTH = int(os.environ.get("MAIL_CANDIDATE_DEPTH", "150"))
SEMANTIC_ENABLED = os.environ.get("MAIL_SEMANTIC_ENABLED", "1") != "0"
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


@dataclass(frozen=True)
class DenseMailbox:
    doc_ids: Any
    vectors: Any
    chunk_to_doc: Any
    receipt_ordinals: Any


class MailSearch:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.by_id = {doc["doc_id"]: doc for doc in documents}
        self.lengths: dict[str, int] = {}
        self.token_sequences: dict[str, tuple[str, ...]] = {}
        self.mailbox_documents: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.term_freqs: dict[str, Counter[str]] = {}
        self.subject_freqs: dict[str, Counter[str]] = {}
        self.postings: dict[str, set[str]] = defaultdict(set)
        self.mailbox_postings: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        self.receipt_dates: dict[str, date] = {}
        self.mailbox_days: dict[tuple[str, date], set[str]] = defaultdict(set)
        self.mailbox_doc_counts: Counter[str] = Counter()
        self.mailbox_length_sums: Counter[str] = Counter()
        for doc in documents:
            tokens = tokenize(doc.get("doc", ""))
            doc_id = doc["doc_id"]
            mailbox = doc["synthetic_user"]
            self.mailbox_documents[mailbox].append(doc)
            self.token_sequences[doc_id] = tuple(tokens)
            raw_date = doc.get("doc_dt")
            if raw_date:
                try:
                    receipt_date = date.fromisoformat(raw_date)
                except ValueError:
                    pass
                else:
                    self.receipt_dates[doc_id] = receipt_date
                    self.mailbox_days[mailbox, receipt_date].add(doc_id)
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
        for mailbox_docs in self.mailbox_documents.values():
            mailbox_docs.sort(key=lambda doc: doc.get("doc_dt") or "", reverse=True)
        self.avg_len = sum(self.lengths.values()) / max(1, len(self.lengths))
        self.mailbox_avg_len = {
            mailbox: self.mailbox_length_sums[mailbox] / count
            for mailbox, count in self.mailbox_doc_counts.items()
        }

        self.dense_model: Any = None
        self.dense_by_mailbox: dict[str, DenseMailbox] = {}
        self.ranker: Any = None
        self._load_optional_rerankers()

    def _load_optional_rerankers(self) -> None:
        if not SEMANTIC_ENABLED or not VECTOR_INDEX_PATH.is_file():
            return
        if not list(MODEL_CACHE_PATH.glob("models--*/snapshots/*")):
            return
        try:
            import numpy as np
            from fastembed import TextEmbedding

            with np.load(VECTOR_INDEX_PATH, allow_pickle=False) as index:
                if "model" in index.files and str(index["model"]) != SEMANTIC_MODEL:
                    print("Dense retrieval disabled: vector index was built with a different model")
                    return
                doc_ids = index["doc_ids"].astype(str, copy=False)
                vectors = index["vectors"].astype(np.float32, copy=False)
                mailbox_ids = index["mailbox_ids"].astype(str, copy=False)
            if (
                vectors.ndim != 2
                or vectors.shape[0] != len(doc_ids)
                or mailbox_ids.shape != doc_ids.shape
                or set(doc_ids) != set(self.by_id)
            ):
                print("Dense retrieval disabled: vector index does not match the current corpus")
                return
            if any(self.by_id[doc_id]["synthetic_user"] != mailbox for doc_id, mailbox in zip(doc_ids, mailbox_ids)):
                print("Dense retrieval disabled: vector index mailbox assignments do not match the corpus")
                return

            ordinals = {doc_id: day.toordinal() for doc_id, day in self.receipt_dates.items()}
            for mailbox in self.mailbox_doc_counts:
                indices = np.flatnonzero(mailbox_ids == mailbox)
                unique_ids, chunk_to_doc = np.unique(doc_ids[indices], return_inverse=True)
                self.dense_by_mailbox[mailbox] = DenseMailbox(
                    doc_ids=unique_ids,
                    vectors=vectors[indices],
                    chunk_to_doc=chunk_to_doc,
                    receipt_ordinals=np.asarray([ordinals.get(doc_id, 0) for doc_id in unique_ids]),
                )
            embedding_args = {
                "model_name": SEMANTIC_MODEL,
                "cache_dir": str(MODEL_CACHE_PATH),
                "local_files_only": True,
            }
            if not SEMANTIC_MODEL.startswith("minishlab/potion-"):
                embedding_args["threads"] = int(os.environ.get("MAIL_QUERY_EMBED_THREADS", "1"))
            self.dense_model = TextEmbedding(**embedding_args)
            if RANKER_PATH.is_file():
                try:
                    import lightgbm as lgb

                    self.ranker = lgb.Booster(model_file=str(RANKER_PATH))
                    print(f"LightGBM reranker active ({RANKER_PATH.name})")
                except Exception as exc:
                    print(f"Dense retrieval active without LightGBM ({type(exc).__name__})")
            print(f"Dense retrieval active ({len(doc_ids)} text chunks)")
        except Exception as exc:
            # A missing/corrupt optional cache must not stop the lexical API from starting.
            print(f"Dense retrieval disabled ({type(exc).__name__})")

    def search_lexical(
        self,
        query: str,
        mailbox: str,
        as_of: date | None,
        limit: int,
        *,
        rerank_receipt_day: bool = True,
    ) -> list[dict[str, Any]]:
        receipt = self.parse_query(query, as_of)
        if as_of and receipt.day and receipt.day > as_of:
            return []

        terms = tokenize(receipt.text)
        if receipt.day:
            terms = [term for term in terms if term not in STOPWORDS or term in {"не", "нет"}]
        if not terms and receipt.day is None:
            return []

        coverage_terms = set(terms) - STOPWORDS
        candidate_ids: set[str] = set()
        mailbox_index = self.mailbox_postings.get(mailbox, {})
        received_that_day: set[str] = set()
        if receipt.day is None:
            for term in set(terms):
                candidate_ids.update(mailbox_index.get(term, ()))
        else:
            received_that_day = self.mailbox_days.get((mailbox, receipt.day), set())
            for term in set(terms):
                candidate_ids.update(received_that_day.intersection(mailbox_index.get(term, ())))
            if not terms:
                candidate_ids = received_that_day

        n_docs = self.mailbox_doc_counts.get(mailbox, 0) if MAILBOX_LOCAL_IDF else len(self.documents)
        avg_len = self.mailbox_avg_len.get(mailbox, self.avg_len) if MAILBOX_LOCAL_IDF else self.avg_len
        k1, b = BM25_K1, BM25_B
        frequencies = mailbox_index if MAILBOX_LOCAL_IDF else self.postings
        idfs = {}
        for term in set(terms):
            df = len(frequencies.get(term, ()))
            idfs[term] = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
        scored: list[tuple[float, dict[str, Any]]] = []
        for doc_id in candidate_ids:
            doc = self.by_id[doc_id]
            doc_date = self.receipt_dates.get(doc_id)
            if as_of is not None and doc_date is not None and doc_date > as_of:
                continue
            freqs = self.term_freqs[doc_id]
            length = self.lengths[doc_id]
            score = 0.0
            for term in terms:
                tf = freqs.get(term, 0)
                if not tf:
                    continue
                idf = idfs[term]
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
            if score or not terms:
                scored.append((score, doc))

        if rerank_receipt_day and USE_RECEIPT_RERANK and received_that_day and terms:
            ranker = ReceiptRanker(terms, STOPWORDS)
            if ranker.terms:
                scored = self._rerank_receipts(scored, received_that_day, ranker)

        scored.sort(key=lambda item: (-item[0], item[1]["doc_id"]))
        return [self.result(doc, score) for score, doc in scored[:limit]]

    def _rerank_receipts(
        self,
        scored: list[tuple[float, dict[str, Any]]],
        received: set[str],
        ranker: ReceiptRanker,
    ) -> list[tuple[float, dict[str, Any]]]:
        max_lexical = max((score for score, _ in scored), default=0) or 1
        lexical_scores = {doc["doc_id"]: score / max_lexical for score, doc in scored}
        ranked = []
        for doc_id in received:
            score = ranker.score(
                self.token_sequences[doc_id],
                self.subject_freqs[doc_id],
                lexical_scores.get(doc_id),
            )
            if score is not None:
                ranked.append((score, self.by_id[doc_id]))
        return ranked

    @staticmethod
    def result(doc: dict[str, Any], score: float) -> dict[str, Any]:
        text = doc.get("doc", "")
        subject = SUBJECT_RE.search(text)
        return {
            "doc_id": doc["doc_id"],
            "date": doc.get("doc_dt"),
            "subject": subject.group(1).strip() if subject else None,
            "snippet": text[:500],
            "score": round(score, 6),
        }

    @staticmethod
    def parse_query(query: str, as_of: date | None) -> ReceiptQuery:
        return parse_receipt_query(query, as_of) if USE_RECEIPT_DATES else ReceiptQuery(query)

    def _dense_search(
        self,
        query: str,
        mailbox: str,
        as_of: date | None,
        limit: int,
        received_on: date | None = None,
    ) -> tuple[list[str], dict[str, float]]:
        mailbox_index = self.dense_by_mailbox.get(mailbox)
        if self.dense_model is None or mailbox_index is None:
            return [], {}
        import numpy as np

        qvec = np.asarray(next(self.dense_model.query_embed(query)), dtype=np.float32)
        qvec /= max(float(np.linalg.norm(qvec)), 1e-12)
        doc_ids = mailbox_index.doc_ids
        receipt_ordinals = mailbox_index.receipt_ordinals
        eligible = np.ones(len(doc_ids), dtype=np.bool_)
        if received_on is not None:
            eligible &= receipt_ordinals == received_on.toordinal()
        if as_of is not None:
            eligible &= (receipt_ordinals == 0) | (receipt_ordinals <= as_of.toordinal())
        if not np.any(eligible):
            return [], {}
        chunk_eligible = eligible[mailbox_index.chunk_to_doc]
        if not np.any(chunk_eligible):
            return [], {}
        chunk_to_doc = mailbox_index.chunk_to_doc[chunk_eligible]
        chunk_scores = mailbox_index.vectors[chunk_eligible] @ qvec
        best_by_doc = np.full(len(doc_ids), -np.inf, dtype=np.float32)
        np.maximum.at(best_by_doc, chunk_to_doc, chunk_scores)
        doc_ids = doc_ids[eligible]
        best_by_doc = best_by_doc[eligible]
        # Doc IDs are already sorted; stable ordering preserves the existing tie break.
        ranked = np.argsort(-best_by_doc, kind="stable")[:limit]
        return doc_ids[ranked].tolist(), dict(zip(doc_ids.tolist(), best_by_doc.tolist()))

    def search(self, query: str, mailbox: str, as_of: date | None, limit: int) -> list[dict[str, Any]]:
        receipt = self.parse_query(query, as_of)
        if as_of is not None and receipt.day is not None and receipt.day > as_of:
            return []
        if self.dense_model is None:
            return self.search_lexical(query, mailbox, as_of, limit)
        if not TOKEN_RE.search(query):
            return []

        # Keep the user's natural-language topic while restricting both
        # retrieval paths to the exact requested receipt day.
        retrieval_query = receipt.text if receipt.day is not None else query
        depth = max(CANDIDATE_DEPTH, limit)
        lexical = self.search_lexical(
            query,
            mailbox,
            as_of,
            depth,
            rerank_receipt_day=receipt.day is None,
        )
        dense_ids, dense_scores = self._dense_search(
            retrieval_query, mailbox, as_of, depth, received_on=receipt.day
        )
        lexical_by_id = {row["doc_id"]: row for row in lexical}
        lexical_ranks = {row["doc_id"]: rank for rank, row in enumerate(lexical, 1)}
        dense_ranks = {doc_id: rank for rank, doc_id in enumerate(dense_ids, 1)}
        candidate_ids = sorted(set(lexical_by_id) | set(dense_ids))
        if not candidate_ids:
            return []

        if self.ranker is not None:
            import numpy as np
            from search_features import CandidateFeatures

            features = CandidateFeatures(self, mailbox, tokenize(retrieval_query), STOPWORDS, depth)
            feature_rows = [
                features.for_document(
                    doc_id,
                    lexical_score=lexical_by_id.get(doc_id, {}).get("score", 0.0),
                    lexical_rank=lexical_ranks.get(doc_id, 0),
                    dense_score=dense_scores.get(doc_id, 0.0),
                    dense_rank=dense_ranks.get(doc_id, 0),
                )
                for doc_id in candidate_ids
            ]
            scores = self.ranker.predict(
                np.asarray(feature_rows, dtype=np.float32),
                num_threads=int(os.environ.get("MAIL_RANKER_THREADS", "1")),
            )
            ranked = sorted(zip(candidate_ids, scores), key=lambda item: (-float(item[1]), item[0]))
        else:
            fused: dict[str, float] = defaultdict(float)
            for rank, doc_id in enumerate(lexical_by_id, 1):
                fused[doc_id] += 1 / (60 + rank)
            for rank, doc_id in enumerate(dense_ids, 1):
                fused[doc_id] += 0.1 / (60 + rank)
            ranked = sorted(fused.items(), key=lambda item: (-item[1], item[0]))

        if receipt.day is not None and USE_RECEIPT_RERANK and receipt.text.strip():
            raw_max = max((row["score"] for row in lexical), default=0.0) or 1.0
            receipt_ranker = ReceiptRanker(tokenize(retrieval_query), STOPWORDS)
            receipt_scores = {
                doc_id: score
                for doc_id in candidate_ids
                if (score := receipt_ranker.score(
                    self.token_sequences[doc_id],
                    self.subject_freqs[doc_id],
                    lexical_by_id.get(doc_id, {}).get("score", 0.0) / raw_max
                    if doc_id in lexical_by_id else None,
                )) is not None
            }
            receipt_rank = {
                doc_id: rank
                for rank, doc_id in enumerate(
                    sorted(receipt_scores, key=lambda doc_id: (-receipt_scores[doc_id], doc_id)), 1
                )
            }
            hybrid_rank = {doc_id: rank for rank, (doc_id, _) in enumerate(ranked, 1)}
            combined_scores = {
                doc_id: (10.0 / (60 + receipt_rank[doc_id]) if doc_id in receipt_rank else 0.0)
                + 0.1 / (60 + hybrid_rank[doc_id])
                for doc_id in candidate_ids
            }
            ranked_ids = sorted(candidate_ids, key=lambda doc_id: (-combined_scores[doc_id], doc_id))
            ranked = [(doc_id, combined_scores[doc_id]) for doc_id in ranked_ids]

        return [self.result(self.by_id[doc_id], float(score)) for doc_id, score in ranked[:limit]]


app = FastAPI(title="VK Mail Search", version="0.1.0")
search_engine = MailSearch(read_documents())
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=4)
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
    return {
        "status": "ok",
        "documents": len(search_engine.documents),
        "semantic_search": search_engine.dense_model is not None,
        "reranker": search_engine.ranker is not None,
        "receipt_reranking": USE_RECEIPT_DATES and USE_RECEIPT_RERANK,
    }


@app.get("/mailboxes")
def mailboxes() -> dict[str, Any]:
    counts = search_engine.mailbox_doc_counts
    return {"mailboxes": [{"synthetic_user": user, "count": count} for user, count in sorted(counts.items())]}


@app.get("/mailboxes/{synthetic_user}/messages")
def messages(
    synthetic_user: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    preview: bool = False,
) -> dict[str, Any]:
    mailbox_docs = search_engine.mailbox_documents.get(synthetic_user)
    if not mailbox_docs:
        raise HTTPException(status_code=404, detail="Unknown mailbox")
    page = mailbox_docs[offset : offset + limit]
    if preview:
        messages = []
        for doc in page:
            summary = search_engine.result(doc, 0)
            summary.pop("score")
            summary["snippet"] = summary["snippet"][:280]
            messages.append(summary)
    else:
        messages = [
            {"doc_id": doc["doc_id"], "date": doc.get("doc_dt"), "text": doc.get("doc", "")}
            for doc in page
        ]
    return {"synthetic_user": synthetic_user, "total": len(mailbox_docs), "messages": messages}


@app.get("/mailboxes/{synthetic_user}/messages/{doc_id}")
def message(synthetic_user: str, doc_id: str) -> dict[str, Any]:
    doc = search_engine.by_id.get(doc_id)
    if doc is None or doc["synthetic_user"] != synthetic_user:
        raise HTTPException(status_code=404, detail="Unknown message")
    return {"doc_id": doc_id, "date": doc.get("doc_dt"), "text": doc.get("doc", "")}


@app.post("/search")
def search(request: SearchRequest) -> dict[str, Any]:
    if request.synthetic_user not in search_engine.mailbox_doc_counts:
        raise HTTPException(status_code=404, detail="Unknown mailbox")
    results = search_engine.search(
        request.query, request.synthetic_user, request.query_date, request.limit
    )
    receipt = search_engine.parse_query(request.query, request.query_date)
    return {
        "query": request.query, "received_on": receipt.day, "results": results, "count": len(results)
    }


@app.get("/search")
def search_get(
    q: str = Query(min_length=1, max_length=1000),
    synthetic_user: str = Query(min_length=1),
    query_date: date | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    return search(SearchRequest(query=q, synthetic_user=synthetic_user, query_date=query_date, limit=limit))


if os.environ.get("MAIL_SERVE_FRONTEND") == "1":
    from fastapi.staticfiles import StaticFiles

    dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
