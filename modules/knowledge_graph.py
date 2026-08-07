"""Knowledge Graph - Memória Avançada do J.A.R.V.I.S.

Sistema de grafos de conhecimento: entidades, fatos, relacionamentos.
Inspirado em isair/jarvis e vierisid/jarvis.
"""

import json
import re
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class Entity:
    """Uma entidade no grafo de conhecimento."""
    id: str
    name: str
    entity_type: str  # pessoa, lugar, projeto, conceito, dispositivo
    properties: dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_accessed: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class Relation:
    """Um relacionamento entre entidades."""
    id: str
    source_id: str
    target_id: str
    relation_type: str  # trabalha_em, gosta_de, usa, criou, pertence_a
    properties: dict = field(default_factory=dict)
    weight: float = 1.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class Fact:
    """Um fato sobre uma entidade."""
    id: str
    entity_id: str
    content: str
    source: str = "conversation"
    confidence: float = 1.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class KnowledgeGraph:
    """Grafo de conhecimento persistente."""

    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._entities: dict[str, Entity] = {}
        self._relations: dict[str, Relation] = {}
        self._facts: dict[str, Fact] = {}
        self._entity_index: dict[str, list[str]] = {}  # nome -> ids
        self._counter = 0

        self._load()

    def _load(self) -> None:
        """Carrega o grafo do disco."""
        graph_file = self._data_dir / "knowledge_graph.json"
        if graph_file.exists():
            try:
                data = json.loads(graph_file.read_text(encoding="utf-8"))
                for e in data.get("entities", []):
                    entity = Entity(**e)
                    self._entities[entity.id] = entity
                for r in data.get("relations", []):
                    relation = Relation(**r)
                    self._relations[relation.id] = relation
                for f in data.get("facts", []):
                    fact = Fact(**f)
                    self._facts[fact.id] = fact
                self._counter = data.get("counter", 0)
                self._rebuild_index()
            except Exception:
                pass

    def _save(self) -> None:
        """Salva o grafo no disco."""
        graph_file = self._data_dir / "knowledge_graph.json"
        data = {
            "entities": [asdict(e) for e in self._entities.values()],
            "relations": [asdict(r) for r in self._relations.values()],
            "facts": [asdict(f) for f in self._facts.values()],
            "counter": self._counter,
        }
        graph_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _rebuild_index(self) -> None:
        """Reconstrói o índice de nomes."""
        self._entity_index.clear()
        for eid, entity in self._entities.items():
            name_lower = entity.name.lower()
            if name_lower not in self._entity_index:
                self._entity_index[name_lower] = []
            self._entity_index[name_lower].append(eid)

    def _next_id(self, prefix: str) -> str:
        """Gera o próximo ID."""
        self._counter += 1
        return f"{prefix}_{self._counter}"

    # ── Entidades ──────────────────────────────────────────

    def add_entity(
        self,
        name: str,
        entity_type: str,
        properties: Optional[dict] = None,
    ) -> Entity:
        """Adiciona uma entidade ao grafo."""
        # Verificar se já existe
        name_lower = name.lower()
        if name_lower in self._entity_index:
            eid = self._entity_index[name_lower][0]
            entity = self._entities[eid]
            entity.last_accessed = datetime.now().isoformat()
            if properties:
                entity.properties.update(properties)
            self._save()
            return entity

        entity = Entity(
            id=self._next_id("ent"),
            name=name,
            entity_type=entity_type,
            properties=properties or {},
        )
        self._entities[entity.id] = entity
        if name_lower not in self._entity_index:
            self._entity_index[name_lower] = []
        self._entity_index[name_lower].append(entity.id)
        self._save()
        return entity

    def get_entity(self, name: str) -> Optional[Entity]:
        """Busca uma entidade pelo nome."""
        name_lower = name.lower()
        ids = self._entity_index.get(name_lower, [])
        if ids:
            entity = self._entities[ids[0]]
            entity.last_accessed = datetime.now().isoformat()
            return entity
        return None

    def search_entities(self, query: str, limit: int = 10) -> list[Entity]:
        """Busca entidades por similaridade de nome."""
        query_lower = query.lower()
        results = []
        for name, ids in self._entity_index.items():
            if query_lower in name or name in query_lower:
                for eid in ids:
                    results.append(self._entities[eid])
                    if len(results) >= limit:
                        return results
        return results

    def get_entities_by_type(self, entity_type: str) -> list[Entity]:
        """Retorna entidades de um tipo específico."""
        return [e for e in self._entities.values() if e.entity_type == entity_type]

    # ── Relacionamentos ────────────────────────────────────

    def add_relation(
        self,
        source_name: str,
        target_name: str,
        relation_type: str,
        properties: Optional[dict] = None,
    ) -> Optional[Relation]:
        """Adiciona um relacionamento entre duas entidades."""
        source = self.get_entity(source_name)
        target = self.get_entity(target_name)

        if not source or not target:
            return None

        relation = Relation(
            id=self._next_id("rel"),
            source_id=source.id,
            target_id=target.id,
            relation_type=relation_type,
            properties=properties or {},
        )
        self._relations[relation.id] = relation
        self._save()
        return relation

    def get_relations_from(self, entity_name: str) -> list[dict]:
        """Retorna todos os relacionamentos saindo de uma entidade."""
        entity = self.get_entity(entity_name)
        if not entity:
            return []

        results = []
        for rel in self._relations.values():
            if rel.source_id == entity.id:
                target = self._entities.get(rel.target_id)
                if target:
                    results.append({
                        "relation": rel.relation_type,
                        "target": target.name,
                        "target_type": target.entity_type,
                        "weight": rel.weight,
                    })
        return results

    def get_relations_to(self, entity_name: str) -> list[dict]:
        """Retorna todos os relacionamentos chegando em uma entidade."""
        entity = self.get_entity(entity_name)
        if not entity:
            return []

        results = []
        for rel in self._relations.values():
            if rel.target_id == entity.id:
                source = self._entities.get(rel.source_id)
                if source:
                    results.append({
                        "relation": rel.relation_type,
                        "source": source.name,
                        "source_type": source.entity_type,
                        "weight": rel.weight,
                    })
        return results

    def get_neighbors(self, entity_name: str) -> list[dict]:
        """Retorna todas as entidades vizinhas."""
        outgoing = self.get_relations_from(entity_name)
        incoming = self.get_relations_to(entity_name)
        return outgoing + incoming

    # ── Fatos ──────────────────────────────────────────────

    def add_fact(
        self,
        entity_name: str,
        content: str,
        source: str = "conversation",
        confidence: float = 1.0,
    ) -> Optional[Fact]:
        """Adiciona um fato sobre uma entidade."""
        entity = self.get_entity(entity_name)
        if not entity:
            # Criar entidade automaticamente
            entity = self.add_entity(entity_name, "conceito")

        fact = Fact(
            id=self._next_id("fact"),
            entity_id=entity.id,
            content=content,
            source=source,
            confidence=confidence,
        )
        self._facts[fact.id] = fact
        self._save()
        return fact

    def get_facts(self, entity_name: str) -> list[Fact]:
        """Retorna todos os fatos de uma entidade."""
        entity = self.get_entity(entity_name)
        if not entity:
            return []
        return [f for f in self._facts.values() if f.entity_id == entity.id]

    # ── Extração automática ────────────────────────────────

    def extract_from_text(self, text: str) -> dict:
        """Extrai entidades e relacionamentos de um texto.

        Usa heurísticas simples para extrair informações.
        """
        extracted = {"entities": [], "relations": [], "facts": []}

        # Padrões para entidades
        entity_patterns = [
            (r"meu nome é (\w+)", "pessoa", "perfil"),
            (r"me chamo (\w+)", "pessoa", "perfil"),
            (r"meu projeto ([\w\s]+)", "projeto", "projeto"),
            (r"trabalho com ([\w\s]+)", "conceito", "trabalho"),
            (r"uso ([\w\s]+)", "ferramenta", "uso"),
            (r"tenho um ([\w\s]+)", "dispositivo", "posse"),
            (r"moro em ([\w\s]+)", "lugar", "localização"),
        ]

        for pattern, entity_type, tag in entity_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                name = match.group(1).strip()
                if len(name) > 1:
                    entity = self.add_entity(name, entity_type, {"tag": tag})
                    extracted["entities"].append({"name": name, "type": entity_type})

        # Padrões para relacionamentos
        rel_patterns = [
            (r"(\w+) trabalha com (\w+)", "trabalha_com"),
            (r"(\w+) gosta de (\w+)", "gosta_de"),
            (r"(\w+) usa (\w+)", "usa"),
            (r"(\w+) criou (\w+)", "criou"),
            (r"(\w+) é amigo de (\w+)", "amigo_de"),
        ]

        for pattern, rel_type in rel_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                source_name = match.group(1).strip()
                target_name = match.group(2).strip()
                source = self.get_entity(source_name)
                target = self.get_entity(target_name)
                if source and target:
                    self.add_relation(source_name, target_name, rel_type)
                    extracted["relations"].append({
                        "source": source_name,
                        "target": target_name,
                        "type": rel_type,
                    })

        return extracted

    # ── Visualização ───────────────────────────────────────

    def get_stats(self) -> dict:
        """Retorna estatísticas do grafo."""
        return {
            "entities": len(self._entities),
            "relations": len(self._relations),
            "facts": len(self._facts),
            "entity_types": len(set(e.entity_type for e in self._entities.values())),
        }

    def format_entity(self, entity: Entity) -> str:
        """Formata uma entidade para exibição."""
        relations = self.get_neighbors(entity.name)
        facts = self.get_facts(entity.name)

        lines = [
            f"📌 {entity.name} ({entity.entity_type})",
            f"   ID: {entity.id}",
        ]

        if entity.properties:
            props = ", ".join(f"{k}={v}" for k, v in entity.properties.items())
            lines.append(f"   Props: {props}")

        if relations:
            lines.append("   Relacionamentos:")
            for rel in relations[:5]:
                lines.append(f"     → {rel['relation']}: {rel['target']}")

        if facts:
            lines.append("   Fatos:")
            for fact in facts[:3]:
                lines.append(f"     • {fact.content}")

        return "\n".join(lines)

    def format_graph_summary(self) -> str:
        """Formata um resumo do grafo."""
        stats = self.get_stats()
        lines = [
            f"🧠 Knowledge Graph",
            f"   Entidades: {stats['entities']}",
            f"   Relacionamentos: {stats['relations']}",
            f"   Fatos: {stats['facts']}",
        ]

        # Top entidades por tipo
        type_counts = {}
        for entity in self._entities.values():
            type_counts[entity.entity_type] = type_counts.get(entity.entity_type, 0) + 1

        if type_counts:
            lines.append("   Por tipo:")
            for t, c in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"     {t}: {c}")

        return "\n".join(lines)
