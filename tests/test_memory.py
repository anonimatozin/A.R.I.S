"""Testes do sistema de memória SQLite do A.R.I.S.

Cobre: MemoryDB, MemoryManager (SQLite backend), KnowledgeGraph (SQLite),
eventos memory.*, persistência, migração JSON→SQLite.
"""

import json

import pytest

from core.memory import MemoryManager
from core.memory_db import MemoryDB
from core.memory_models import MemoryCategory
from core.neural.event_bus import EventBus
from core.neural.events import (
    EVENT_MEMORY_CREATED,
    EVENT_MEMORY_DELETED,
    EVENT_MEMORY_RETRIEVED,
    EVENT_MEMORY_UPDATED,
)
from modules.knowledge_graph import KnowledgeGraph
from utils.logger import Logger


def _logger():
    return Logger(name="test-memory", level="CRITICAL")


@pytest.fixture
def tmp_db(tmp_path):
    """MemoryDB isolado em diretório temporário."""
    return MemoryDB(db_dir=tmp_path, logger=_logger())


@pytest.fixture
def tmp_memory(tmp_path):
    """MemoryManager com backend SQLite isolado."""
    return MemoryManager(logger=_logger(), memory_root=tmp_path / "mem",
                         db_dir=tmp_path / "db")


@pytest.fixture
def tmp_kg(tmp_path):
    """KnowledgeGraph com backend SQLite isolado."""
    data_dir = tmp_path / "kg_data"
    data_dir.mkdir()
    db = MemoryDB(db_dir=tmp_path, logger=_logger())
    return KnowledgeGraph(data_dir=data_dir, db=db)


@pytest.fixture
def bus():
    return EventBus()


# ── MemoryDB — Schema e CRUD ────────────────────────────────

class TestMemoryDB:
    def test_tables_created(self, tmp_db):
        rows = tmp_db._execute("SELECT name FROM sqlite_master WHERE type='table'", fetch=True)
        names = {r["name"] for r in rows}
        assert "memory_entries" in names
        assert "entities" in names
        assert "relations" in names
        assert "facts" in names

    def test_insert_and_get_memory(self, tmp_db):
        now = "2026-01-01T00:00:00"
        tmp_db.insert_memory({
            "id": "m1", "category": "Knowledge", "title": "Teste",
            "content": "Conteúdo", "importance": 7, "priority": "Alta",
            "tags": "[]", "source": "test", "memory_type": "semantic",
            "created_at": now, "last_accessed": now, "access_count": 0,
            "is_permanente": 0,
        })
        row = tmp_db.get_memory("m1")
        assert row is not None
        assert row["title"] == "Teste"
        assert row["importance"] == 7

    def test_get_nonexistent_returns_none(self, tmp_db):
        assert tmp_db.get_memory("nope") is None

    def test_search_memories(self, tmp_db):
        now = "2026-01-01T00:00:00"
        for i in range(5):
            tmp_db.insert_memory({
                "id": f"m{i}", "category": "Projects", "title": f"Projeto {i}",
                "content": f"Conteúdo {i}", "importance": 3 + i, "priority": "Média",
                "tags": "[]", "source": "test", "memory_type": "semantic",
                "created_at": now, "last_accessed": now, "access_count": 0,
                "is_permanente": 0,
            })
        results = tmp_db.search_memories(query="Projeto", limit=3)
        assert len(results) == 3

    def test_update_memory(self, tmp_db):
        now = "2026-01-01T00:00:00"
        tmp_db.insert_memory({
            "id": "m1", "category": "Knowledge", "title": "Original",
            "content": "Conteúdo", "importance": 5, "priority": "Média",
            "tags": "[]", "source": "test", "memory_type": "semantic",
            "created_at": now, "last_accessed": now, "access_count": 0,
            "is_permanente": 0,
        })
        tmp_db.update_memory("m1", title="Atualizado", importance=9)
        row = tmp_db.get_memory("m1")
        assert row["title"] == "Atualizado"
        assert row["importance"] == 9

    def test_delete_memory(self, tmp_db):
        now = "2026-01-01T00:00:00"
        tmp_db.insert_memory({
            "id": "m1", "category": "Knowledge", "title": "Para deletar",
            "content": "X", "importance": 1, "priority": "Baixa",
            "tags": "[]", "source": "test", "memory_type": "semantic",
            "created_at": now, "last_accessed": now, "access_count": 0,
            "is_permanente": 0,
        })
        assert tmp_db.delete_memory("m1") is True
        assert tmp_db.get_memory("m1") is None

    def test_insert_entity_and_relation(self, tmp_db):
        now = "2026-01-01T00:00:00"
        tmp_db.insert_entity({
            "id": "e1", "name": "Python", "entity_type": "conceito",
            "properties": "{}", "confidence": 1.0, "source": "test",
            "created_at": now,
        })
        tmp_db.insert_entity({
            "id": "e2", "name": "ARIS", "entity_type": "projeto",
            "properties": "{}", "confidence": 1.0, "source": "test",
            "created_at": now,
        })
        tmp_db.insert_relation({
            "id": "r1", "source_id": "e1", "target_id": "e2",
            "relation_type": "usa", "properties": "{}", "weight": 1.0,
            "confidence": 1.0, "source": "test", "created_at": now,
        })
        rels = tmp_db.search_relations(source_id="e1")
        assert len(rels) == 1
        assert rels[0]["relation_type"] == "usa"

    def test_delete_entity_cascades(self, tmp_db):
        now = "2026-01-01T00:00:00"
        tmp_db.insert_entity({"id": "e1", "name": "X", "entity_type": "t", "properties": "{}", "confidence": 1.0, "source": "test", "created_at": now})
        tmp_db.insert_entity({"id": "e2", "name": "Y", "entity_type": "t", "properties": "{}", "confidence": 1.0, "source": "test", "created_at": now})
        tmp_db.insert_relation({"id": "r1", "source_id": "e1", "target_id": "e2", "relation_type": "usa", "properties": "{}", "weight": 1.0, "confidence": 1.0, "source": "test", "created_at": now})
        tmp_db.insert_fact({"id": "f1", "entity_id": "e1", "content": "fact", "source": "test", "confidence": 1.0, "created_at": now})
        tmp_db.delete_entity("e1")
        assert tmp_db.get_entity("e1") is None
        assert len(tmp_db.search_relations(source_id="e1")) == 0
        assert len(tmp_db.search_facts(entity_id="e1")) == 0

    def test_stats(self, tmp_db):
        now = "2026-01-01T00:00:00"
        tmp_db.insert_memory({"id": "m1", "category": "Knowledge", "title": "T", "content": "C", "importance": 5, "priority": "Média", "tags": "[]", "source": "test", "memory_type": "semantic", "created_at": now, "last_accessed": now, "access_count": 0, "is_permanente": 0})
        tmp_db.insert_entity({"id": "e1", "name": "E", "entity_type": "t", "properties": "{}", "confidence": 1.0, "source": "test", "created_at": now})
        stats = tmp_db.stats()
        assert stats["total_memories"] == 1
        assert stats["total_entities"] == 1


