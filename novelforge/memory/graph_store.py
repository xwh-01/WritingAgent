"""NetworkX-backed character relationship graph."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novelforge.memory.interfaces import IGraphStore

try:
    import networkx as nx
except Exception:  # pragma: no cover - exercised only without optional dependency
    nx = None


class NetworkXGraphStore(IGraphStore):
    """基于 NetworkX 的角色关系图存储，无 NetworkX 时自动降级为纯字典模式。"""

    def __init__(self, graph_directory: str):
        """初始化图存储目录并加载已有的关系图文件。"""
        self.graph_directory = Path(graph_directory)
        self.graph_directory.mkdir(parents=True, exist_ok=True)
        self.path = self.graph_directory / "relationships.json"
        self.graph = nx.Graph() if nx is not None else {"nodes": {}, "edges": []}
        self._load()

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
                {"source": a, "target": b, **dict(data)}
                for a, b, data in subgraph.edges(data=True)
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
            self.graph["nodes"] = {node: attrs for node, attrs in self.graph["nodes"].items() if node not in nodes}
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

    def save(self) -> None:
        """将当前图结构序列化为 JSON 并写入磁盘。"""
        if nx is None:
            data = self.graph
        else:
            try:
                data = nx.node_link_data(self.graph, edges="edges")
            except TypeError:
                data = nx.node_link_data(self.graph)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load(self) -> None:
        """从磁盘 JSON 文件反序列化加载图结构。"""
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if nx is None:
            self.graph = data
            return
        try:
            self.graph = nx.node_link_graph(data, edges="edges")
        except TypeError:
            self.graph = nx.node_link_graph(data)
