"""Abstract interfaces for memory backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class IVectorStore(ABC):
    @abstractmethod
    def add(self, collection: str, documents: list[str], metadatas: list[dict[str, Any]], ids: list[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def query(self, collection: str, query_text: str, k: int = 5) -> list[dict[str, Any]]:
        raise NotImplementedError


class IGraphStore(ABC):
    @abstractmethod
    def add_node(self, node_id: str, attributes: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def add_edge(self, source: str, target: str, relation: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_ego_network(self, node_id: str, depth: int = 1) -> dict[str, Any]:
        raise NotImplementedError


class IFTSStore(ABC):
    @abstractmethod
    def index_document(self, doc_id: str, content: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[str]:
        raise NotImplementedError