# ── MemoryManager — API pública sobre SQLite ─────────────────

class TestMemoryManagerSQLite:
    def test_save_and_get(self, tmp_memory):
        entry = tmp_memory.save("Titulo", "Conteúdo", MemoryCategory.KNOWLEDGE, 7)
        assert entry.id
        retrieved = tmp_memory.get(entry.id)
        assert retrieved is not None
        assert retrieved.title == "Titulo"
        assert retrieved.content == "Conteúdo"

    def test_search(self, tmp_memory):
        tmp_memory.save("Projeto X", "Detalhes do projeto", MemoryCategory.PROJECTS, 8)
        tmp_memory.save("Conversa Y", "Resumo", MemoryCategory.CONVERSATIONS, 3)
        results = tmp_memory.search(query="Projeto", category=MemoryCategory.PROJECTS)
        assert len(results) == 1
        assert results[0].title == "Projeto X"

    def test_update(self, tmp_memory):
        entry = tmp_memory.save("Original", "Conteúdo")
        updated = tmp_memory.update(entry.id, title="Novo título", importance=9)
        assert updated is not None
        assert updated.title == "Novo título"
        assert updated.importance == 9

    def test_delete(self, tmp_memory):
        entry = tmp_memory.save("Para deletar", "X")
        assert tmp_memory.delete(entry.id) is True
        assert tmp_memory.get(entry.id) is None

    def test_delete_permanent_requires_confirm(self, tmp_memory):
        entry = tmp_memory.save("Permanente", "X", is_permanente=True)
        assert tmp_memory.delete(entry.id, confirm=False) is False
        assert tmp_memory.get(entry.id) is not None
        assert tmp_memory.delete(entry.id, confirm=True) is True

    def test_persistence_across_instances(self, tmp_path):
        db_dir = tmp_path / "db"
        mem1 = MemoryManager(logger=_logger(), memory_root=tmp_path / "mem",
                             db_dir=db_dir)
        entry = mem1.save("Persistente", "Dados importantes")
        entry_id = entry.id

        mem2 = MemoryManager(logger=_logger(), memory_root=tmp_path / "mem",
                             db_dir=db_dir)
        retrieved = mem2.get(entry_id)
        assert retrieved is not None
        assert retrieved.title == "Persistente"

    def test_get_stats(self, tmp_memory):
        tmp_memory.save("A", "X", MemoryCategory.KNOWLEDGE, 5)
        tmp_memory.save("B", "Y", MemoryCategory.PROJECTS, 8)
        stats = tmp_memory.get_stats()
        assert stats["total_memories"] == 2
        assert "Knowledge" in stats["by_category"]
        assert "Projects" in stats["by_category"]

    def test_should_save_keywords(self, tmp_memory):
        assert tmp_memory.should_save("Meu projeto usa Python") is True
        assert tmp_memory.should_save("ok") is False
        assert tmp_memory.should_save("Oi") is False


