"""
Knowledge Graph for A.R.I.S.
Inspired by mcp-memory-service. Persistent memory with typed edges and semantic search.
"""

import json
import time
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime


DATA_DIR = Path(__file__).parent.parent / "data"
GRAPH_FILE = DATA_DIR / "knowledge_graph.json"


class KnowledgeGraph:
    """Persistent knowledge graph with typed edges and search."""

    def __init__(self):
        self.nodes: Dict[str, Dict] = {}
        self.edges: List[Dict] = []
        self._load()

    def _load(self):
        """Load graph from disk."""
        if GRAPH_FILE.exists():
            try:
                with open(GRAPH_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.nodes = data.get("nodes", {})
                    self.edges = data.get("edges", [])
            except (json.JSONDecodeError, KeyError):
                pass

    def _save(self):
        """Save graph to disk."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(GRAPH_FILE, "w", encoding="utf-8") as f:
            json.dump({"nodes": self.nodes, "edges": self.edges}, f, indent=2, ensure_ascii=False)

    def _node_id(self, content: str, node_type: str = "concept") -> str:
        """Generate a deterministic node ID."""
        key = f"{node_type}:{content.lower().strip()}"
        return hashlib.md5(key.encode()).hexdigest()[:12]

    def add_node(self, content: str, node_type: str = "concept",
                 metadata: Optional[Dict] = None, tags: Optional[List[str]] = None) -> str:
        """Add a node to the graph. Returns node ID."""
        node_id = self._node_id(content, node_type)
        now = datetime.now().isoformat()

        if node_id in self.nodes:
            self.nodes[node_id]["last_accessed"] = now
            self.nodes[node_id]["access_count"] = self.nodes[node_id].get("access_count", 0) + 1
            if tags:
                existing = set(self.nodes[node_id].get("tags", []))
                existing.update(tags)
                self.nodes[node_id]["tags"] = sorted(existing)
        else:
            self.nodes[node_id] = {
                "id": node_id,
                "content": content,
                "type": node_type,
                "metadata": metadata or {},
                "tags": tags or [],
                "created": now,
                "last_accessed": now,
                "access_count": 1,
            }

        self._save()
        return node_id

    def add_edge(self, source_id: str, target_id: str, edge_type: str,
                 weight: float = 1.0, metadata: Optional[Dict] = None) -> bool:
        """Add a typed edge between two nodes."""
        if source_id not in self.nodes or target_id not in self.nodes:
            return False

        for edge in self.edges:
            if edge["source"] == source_id and edge["target"] == target_id and edge["type"] == edge_type:
                edge["weight"] = min(edge.get("weight", 1.0) + 0.1, 5.0)
                edge["last_used"] = datetime.now().isoformat()
                self._save()
                return True

        self.edges.append({
            "source": source_id,
            "target": target_id,
            "type": edge_type,
            "weight": weight,
            "metadata": metadata or {},
            "created": datetime.now().isoformat(),
            "last_used": datetime.now().isoformat(),
        })
        self._save()
        return True

    def store(self, content: str, node_type: str = "memory",
              tags: Optional[List[str]] = None,
              relationships: Optional[List[Tuple[str, str, str]]] = None) -> str:
        """Store a memory with optional relationships.

        relationships: list of (target_content, target_type, edge_type)
        """
        node_id = self.add_node(content, node_type, tags=tags)

        if relationships:
            for target_content, target_type, edge_type in relationships:
                target_id = self._node_id(target_content, target_type)
                if target_id not in self.nodes:
                    self.add_node(target_content, target_type)
                self.add_edge(node_id, target_id, edge_type)

        return node_id

    def search(self, query: str, node_type: Optional[str] = None,
               tags: Optional[List[str]] = None, limit: int = 10) -> List[Dict]:
        """Search nodes by content similarity (keyword matching)."""
        query_lower = query.lower()
        query_words = set(query_lower.split())

        results = []
        for node_id, node in self.nodes.items():
            if node_type and node.get("type") != node_type:
                continue
            if tags:
                node_tags = set(node.get("tags", []))
                if not set(tags).issubset(node_tags):
                    continue

            content_lower = node["content"].lower()
            content_words = set(content_lower.split())

            overlap = len(query_words & content_words)
            if query_lower in content_lower:
                overlap += 10
            if any(qw in content_lower for qw in query_words):
                overlap += 3

            if overlap > 0:
                score = overlap / max(len(query_words), 1)
                results.append({
                    "id": node_id,
                    "content": node["content"],
                    "type": node.get("type", "concept"),
                    "tags": node.get("tags", []),
                    "score": round(score, 3),
                    "created": node.get("created"),
                    "access_count": node.get("access_count", 0),
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def get_neighbors(self, node_id: str, edge_type: Optional[str] = None,
                      direction: str = "both") -> List[Dict]:
        """Get neighboring nodes."""
        neighbors = []
        for edge in self.edges:
            target_node = None
            if direction in ("out", "both") and edge["source"] == node_id:
                target_node = self.nodes.get(edge["target"])
            elif direction in ("in", "both") and edge["target"] == node_id:
                target_node = self.nodes.get(edge["source"])

            if target_node and (not edge_type or edge["type"] == edge_type):
                neighbors.append({
                    "node": target_node,
                    "edge_type": edge["type"],
                    "weight": edge.get("weight", 1.0),
                })

        return neighbors

    def get_stats(self) -> Dict:
        """Get graph statistics."""
        type_counts = {}
        for node in self.nodes.values():
            t = node.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

        edge_type_counts = {}
        for edge in self.edges:
            t = edge.get("type", "unknown")
            edge_type_counts[t] = edge_type_counts.get(t, 0) + 1

        return {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "node_types": type_counts,
            "edge_types": edge_type_counts,
        }

    def export_context(self, query: str, max_chars: int = 3000) -> str:
        """Export relevant context as a text block for LLM prompts."""
        results = self.search(query, limit=5)
        if not results:
            return ""

        lines = ["## Knowledge Graph Context"]
        for r in results:
            lines.append(f"- [{r['type']}] {r['content']}")
            neighbors = self.get_neighbors(r["id"], direction="out")
            for n in neighbors[:3]:
                lines.append(f"  -> [{n['edge_type']}] {n['node']['content'][:100]}")

        context = "\n".join(lines)
        if len(context) > max_chars:
            context = context[:max_chars] + "..."
        return context


_graph_instance = None


def get_knowledge_graph() -> KnowledgeGraph:
    """Get the singleton knowledge graph instance."""
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = KnowledgeGraph()
    return _graph_instance
