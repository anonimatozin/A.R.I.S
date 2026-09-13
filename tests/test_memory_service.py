"""Testes offline do sistema de memória cognitiva (core/memcore).

Nunca toca D:/ARIS_MEMORY real: sempre usa roots temporários.
Cobre: persistência, working memory, associações, consolidação,
contradição, decay, fallback, migração, backup/corrupção e eventos.
"""

from __future__ import annotations

import json
from datetime import UTC

from core.memcore import MemoryKind, MemoryService, StorageClass
from core.memcore.models import MemoryItem


def make_service(tmp_path, legacy_dir=None, primary=None) -> MemoryService:
    primary = primary or (tmp_path / "primary")
    fb = tmp_path / "fallback"
    svc = MemoryService(primary_root=primary, fallback_root=fb,
                        legacy_dir=legacy_dir)
    svc.boot()
    return svc


# ── persistência básica ──────────────────────────────────────────────────

def test_save_retrieve_update_forget(tmp_path):
    svc = make_service(tmp_path)
    m = svc.remember("Vinicius gosta de café forte", importance=8.0)
    got = svc.get(m.id)
    assert isinstance(got, MemoryItem)
    assert got.content == "Vinicius gosta de café forte"
    assert got.importance == 8.0
    assert got.memory_type == MemoryKind.SEMANTIC

    assert svc.update(m.id, importance=9.0, confidence=0.95)
    assert svc.get(m.id).importance == 9.0
    assert svc.get(m.id).confidence == 0.95

    svc.forget(m.id)
    assert svc.get(m.id) is None


def test_retrieve_scores_semantics(tmp_path):
    svc = make_service(tmp_path)
    svc.remember("Vinicius mora em São Paulo", importance=8.0,
                 entities=["vinicius", "sao paulo"])
    svc.remember("O projeto ARIS usa Python", importance=7.0,
                 entities=["aris", "python"])
    results = svc.retrieve("o que sei sobre vinicius?", limit=5)
    assert results, "deveria encontrar memórias"
    assert results[0]["content"].lower().find("vinicius") != -1


def test_save_role(tmp_path):
    svc = make_service(tmp_path)
    one = svc.remember("relato a", importance=5.0)
    svc.retrieve("busca a", limit=5)
    got = svc.get(one.id)
    assert got.access_count >= 1


def test_remember_auto_entities(tmp_path):
    svc = make_service(tmp_path)
    m = svc.remember("Adoro pizza de calabresa")
    assert any("calabresa" in e for e in m.entities)


def test_create_kinds(tmp_path):
    svc = make_service(tmp_path)
    e = svc.create_episode("Instalei o driver da impressora")
    assert e.memory_type == MemoryKind.EPISODIC
    s = svc.create_semantic_memory("O usuário prefere tema escuro")
    assert s.memory_type == MemoryKind.SEMANTIC
    p = svc.create_procedure("Para reiniciar a rede use netsh reset")
    assert p.memory_type == MemoryKind.PROCEDURAL


def test_search_empty_lists_all(tmp_path):
    svc = make_service(tmp_path)
    svc.remember("uma", importance=5.0)
    svc.remember("duas", importance=5.0)
    assert len(svc.search("", limit=10)) >= 2


# ── working memory ───────────────────────────────────────────────────────

def test_working_memory_roundtrip(tmp_path):
    svc = make_service(tmp_path)
    assert svc.get_working_memory("proj") is None
    svc.set_working_memory("proj", goal="criar API", entities=["api"],
                           constraints=["offline"], steps=["step1"], results=["ok"])
    wm = svc.get_working_memory("proj")
    assert wm["goal"] == "criar API"
    assert wm["entities"] == ["api"]
    assert wm["steps"] == ["step1"]
    svc.clear_working_memory("proj")
    assert svc.get_working_memory("proj") is None


# ── associações ──────────────────────────────────────────────────────────

def test_associate_and_related(tmp_path):
    svc = make_service(tmp_path)
    a = svc.remember("Python é usado no ARIS", importance=7.0)
    b = svc.remember("Instalei a biblioteca requests", importance=6.0)
    svc.associate(a.id, b.id, "related_to", 0.9, "mesmo projeto")
    other = svc.related(a.id)
    assert b.id in other


# ── consolidação via eventos ─────────────────────────────────────────────

def test_observe_fact_becomes_semantic(tmp_path):
    svc = make_service(tmp_path)
    svc.observe("USER_MESSAGE", {"text": "Prefiro o tema escuro no editor"})
    results = svc.search("prefere tema escuro", limit=5)
    assert any(r["memory_type"] == "semantic" for r in results)


def test_observe_short_dropped(tmp_path):
    svc = make_service(tmp_path)
    svc.observe("USER_MESSAGE", {"text": "ok"})
    assert svc.get_stats()["total"] == 0


def test_observe_event_becomes_episode(tmp_path):
    svc = make_service(tmp_path)
    svc.observe("USER_MESSAGE", {"text": "Estou instalando o mysql aqui hoje"})
    results = svc.search("instalando mysql", limit=5)
    assert any(r["memory_type"] == "episodic" for r in results)


def test_contradiction_lowers_confidence_and_links(tmp_path):
    svc = make_service(tmp_path)
    old = svc.remember("Vinicius usa Windows", importance=8.0)
    svc.observe("USER_MESSAGE", {"text": "Na verdade agora o Vinicius usa Linux para programar"})
    got = svc.get(old.id)
    assert got.confidence < 0.7
    new = svc.search("uso linux", limit=5)
    assert new and new[0]["memory_type"] == "semantic"
    assert old.id in svc.related(new[0]["id"])


