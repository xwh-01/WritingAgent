"""NetworkX-backed character relationship graph."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from novelforge.indexes.interfaces import IGraphStore

try:
    import networkx as nx
except Exception:  # pragma: no cover - exercised only without optional dependency
    nx = None

logger = logging.getLogger(__name__)


class NetworkXGraphStore(IGraphStore):
    """基于 NetworkX 的角色关系图存储，无 NetworkX 时自动降级为纯字典模式。"""

    def __init__(self, graph_directory: str):
        """初始化图存储目录并加载已有的关系图文件。"""
        self.graph_directory = Path(graph_directory)
        self.graph_directory.mkdir(parents=True, exist_ok=True)
        self.path = self.graph_directory / "relationships.json"
        self.graph = nx.Graph() if nx is not None else {"nodes": {}, "edges": []}
        self._load()

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _normalize_persisted_graph(self, data: object) -> dict[str, object]:
        """Convert any historical on-disk format into standard node-link output.

        Returns a dict with keys ``directed``, ``multigraph``, ``graph``,
        ``nodes`` (list of dicts, each containing at least ``"id"``), and
        ``edges`` (list of dicts, each containing at least ``"source"`` and
        ``"target"``).
        """
        if not isinstance(data, dict):
            logger.warning("Graph data on disk is not a dict; starting with empty graph.")
            return _empty_node_link()

        normalized: dict[str, object] = {
            "directed": data.get("directed", False),
            "multigraph": data.get("multigraph", False),
            "graph": data.get("graph", {}),
            "nodes": self._normalize_nodes(data.get("nodes")),
            "edges": self._normalize_edges(data.get("edges", data.get("links", []))),
        }
        return normalized

    @staticmethod
    def _normalize_nodes(raw_nodes: object) -> list[dict[str, object]]:
        """Normalize *raw_nodes* into ``[{"id": …, …}, …]``.

        Accepts a dict (old fallback ``{node_id: {attrs}}``) or a list
        (standard node-link ``[{"id": …, …}]``).
        """
        if isinstance(raw_nodes, dict):
            result: list[dict[str, object]] = []
            for node_id, attrs in raw_nodes.items():
                if isinstance(attrs, dict):
                    entry: dict[str, object] = dict(attrs)
                    entry.setdefault("id", str(node_id))
                    result.append(entry)
                else:
                    # Non-dict attribute value – keep the node with minimal info.
                    result.append({"id": str(node_id)})
            return result

        if isinstance(raw_nodes, list):
            return [item if isinstance(item, dict) else {"id": str(item)} for item in raw_nodes]

        logger.warning(
            "Graph nodes have unexpected type %s; treating as empty.", type(raw_nodes).__name__
        )
        return []

    @staticmethod
    def _normalize_edges(raw_edges: object) -> list[dict[str, object]]:
        """Normalize *raw_edges* / *links* into ``[{"source": …, "target": …, …}, …]``.

        Edges missing ``source`` or ``target`` are silently dropped.
        """
        if not isinstance(raw_edges, list):
            logger.warning(
                "Graph edges have unexpected type %s; treating as empty.", type(raw_edges).__name__
            )
            return []

        kept: list[dict[str, object]] = []
        for item in raw_edges:
            if not isinstance(item, dict):
                continue
            if "source" not in item or "target" not in item:
                continue
            kept.append(dict(item))
        return kept

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_node(self, node_id: str, attributes: dict[str, Any]) -> None:
        """向图中添加节点并保存。"""
        if nx is None:
            self.graph["nodes"][node_id] = dict(attributes)
            self.save()
            return
        self.graph.add_node(node_id, **attributes)
        self.save()

    def add_edge(self, source: str, target: str, relation: str) -> None:
        """在两个节点间添加一条带关系标签的边并保存。"""
        if nx is None:
            self.graph["edges"].append({"source": source, "target": target, "relation": relation})
            self.save()
            return
        self.graph.add_edge(source, target, relation=relation)
        self.save()

    def get_ego_network(self, node_id: str, depth: int = 1) -> dict[str, Any]:
        """返回指定节点在给定深度内的自我中心网络（节点和边）。"""
        if nx is None:
            if node_id not in self.graph["nodes"]:
                return {"nodes": {}, "edges": []}
            selected = {node_id}
            edges = []
            frontier = {node_id}
            for _ in range(depth):
                next_frontier = set()
                for edge in self.graph["edges"]:
                    if edge["source"] in frontier or edge["target"] in frontier:
                        edges.append(edge)
                        next_frontier.add(edge["source"])
                        next_frontier.add(edge["target"])
                selected |= next_frontier
                frontier = next_frontier
            return {
                "nodes": {node: self.graph["nodes"].get(node, {}) for node in selected},
                "edges": edges,
            }
        if node_id not in self.graph:
            return {"nodes": {}, "edges": []}
        nodes = nx.single_source_shortest_path_length(self.graph, node_id, cutoff=depth).keys()
        subgraph = self.graph.subgraph(nodes)
        return {
            "nodes": {node: dict(subgraph.nodes[node]) for node in subgraph.nodes},
            "edges": [
                {"source": a, "target": b, **dict(data)} for a, b, data in subgraph.edges(data=True)
            ],
        }

    def get_related_characters(self, character_id: str) -> list[dict[str, Any]]:
        """返回与指定角色直接关联的其他角色信息列表。"""
        network = self.get_ego_network(character_id, depth=1)
        return [
            {"id": node_id, **attrs}
            for node_id, attrs in network["nodes"].items()
            if node_id != character_id
        ]

    def delete_story(self, story_id: str) -> int:
        """删除图中属于指定故事的所有节点和关联边，返回删除节点数。"""
        if nx is None:
            nodes = [
                node_id
                for node_id, attrs in self.graph["nodes"].items()
                if attrs.get("story_id") == story_id or str(node_id).startswith(f"{story_id}:")
            ]
            self.graph["nodes"] = {
                node: attrs for node, attrs in self.graph["nodes"].items() if node not in nodes
            }
            self.graph["edges"] = [
                edge
                for edge in self.graph["edges"]
                if edge.get("source") not in nodes and edge.get("target") not in nodes
            ]
            if nodes:
                self.save()
            return len(nodes)
        nodes = [
            node
            for node, attrs in self.graph.nodes(data=True)
            if attrs.get("story_id") == story_id or str(node).startswith(f"{story_id}:")
        ]
        if nodes:
            self.graph.remove_nodes_from(nodes)
            self.save()
        return len(nodes)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """将当前图序列化为标准 node-link JSON 并原子写入磁盘。"""
        if nx is None:
            # Save in standard node-link format even in fallback mode.
            nodes = [{"id": node_id, **attrs} for node_id, attrs in self.graph["nodes"].items()]
            data: dict[str, object] = {
                "directed": False,
                "multigraph": False,
                "graph": {},
                "nodes": nodes,
                "edges": self.graph["edges"],
            }
        else:
            try:
                data = nx.node_link_data(self.graph, edges="edges")
            except TypeError:
                data = nx.node_link_data(self.graph)

        # Atomic write: tmp → flush → replace.
        # A unique sibling temp file keeps concurrent background jobs from
        # opening and replacing the same temporary path on Windows.
        tmp_path = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, self.path)

    def _load(self) -> None:
        """从磁盘 JSON 文件加载图，自动兼容历史格式。"""
        if not self.path.exists():
            return

        # ── Read raw file ────────────────────────────────────────────
        try:
            raw = self.path.read_text(encoding="utf-8").strip()
        except Exception:
            logger.warning("Could not read graph file %s; starting with empty graph.", self.path)
            return

        if not raw:
            logger.warning("Graph file %s is empty; starting with empty graph.", self.path)
            return

        # ── Parse JSON ───────────────────────────────────────────────
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "Graph file %s contains invalid JSON; starting with empty graph.", self.path
            )
            return

        # ── Normalize to standard node-link ──────────────────────────
        normalized = self._normalize_persisted_graph(data)

        # ── Load into the active implementation ──────────────────────
        if nx is None:
            # Convert node-link list back to internal fallback dict.
            nodes_dict: dict[str, dict[str, object]] = {}
            for item in normalized["nodes"]:
                node_id = str(item.pop("id"))
                nodes_dict[node_id] = item
            self.graph = {"nodes": nodes_dict, "edges": normalized["edges"]}
            return

        try:
            self.graph = nx.node_link_graph(normalized, edges="edges")
        except TypeError:
            # Older NetworkX uses "links" instead of "edges".
            networkx_2_data = dict(normalized)
            networkx_2_data["links"] = networkx_2_data.pop("edges", [])
            self.graph = nx.node_link_graph(networkx_2_data)


def _empty_node_link() -> dict[str, object]:
    return {
        "directed": False,
        "multigraph": False,
        "graph": {},
        "nodes": [],
        "edges": [],
    }
