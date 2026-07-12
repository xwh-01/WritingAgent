"""Tests for NetworkXGraphStore format migration, robustness, and atomic writes."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from novelforge.memory.graph_store import NetworkXGraphStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_graph_file(directory: Path, data: dict | str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "relationships.json"
    content = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    path.write_text(content, encoding="utf-8")
    return directory


# ---------------------------------------------------------------------------
# 1. Old fallback dict format
# ---------------------------------------------------------------------------

def test_old_fallback_dict_format_is_normalized(tmp_path: Path) -> None:
    _write_graph_file(tmp_path, {
        "nodes": {
            "a": {"name": "Alice"},
            "b": {"name": "Bob"},
        },
        "edges": [
            {"source": "a", "target": "b", "relation": "friend"},
        ],
    })

    store = NetworkXGraphStore(str(tmp_path))
    ego = store.get_ego_network("a", depth=1)

    assert "a" in ego["nodes"]
    assert "b" in ego["nodes"]
    assert len(ego["edges"]) >= 1
    assert any(e.get("relation") == "friend" for e in ego["edges"])


# ---------------------------------------------------------------------------
# 2. Standard node-link format (list-based nodes)
# ---------------------------------------------------------------------------

def test_standard_node_link_format_roundtrips(tmp_path: Path) -> None:
    import networkx as nx

    g = nx.Graph()
    g.add_node("x", name="Xavier")
    g.add_node("y", name="Yvonne")
    g.add_edge("x", "y", relation="ally")

    data = nx.node_link_data(g, edges="edges")
    _write_graph_file(tmp_path, data)

    store = NetworkXGraphStore(str(tmp_path))
    ego = store.get_ego_network("x", depth=1)

    assert "x" in ego["nodes"]
    assert "y" in ego["nodes"]
    assert ego["nodes"]["x"]["name"] == "Xavier"


# ---------------------------------------------------------------------------
# 3. Fallback mode (no NetworkX) can read standard node-link format
# ---------------------------------------------------------------------------

def test_fallback_mode_reads_standard_format(tmp_path: Path, monkeypatch) -> None:
    import networkx as nx

    g = nx.Graph()
    g.add_node("p", name="Paul")
    g.add_edge("p", "q", relation="rival")
    # Use the graph with NX first to create standard data, then disable NX.
    data = nx.node_link_data(g, edges="edges")
    _write_graph_file(tmp_path, data)

    monkeypatch.setattr("novelforge.memory.graph_store.nx", None)

    store = NetworkXGraphStore(str(tmp_path))
    assert store.graph["nodes"]["p"]["name"] == "Paul"
    assert len(store.graph["edges"]) >= 1


# ---------------------------------------------------------------------------
# 4. After loading old format, save writes standard list-based nodes
# ---------------------------------------------------------------------------

def test_old_format_saves_as_standard_after_reload(tmp_path: Path) -> None:
    _write_graph_file(tmp_path, {
        "nodes": {"hero": {"name": "Hero"}},
        "edges": [],
    })

    store = NetworkXGraphStore(str(tmp_path))
    store.add_node("sidekick", {"name": "Sidekick"})  # triggers save

    raw = (tmp_path / "relationships.json").read_text(encoding="utf-8")
    data = json.loads(raw)

    assert isinstance(data["nodes"], list), "Nodes must be a list after save"
    ids = {item.get("id") or item["id"] for item in data["nodes"]}
    assert "hero" in ids
    assert "sidekick" in ids


# ---------------------------------------------------------------------------
# 5. Corrupt / edge-case files
# ---------------------------------------------------------------------------

def test_empty_file_does_not_crash(tmp_path: Path) -> None:
    _write_graph_file(tmp_path, "")
    store = NetworkXGraphStore(str(tmp_path))
    assert store.get_ego_network("anything") == {"nodes": {}, "edges": []}


def test_invalid_json_does_not_crash(tmp_path: Path) -> None:
    _write_graph_file(tmp_path, "{invalid")
    store = NetworkXGraphStore(str(tmp_path))
    assert store.get_ego_network("anything") == {"nodes": {}, "edges": []}


def test_non_dict_root_does_not_crash(tmp_path: Path) -> None:
    _write_graph_file(tmp_path, json.dumps([1, 2, 3]))
    store = NetworkXGraphStore(str(tmp_path))
    assert store.get_ego_network("anything") == {"nodes": {}, "edges": []}


def test_malformed_nodes_does_not_crash(tmp_path: Path) -> None:
    _write_graph_file(tmp_path, {"nodes": "not-a-dict-or-list", "edges": []})
    store = NetworkXGraphStore(str(tmp_path))
    assert store.get_ego_network("anything") == {"nodes": {}, "edges": []}


def test_malformed_edges_does_not_crash(tmp_path: Path) -> None:
    _write_graph_file(tmp_path, {"nodes": [], "edges": "not-a-list"})
    store = NetworkXGraphStore(str(tmp_path))
    assert store.get_ego_network("anything") == {"nodes": {}, "edges": []}


def test_missing_file_starts_empty(tmp_path: Path) -> None:
    store = NetworkXGraphStore(str(tmp_path / "nonexistent"))
    assert store.get_ego_network("anything") == {"nodes": {}, "edges": []}


def test_edges_with_links_field(tmp_path: Path) -> None:
    """Some old formats store edges under 'links' instead of 'edges'."""
    _write_graph_file(tmp_path, {
        "nodes": [
            {"id": "a", "name": "A"},
            {"id": "b", "name": "B"},
        ],
        "links": [
            {"source": "a", "target": "b", "weight": 5},
        ],
    })
    store = NetworkXGraphStore(str(tmp_path))
    ego = store.get_ego_network("a", depth=1)
    assert "b" in ego["nodes"]


def test_edges_missing_source_are_filtered(tmp_path: Path) -> None:
    _write_graph_file(tmp_path, {
        "nodes": [{"id": "a"}, {"id": "b"}],
        "edges": [
            {"target": "b"},  # no source → dropped
            {"source": "a", "target": "b", "relation": "ok"},
        ],
    })
    store = NetworkXGraphStore(str(tmp_path))
    ego = store.get_ego_network("a", depth=1)
    assert "b" in ego["nodes"]


def test_non_dict_node_attrs_kept_with_id(tmp_path: Path) -> None:
    _write_graph_file(tmp_path, {
        "nodes": {"n1": "just-a-string"},
        "edges": [],
    })
    store = NetworkXGraphStore(str(tmp_path))
    ego = store.get_ego_network("n1", depth=1)
    assert "n1" in ego["nodes"]


# ---------------------------------------------------------------------------
# 6. Full GraphStore regression (CRUD)
# ---------------------------------------------------------------------------

def test_graph_store_full_crud(tmp_path: Path) -> None:
    store = NetworkXGraphStore(str(tmp_path))

    # add_node
    store.add_node("alice", {"name": "Alice", "story_id": "s1"})
    store.add_node("bob", {"name": "Bob", "story_id": "s1"})
    store.add_node("carol", {"name": "Carol", "story_id": "s2"})

    # add_edge
    store.add_edge("alice", "bob", "friend")

    # get_ego_network
    ego = store.get_ego_network("alice", depth=1)
    assert "alice" in ego["nodes"]
    assert "bob" in ego["nodes"]
    assert "carol" not in ego["nodes"]

    # get_related_characters
    related = store.get_related_characters("alice")
    assert any(item["id"] == "bob" for item in related)

    # delete_story
    removed = store.delete_story("s1")
    assert removed == 2  # alice + bob

    # Re-init from disk — data persists
    store2 = NetworkXGraphStore(str(tmp_path))
    ego2 = store2.get_ego_network("carol", depth=1)
    assert "carol" in ego2["nodes"]
    ego3 = store2.get_ego_network("alice", depth=1)
    assert ego3 == {"nodes": {}, "edges": []}


# ---------------------------------------------------------------------------
# 7. Atomic write — no leftover .tmp when save succeeds
# ---------------------------------------------------------------------------

def test_atomic_write_cleans_up_tmp(tmp_path: Path) -> None:
    store = NetworkXGraphStore(str(tmp_path))
    store.add_node("x", {"v": 1})
    assert not (tmp_path / "relationships.json.tmp").exists()
    assert (tmp_path / "relationships.json").exists()


def test_reinit_after_atomic_write_preserves_data(tmp_path: Path) -> None:
    store = NetworkXGraphStore(str(tmp_path))
    store.add_node("k1", {"val": 100})

    store2 = NetworkXGraphStore(str(tmp_path))
    ego = store2.get_ego_network("k1", depth=1)
    assert "k1" in ego["nodes"]
    assert ego["nodes"]["k1"]["val"] == 100