# ── decay / expiração ────────────────────────────────────────────────────

def test_expired_temporary_removed(tmp_path):
    from datetime import datetime, timedelta
    svc = make_service(tmp_path)
    past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    svc.remember("lembrete temporário", storage=StorageClass.TEMPORARY)
    rows = svc._db.query_memories(limit=50)
    for r in rows:
        svc._db.update_memory(r["id"], {"expiration": past})
    from core.memcore.decay import apply_decay
    apply_decay(svc._db)
    rows = svc._db.query_memories(limit=50)
    assert all(r["memory_type"] != "conversation" for r in rows)
    assert all(r["storage_class"] != "temporary" for r in rows)


def test_critical_never_expires(tmp_path):
    from datetime import datetime, timedelta

    from core.memcore.decay import apply_decay
    svc = make_service(tmp_path)
    past = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    m = svc.remember("usuário é o Administrador", storage=StorageClass.CRITICAL)
    svc._db.update_memory(m.id, {"expiration": past})
    apply_decay(svc._db)
    assert svc.get(m.id) is not None


def test_forgotten_purged(tmp_path):
    from core.memcore.decay import apply_decay
    svc = make_service(tmp_path)
    m = svc.remember("conteúdo que será esquecido", importance=1.0)
    svc.forget(m.id)
    apply_decay(svc._db)
    assert svc.get(m.id) is None


# ── fallback ─────────────────────────────────────────────────────────────

def test_fallback_when_primary_unavailable(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("sou um arquivo", encoding="utf-8")
    svc = make_service(tmp_path, primary=blocked)
    assert svc.primary_available is False
    m = svc.remember("estamos no fallback")
    assert svc.get(m.id) is not None
    assert svc.get_stats()["root"] == str(tmp_path / "fallback") or "fallback" in svc.get_stats()["root"]


# ── migração ─────────────────────────────────────────────────────────────

def test_migrate_legacy(tmp_path):
    legacy = tmp_path / "legacy_memory"
    index = legacy / "Index"
    index.mkdir(parents=True)
    (index / "memory_index.json").write_text(json.dumps({
        "memories": [
            {"content": "Vinicius gosta de café", "category": "profile",
             "is_permanente": True, "importance": 8.0},
            {"content": "ontem conversamos sobre python", "category": "conversations",
             "importance": 4.0},
        ]
    }), encoding="utf-8")
    (legacy / "Episodic").mkdir(parents=True)
    (legacy / "Episodic" / "episodes.json").write_text(json.dumps([
        {"description": "resolvi o problema da rede hoje"}
    ]), encoding="utf-8")

    svc = MemoryService(primary_root=tmp_path / "migrate_root",
                        fallback_root=tmp_path / "fb",
                        legacy_dir=legacy)
    svc.boot()
    assert svc._db.get_meta("migrated") == "yes"
    rows = svc._db.query_memories(limit=100)
    assert len(rows) >= 3
    assert any(r["memory_type"] == "semantic" and "café" in r["content"] for r in rows)
    assert any(r["storage_class"] == "critical" for r in rows)
    backups = list((tmp_path / "migrate_root" / "backups").glob("legacy-*"))
    assert backups, "backup dos originais deve existir"


def test_migrate_no_double(tmp_path):
    legacy = tmp_path / "legacy_memory2"
    (legacy / "Index").mkdir(parents=True)
    (legacy / "Index" / "memory_index.json").write_text(json.dumps({
        "memories": [{"content": "deve ser único", "category": "knowledge"}]
    }), encoding="utf-8")
    svc = make_service(tmp_path, legacy_dir=legacy)
    first = svc.get_stats()["total"]
    svc.boot()  # segunda execução
    assert svc.get_stats()["total"] == first


# ── backup / corrupção ───────────────────────────────────────────────────

def test_backup_and_recovery(tmp_path):
    svc = make_service(tmp_path)
    svc.remember("informação que precisa sobreviver")
    svc._backup.snapshot()
    # corrompe o banco
    svc.close()
    with open(svc.root / "database" / "aris_memory.db", "w", encoding="utf-8") as f:
        f.write("garbage")
    svc2 = make_service(tmp_path)
    results = svc2.search("sobreviver", limit=5)
    assert any(r["content"].find("sobreviver") != -1 for r in results)


def test_corrupt_preserved(tmp_path):
    svc = make_service(tmp_path)
    svc._backup.snapshot()
    svc.close()
    with open(svc.root / "database" / "aris_memory.db", "w", encoding="utf-8") as f:
        f.write("garbage")
    make_service(tmp_path)
    corrupt = list((tmp_path / "primary" / "backups").glob("corrupt_*_original.db"))
    assert corrupt or list((tmp_path / "primary" / "database").glob("aris_memory_corrupt_*.db"))


# ── API pública: métodos exigidos na spec ────────────────────────────────

def test_api_surface(tmp_path):
    svc = make_service(tmp_path)
    for name in ("remember", "retrieve", "search", "update", "forget",
                 "reinforce", "touch", "associate", "related", "get",
                 "create_episode", "create_semantic_memory", "create_procedure",
                 "get_working_memory", "set_working_memory", "clear_working_memory",
                 "observe", "consolidate", "backup_now", "get_stats", "boot", "close"):
        assert hasattr(svc, name), f"falta método {name}"
