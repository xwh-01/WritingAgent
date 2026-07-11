"""Abstract interfaces for memory backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class IVectorStore(ABC):
    """向量存储的抽象接口，定义增、查、删除操作。"""

    @abstractmethod
    def add(self, collection: str, documents: list[str], metadatas: list[dict[str, Any]], ids: list[str]) -> None:
        """向指定集合批量添加文档及元数据。"""
        raise NotImplementedError

    @abstractmethod
    def query(
        self,
        collection: str,
        query_text: str,
        k: int = 5,
        story_id: str | None = None,
        max_chapter: int | None = None,
    ) -> list[dict[str, Any]]:
        """语义检索，返回 Top-K 相关文档，支持按 story_id 过滤。"""
        raise NotImplementedError

    @abstractmethod
    def delete_prefix(self, collection: str, id_prefix: str) -> int:
        """删除指定集合内 ID 具有给定前缀的文档。"""
        raise NotImplementedError

    @abstractmethod
    def delete_story(self, story_id: str) -> int:
        """删除指定故事的所有向量文档，返回删除数量。"""
        raise NotImplementedError


class IGraphStore(ABC):
    """关系图存储的抽象接口，定义节点/边的增删查操作。"""

    @abstractmethod
    def add_node(self, node_id: str, attributes: dict[str, Any]) -> None:
        """添加一个节点及其属性。"""
        raise NotImplementedError

    @abstractmethod
    def add_edge(self, source: str, target: str, relation: str) -> None:
        """在两个节点间添加一条带关系标签的边。"""
        raise NotImplementedError

    @abstractmethod
    def get_ego_network(self, node_id: str, depth: int = 1) -> dict[str, Any]:
        """获取指定节点的自我中心网络，深度可配置。"""
        raise NotImplementedError

    @abstractmethod
    def delete_story(self, story_id: str) -> int:
        """删除指定故事的所有节点和关联边，返回删除节点数。"""
        raise NotImplementedError


class IFTSStore(ABC):
    """全文检索引擎的抽象接口，定义索引、搜索和删除操作。"""

    @abstractmethod
    def index_document(self, doc_id: str, content: str) -> None:
        """索引一篇文档以供后续全文检索。"""
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        query: str,
        limit: int = 10,
        story_id: str | None = None,
        max_chapter: int | None = None,
    ) -> list[str]:
        """全文搜索，返回匹配文档内容列表，支持按 story_id 过滤。"""
        raise NotImplementedError

    @abstractmethod
    def delete_prefix(self, id_prefix: str) -> int:
        """删除 ID 具有给定前缀的全文文档。"""
        raise NotImplementedError

    @abstractmethod
    def delete_story(self, story_id: str) -> int:
        """删除指定故事的所有索引文档，返回删除数量。"""
        raise NotImplementedError
