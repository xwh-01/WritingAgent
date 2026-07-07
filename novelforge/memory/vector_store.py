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

    def query(
        self,
        collection: str,
        query_text: str,
        k: int = 5,
        story_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query_vec = self._tokenize(query_text)
        scored: list[dict[str, Any]] = []
        for doc_id, (document, metadata) in self._collections.get(collection, {}).items():
            if story_id is not None and not self._belongs_to_story(doc_id, metadata, story_id):
                continue
            score = self._cosine(query_vec, self._tokenize(document))
            scored.append({"id": doc_id, "document": document, "metadata": metadata, "score": score})
        return sorted(scored, key=lambda item: item["score"], reverse=True)[:k]

    def delete_story(self, story_id: str) -> int:
        deleted = 0
        for docs in self._collections.values():
            ids = [
                doc_id
                for doc_id, (_, metadata) in docs.items()
                if str(metadata.get("story_id", "")) == story_id or doc_id.startswith(f"{story_id}:")
            ]
            for doc_id in ids:
                docs.pop(doc_id, None)
                deleted += 1
        return deleted

    def _tokenize(self, text: str) -> Counter[str]:
        return Counter(re.findall(r"[\w\u4e00-\u9fff]+", text.lower()))

    def _belongs_to_story(self, doc_id: str, metadata: dict[str, Any], story_id: str) -> bool:
        return str(metadata.get("story_id", "")) == story_id or doc_id.startswith(f"{story_id}:")

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

    def query(
        self,
        collection: str,
        query_text: str,
        k: int = 5,
        story_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if self._fallback is not None:
            return self._fallback.query(collection, query_text, k, story_id=story_id)
        coll = self.client.get_or_create_collection(collection)
        query_kwargs: dict[str, Any] = {"query_texts": [query_text], "n_results": k}
        if story_id is not None:
            query_kwargs["where"] = {"story_id": story_id}
        result = coll.query(**query_kwargs)
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

    def delete_story(self, story_id: str) -> int:
        if self._fallback is not None:
            return self._fallback.delete_story(story_id)
        deleted = 0
        collections = self.client.list_collections()
        for collection in collections:
            coll = self.client.get_or_create_collection(collection.name)
            ids: list[str] = []
            try:
                by_meta = coll.get(where={"story_id": story_id})
                ids.extend(by_meta.get("ids", []) or [])
            except Exception:
                pass
            try:
                all_items = coll.get()
                ids.extend([doc_id for doc_id in all_items.get("ids", []) if doc_id.startswith(f"{story_id}:")])
            except Exception:
                pass
            unique_ids = sorted(set(ids))
            if unique_ids:
                coll.delete(ids=unique_ids)
                deleted += len(unique_ids)
        return deleted
