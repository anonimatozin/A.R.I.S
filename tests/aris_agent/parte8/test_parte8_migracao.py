"""Parte 8 — migração da memória antiga (memory_entries) → SqliteMemory."""

from __future__ import annotations

import sqlite3

from aris_agent.bridge.migracao import caminho_memoria_antiga, importar_memoria_antiga
from aris_agent.memory.sqlite import SqliteMemory

LINHAS = [
    ("Gosta de café", "Eu gosto de café coado", "UserProfile", '["gosto"]', "1700000000"),
    ("Projeto ARIS", "Sistema de voz em Python", "knowledge", "[]", "2024-05-01T10:00:00"),
    ("Lição de violão", "Aprender a tocar violão", "lessons", "[]", "data-invalida"),
]


def _db_legado(tmp_path, linhas=LINHAS):
    db = tmp_path / "aris_memory.db"
    con = sqlite3.connect(db)
    con.execute(
        """CREATE TABLE memory_entries (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            importance INTEGER NOT NULL DEFAULT 5,
            priority TEXT NOT NULL DEFAULT 'Média',
            tags TEXT NOT NULL DEFAULT '[]',
            source TEXT NOT NULL DEFAULT 'conversation',
            memory_type TEXT NOT NULL DEFAULT 'semantic',
            created_at TEXT NOT NULL,
            last_accessed TEXT NOT NULL,
            access_count INTEGER NOT NULL DEFAULT 0,
            is_permanente INTEGER NOT NULL DEFAULT 0
        )"""
    )
    for i, (titulo, conteudo, categoria, tags, criado) in enumerate(linhas):
        con.execute(
            "INSERT INTO memory_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"id{i}", categoria, titulo, conteudo, 5, "Média", tags,
                "conversation", "semantic", criado, criado, 0, 0,
            ),
        )
    con.commit()
    con.close()
    return db


def test_importa_memoria_antiga(tmp_path) -> None:
    db = _db_legado(tmp_path)
    memoria = SqliteMemory(tmp_path / "agent.db")
    stats = importar_memoria_antiga(memoria, caminho=db)
    assert stats is not None
    assert stats["created"] == 3
    assert stats["skipped"] == 0


def test_importacao_e_idempotente(tmp_path) -> None:
    """Rodar duas vezes não duplica — dedup exato por texto."""
    db = _db_legado(tmp_path)
    memoria = SqliteMemory(tmp_path / "agent.db")
    primeira = importar_memoria_antiga(memoria, caminho=db)
    segunda = importar_memoria_antiga(memoria, caminho=db)
    assert primeira["created"] == 3
    assert segunda["created"] == 0
    assert segunda["skipped"] + segunda["updated"] == 3


def test_banco_inexistente_devolve_none(tmp_path) -> None:
    memoria = SqliteMemory(tmp_path / "agent.db")
    assert importar_memoria_antiga(memoria, caminho=tmp_path / "nao_existe.db") is None


def test_banco_sem_tabela_devolve_none(tmp_path) -> None:
    vazio = tmp_path / "outro.db"
    sqlite3.connect(vazio).close()
    memoria = SqliteMemory(tmp_path / "agent.db")
    assert importar_memoria_antiga(memoria, caminho=vazio) is None


def test_tabela_vazia_devolve_zero(tmp_path) -> None:
    db = _db_legado(tmp_path, linhas=[])
    memoria = SqliteMemory(tmp_path / "agent.db")
    stats = importar_memoria_antiga(memoria, caminho=db)
    assert stats == {"created": 0, "updated": 0, "skipped": 0}


def test_caminho_da_memoria_antiga_via_env(tmp_path, monkeypatch) -> None:
    db = _db_legado(tmp_path)
    monkeypatch.setenv("ARIS_MEMORY_DIR", str(tmp_path))
    assert caminho_memoria_antiga() == db


def test_caminho_da_memoria_antiga_sem_env(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ARIS_MEMORY_DIR", raising=False)
    achado = caminho_memoria_antiga()
    # pode achar a do repositório (port do Linux) ou nada; só não pode explodir
    assert achado is None or achado.name == "aris_memory.db"