# ── KnowledgeGraph — API pública sobre SQLite ─────────────────

class TestKnowledgeGraphSQLite:
    def test_add_entity(self, tmp_kg):
        entity = tmp_kg.add_entity("Python", "conceito", {"linguagem": "sim"})
        assert entity.id
        assert entity.name == "Python"
        found = tmp_kg.get_entity("Python")
        assert found is not None
        assert found.entity_type == "conceito"

    def test_add_entity_dedup(self, tmp_kg):
        e1 = tmp_kg.add_entity("Python", "conceito")
        e2 = tmp_kg.add_entity("Python", "ferramenta")
        assert e1.id == e2.id  # mesma entidade, não duplica

    def test_add_relation(self, tmp_kg):
        tmp_kg.add_entity("ARIS", "projeto")
        tmp_kg.add_entity("Python", "conceito")
        rel = tmp_kg.add_relation("ARIS", "Python", "usa")
        assert rel is not None
        assert rel.relation_type == "usa"
        neighbors = tmp_kg.get_neighbors("ARIS")
        assert len(neighbors) == 1
        assert neighbors[0]["target"] == "Python"

    def test_add_fact(self, tmp_kg):
        tmp_kg.add_entity("ARIS", "projeto")
        fact = tmp_kg.add_fact("ARIS", "É um assistente pessoal")
        assert fact is not None
        facts = tmp_kg.get_facts("ARIS")
        assert len(facts) == 1
        assert facts[0].content == "É um assistente pessoal"

    def test_get_stats(self, tmp_kg):
        tmp_kg.add_entity("A", "tipo1")
        tmp_kg.add_entity("B", "tipo2")
        tmp_kg.add_entity("A", "tipo1")  # dedup
        tmp_kg.add_entity("C", "tipo1")
        stats = tmp_kg.get_stats()
        assert stats["entities"] == 3
        assert stats["entity_types"] == 2

    def test_persistence_across_instances(self, tmp_path):
        db = MemoryDB(db_dir=tmp_path, logger=_logger())
        kg1 = KnowledgeGraph(data_dir=tmp_path / "kg", db=db)
        kg1.add_entity("Persistente", "teste")

        # Nova instância recarrega do mesmo DB
        kg2 = KnowledgeGraph(data_dir=tmp_path / "kg2", db=db)
        found = kg2.get_entity("Persistente")
        assert found is not None

    def test_format_entity(self, tmp_kg):
        tmp_kg.add_entity("Teste", "conceito", {"chave": "valor"})
        tmp_kg.add_entity("Outro", "conceito")
        tmp_kg.add_relation("Teste", "Outro", "relacionado_a")
        tmp_kg.add_fact("Teste", "Fato importante")
        entity = tmp_kg.get_entity("Teste")
        fmt = tmp_kg.format_entity(entity)
        assert "Teste" in fmt
        assert "conceito" in fmt


# ── Eventos memory.* ─────────────────────────────────────────

