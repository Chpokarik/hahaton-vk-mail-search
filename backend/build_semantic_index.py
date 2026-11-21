"""Build the local dense index once; query-time search never calls a remote API."""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Iterator

import numpy as np
from fastembed import TextEmbedding


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT.parent / "mipt_mail_search_participants.zip"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / ".cache" / "semantic-index.npz"
DEFAULT_MODEL_CACHE = Path(__file__).resolve().parent / ".cache" / "fastembed"
MODEL_NAME = os.environ.get(
    "MAIL_EMBEDDING_MODEL", "minishlab/potion-multilingual-128M"
)
WORD_RE = re.compile(r"\S+")
CHUNK_WORDS = 80
CHUNK_OVERLAP = 16


def split_chunks(text: str) -> Iterator[str]:
    words = WORD_RE.findall(text)
    if not words:
        yield ""
        return
    step = CHUNK_WORDS - CHUNK_OVERLAP
    for start in range(0, len(words), step):
        chunk = " ".join(words[start : start + CHUNK_WORDS])
        if chunk:
            yield chunk
        if start + CHUNK_WORDS >= len(words):
            break


def read_documents(archive_path: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(archive_path) as archive:
        with archive.open("documents.jsonl") as stream:
            return [json.loads(line) for line in stream]


def main() -> None:
    archive_path = Path(os.environ.get("MAIL_DATASET_ZIP", DEFAULT_ARCHIVE))
    output_path = Path(os.environ.get("MAIL_VECTOR_INDEX", DEFAULT_OUTPUT))
    model_cache = Path(os.environ.get("MAIL_MODEL_CACHE", DEFAULT_MODEL_CACHE))
    documents = read_documents(archive_path)
    chunk_ids: list[str] = []
    mailbox_ids: list[str] = []
    texts: list[str] = []
    for doc in documents:
        for chunk in split_chunks(doc.get("doc", "")):
            chunk_ids.append(doc["doc_id"])
            mailbox_ids.append(doc["synthetic_user"])
            texts.append(chunk)

    embedding_args = {"model_name": MODEL_NAME, "cache_dir": str(model_cache)}
    if not MODEL_NAME.startswith("minishlab/potion-"):
        embedding_args["threads"] = int(os.environ.get("MAIL_EMBED_THREADS", "4"))
    model = TextEmbedding(**embedding_args)
    vectors = np.asarray(list(model.embed(texts, batch_size=128)), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    vectors /= np.maximum(norms, 1e-12)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    corpus_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    np.savez_compressed(
        output_path,
        doc_ids=np.asarray(chunk_ids, dtype=str),
        mailbox_ids=np.asarray(mailbox_ids, dtype=str),
        vectors=vectors,
        model=np.asarray(MODEL_NAME),
        corpus_sha256=np.asarray(corpus_sha),
    )
    print(f"documents: {len(documents)}")
    print(f"chunks: {len(chunk_ids)}")
    print(f"dimensions: {vectors.shape[1]}")
    print(f"index: {output_path} ({output_path.stat().st_size / 1024 / 1024:.1f} MiB)")
    print(f"corpus_sha256: {corpus_sha}")


if __name__ == "__main__":
    main()
