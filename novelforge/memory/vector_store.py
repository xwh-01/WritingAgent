"""Chroma vector store wrapper with a lightweight fallback."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from novelforge.memory.interfaces import IVectorStore


class InMemoryVectorStore(IVectorStore):
    def __init__(self) -> None:
        self._collections: dict[str, dict[str, tuple[str, dict[str, Any]]]] = defaultdict(dict)

    def add(self, collection: str, documents: list[str], metadatas: list[dict[str, Any]], ids: list[str]) -> None:
        for doc, metadata, doc_id in zip(documents, metadatas, ids, strict=False):
            metadata = dict(metadata)
            metadata.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
            self._collections[collection][doc_id] = (doc, metadata)

    def query(self, collection: str, query_text: str, k: int = 5) -> list[dict[str, Any]]:
        query_vec = self._tokenize(query_text)
        scored: list[dict[str, Any]] = []
        for doc_id, (document, metadata) in self._collections.get(collection, {}).items():
            score = self._cosine(query_vec, self._tokenize(document))
            scored.append({"id": doc_id, "document": document, "metadata": metadata, "score": score})
        return sorted(scored, key=lambda item: item["score"], reverse=True)[:k]

    def _tokenize(self, text: str) -> Counter[str]:
        return Counter(re.findall(r"[\w\u4e00-\u9fff]+", text.lower()))

    def _cosine(self, a: Counter[str], b: Counter[str]) -> float:
        if not a or not b:
            return 0.0
        common = set(a) & set(b)
        dot = sum(a[t] * b[t] for t in common)
        norm_a = math.sqrt(sum(v * v for v in a.values()))
        norm_b = math.sqrt(sum(v * v for v in b.values()))
        return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


class ChromaVectorStore(IVectorStore):
    def __init__(self, persist_directory: str):
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        try:
            import chromadb

            self.client = chromadb.PersistentClient(path=str(self.persist_directory))
            self._fallback: InMemoryVectorStore | None = None
        except Exception:
            self.client = None
            self._fallback = InMemoryVectorStore()

    def add(self, collection: str, documents: list[str], metadatas: list[dict[str, Any]], ids: list[str]) -> None:
        if self._fallback is not None:
            self._fallback.add(collection, documents, metadatas, ids)
            return
        enriched = []
        for metadata in metadatas:
            item = dict(metadata)
            item.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
            enriched.append(item)
        coll = self.client.get_or_create_collection(collection)
        coll.upsert(documents=documents, metadatas=enriched, ids=ids)

    def query(self, collection: str, query_text: str, k: int = 5) -> list[dict[str, Any]]:
        if self._fallback is not None:
            return self._fallback.query(collection, query_text, k)
        coll = self.client.get_or_create_collection(collection)
        result = coll.query(query_texts=[query_text], n_results=k)
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0] or [0.0] * len(ids)
        return [
            {
                "id": doc_id,
                "document": doc,
                "metadata": meta or {},
                "score": 1.0 / (1.0 + distance),
            }
            for doc_id, doc, meta, distance in zip(ids, docs, metas, distances, strict=False)
        ]