class TestMemoryEvents:
    def test_save_emits_created(self, tmp_memory, bus):
        tmp_memory.set_event_bus(bus)
        collector = []
        bus.subscribe("*", collector.append)
        tmp_memory.save("Teste evento", "Conteúdo")
        types = {e.event_type for e in collector}
        assert EVENT_MEMORY_CREATED in types

    def test_get_emits_retrieved(self, tmp_memory, bus):
        tmp_memory.set_event_bus(bus)
        entry = tmp_memory.save("Para buscar", "X")
        collector = []
        bus.subscribe("*", collector.append)
        tmp_memory.get(entry.id)
        types = {e.event_type for e in collector}
        assert EVENT_MEMORY_RETRIEVED in types

    def test_update_emits_updated(self, tmp_memory, bus):
        tmp_memory.set_event_bus(bus)
        entry = tmp_memory.save("Para atualizar", "X")
        collector = []
        bus.subscribe("*", collector.append)
        tmp_memory.update(entry.id, title="Novo")
        types = {e.event_type for e in collector}
        assert EVENT_MEMORY_UPDATED in types

    def test_delete_emits_deleted(self, tmp_memory, bus):
        tmp_memory.set_event_bus(bus)
        entry = tmp_memory.save("Para deletar", "X")
        collector = []
        bus.subscribe("*", collector.append)
        tmp_memory.delete(entry.id)
        types = {e.event_type for e in collector}
        assert EVENT_MEMORY_DELETED in types

    def test_events_registered(self):
        from core.neural.events import MEMORY_EVENT_TYPES
        assert EVENT_MEMORY_CREATED in MEMORY_EVENT_TYPES
        assert EVENT_MEMORY_RETRIEVED in MEMORY_EVENT_TYPES
        assert EVENT_MEMORY_UPDATED in MEMORY_EVENT_TYPES
        assert EVENT_MEMORY_DELETED in MEMORY_EVENT_TYPES


# ── Migração JSON → SQLite ──────────────────────────────────

class TestMigration:
    def test_migrate_json_index(self, tmp_path):
        """Simula migração de memory_index.json existente."""
        mem_dir = tmp_path / "mem"
        index_dir = mem_dir / "Index"
        index_dir.mkdir(parents=True)

        # Criar índice JSON antigo
        index_data = {
            "version": "1.0",
            "memories": [
                {
                    "id": "old1",
                    "title": "Memória antiga",
                    "content": "Dados do JSON",
                    "category": "Knowledge",
                    "importance": 8,
                    "priority": "Alta",
                    "tags": ["tag1"],
                    "source": "test",
                    "created_at": "2025-01-01T00:00:00",
                    "last_accessed": "2025-01-01T00:00:00",
                    "access_count": 3,
                    "is_permanente": False,
                }
            ],
        }
        (index_dir / "memory_index.json").write_text(
            json.dumps(index_data), encoding="utf-8"
        )

        # Criar MemoryManager — deve migrar automaticamente
        mem = MemoryManager(logger=_logger(), memory_root=mem_dir)

        # Verificar que dados foram importados
        entry = mem.get("old1")
        assert entry is not None
        assert entry.title == "Memória antiga"
        assert entry.importance == 8

        # Verificar que JSON antigo foi movido para backup
        backup_dir = mem_dir / "_migrated_backup"
        assert backup_dir.exists()

    def test_migrate_knowledge_graph_json(self, tmp_path):
        """Simula migração de knowledge_graph.json existente."""
        data_dir = tmp_path / "kg"
        data_dir.mkdir()

        # Criar knowledge_graph.json antigo
        kg_data = {
            "entities": [
                {"id": "ent_1", "name": "ARIS", "entity_type": "projeto", "properties": {}, "created_at": "2025-01-01T00:00:00", "last_accessed": "2025-01-01T00:00:00"},
            ],
            "relations": [
                {"id": "rel_1", "source_id": "ent_1", "target_id": "ent_1", "relation_type": "usa", "properties": {}, "weight": 1.0, "created_at": "2025-01-01T00:00:00"},
            ],
            "facts": [
                {"id": "fact_1", "entity_id": "ent_1", "content": "É um assistente", "source": "test", "confidence": 1.0, "created_at": "2025-01-01T00:00:00"},
            ],
            "counter": 3,
        }
        (data_dir / "knowledge_graph.json").write_text(
            json.dumps(kg_data), encoding="utf-8"
        )

        db = MemoryDB(db_dir=tmp_path, logger=_logger())
        kg = KnowledgeGraph(data_dir=data_dir, db=db)

        # Verificar que dados foram importados
        entity = kg.get_entity("ARIS")
        assert entity is not None
        assert entity.entity_type == "projeto"

        facts = kg.get_facts("ARIS")
        assert len(facts) == 1
        assert facts[0].content == "É um assistente"

        # Verificar que JSON antigo foi movido para backup
        backup_dir = data_dir / "_migrated_backup"
        assert backup_dir.exists()
