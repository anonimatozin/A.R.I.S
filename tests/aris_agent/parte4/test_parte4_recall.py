"""Testes de busca/ranking da SqliteMemory: FTS5, fallback LIKE, acentos, embedder (Parte 4)."""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid

import pytest

from aris_agent.memory import SqliteMemory
from aris_agent.memory.schema import enable_fts


@pytest.fixture
def mem(tmp_path):
    instance = SqliteMemory(tmp_path / "memory.sqlite3")
    yield instance
    instance.close()


class FakeEmbedder:
    """Embedder de mentira: bag-of-words com hash (determinístico, sem modelo)."""

    def __init__(self, dims: int = 16) -> None:
        self.dims = dims
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        vector = [0.0] * self.dims
        for token in text.lower().split():
            vector[hash(token) % self.dims] += 1.0
        return vector


def test_fts_ativo_por_padrao(tmp_path) -> None:
    with SqliteMemory(tmp_path / "fts.sqlite3") as mem:
        assert mem.fts_enabled is True


def test_busca_ignora_acento_e_caixa(mem: SqliteMemory) -> None:
    mem.remember("Configuração do roteador doméstico", kind="fact")
    for query in ("configuracao", "CONFIGURAÇÃO", "Configuração", "ROTEADOR"):
        found = mem.recall(query, k=3)
        assert found, f"consulta {query!r} não achou nada"
        assert found[0].kind == "fact"


def test_busca_prefixo(mem: SqliteMemory) -> None:
    mem.remember("chuva caiu forte ontem à tarde")
    assert mem.recall("chuv", k=3), "prefixo 'chuv' deveria achar 'chuva'"


def test_filtro_por_kinds(mem: SqliteMemory) -> None:
    mem.remember("usuario assistiu o jogo ontem a noite", kind="fact")
    mem.remember("usuario ama jogos de tabuleiro", kind="preference")
    all_items = mem.recall("jogo", k=5)
    assert {item.kind for item in all_items} == {"fact", "preference"}
    only_pref = mem.recall("jogo", k=5, kinds=("preference",))
    assert [item.kind for item in only_pref] == ["preference"]
    assert mem.recall("jogo", k=5, kinds=()) == []


def test_ranking_recente_importante_vence_antigo(mem: SqliteMemory) -> None:
    now = time.time()
    mem.import_records(
        [
            {
                "text": "relatorio de vendas antigo",
                "kind": "fact",
                "created_at": now - 400 * 86400,
                "importance": 0.1,
            },
            {
                "text": "relatorio de vendas recente",
                "kind": "fact",
                "created_at": now - 86400,
                "importance": 0.9,
            },
        ]
    )
    found = mem.recall("relatorio de vendas", k=2)
    assert [item.text for item in found] == [
        "relatorio de vendas recente",
        "relatorio de vendas antigo",
    ]
    assert found[0].score > found[1].score


def test_ranking_recencia_isolada(tmp_path) -> None:
    with SqliteMemory(tmp_path / "recencia.sqlite3") as mem:
        now = time.time()
        mem.import_records(
            [
                {"text": "versao velha do plano", "created_at": now - 300 * 86400},
                {"text": "versao nova do plano", "created_at": now - 60},
            ]
        )
        found = mem.recall("plano", k=2)
        assert found[0].text == "versao nova do plano"
        assert found[0].score > found[1].score


def test_uso_frequente_sobe_na_pontuacao(mem: SqliteMemory) -> None:
    mem.remember("vitamina d no café da manhã todos os dias")
    first = mem.recall("vitamina", k=1)[0].score
    second = mem.recall("vitamina", k=1)[0].score
    third = mem.recall("vitamina", k=1)[0].score
    assert second > first
    assert third > second
    fourth = mem.recall("vitamina", k=1)[0].score
    assert fourth > third  # use_count crescendo sobe a pontuação


def test_limites_de_k(mem: SqliteMemory) -> None:
    for index in range(7):
        mem.remember(f"assunto {index} {uuid.uuid4().hex}")
    assert len(mem.recall("assunto", k=3)) == 3
    assert mem.recall("assunto", k=0) == []
    assert mem.recall("assunto", k=-1) == []
    assert len(mem.recall("assunto", k=99)) == 7
    assert len(mem.recall("assunto", k=5)) == 5
    assert len(mem.recall("assunto", k="nao numero")) == 5  # vira o padrão 5


def test_consulta_vazia_devolve_mais_importantes(mem: SqliteMemory) -> None:
    mem.remember("registro pouco importante", importance=0.1)
    mem.remember("registro muito importante", importance=0.9)
    found = mem.recall("", k=2)
    assert len(found) == 2
    assert found[0].text == "registro muito importante"


def test_consulta_sem_resultados(mem: SqliteMemory) -> None:
    mem.remember("assunto completamente diferente")
    assert mem.recall("zqxjkv inexistente", k=5) == []


def test_fallback_like_sem_fts(tmp_path, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="aris.agent.memory.sqlite"):
        with SqliteMemory(tmp_path / "sem_fts.sqlite3", fts=False) as mem:
            assert mem.fts_enabled is False
            mem.remember("Configuração avançada do sistema")
            found = mem.recall("configuracao", k=3)
            assert [item.kind for item in found] == ["fact"]
            assert mem.recall("CONFIGURAÇÃO", k=3)
    assert "LIKE" in caplog.text


def test_sem_fts5_no_sqlite_avisa(caplog) -> None:
    class _SemFts5:
        def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise sqlite3.OperationalError("no such module: fts5")

    with caplog.at_level(logging.WARNING, logger="aris.agent.memory.schema"):
        ok = enable_fts(_SemFts5())
    assert ok is False
    assert "FTS5" in caplog.text
    assert "LIKE" in caplog.text


def test_reabrir_com_fts_faz_backfill(tmp_path) -> None:
    path = tmp_path / "backfill.sqlite3"
    with SqliteMemory(path, fts=False) as primeira:
        primeira.remember("registro gravado sem indice full text")
    with SqliteMemory(path) as segunda:
        assert segunda.fts_enabled is True
        found = segunda.recall("full text", k=3)
        assert [item.text for item in found] == ["registro gravado sem indice full text"]


def test_embedder_desligado_por_padrao(tmp_path) -> None:
    path = tmp_path / "sem_embedder.sqlite3"
    with SqliteMemory(path) as mem:
        assert mem.embedder is None
        item_id = mem.remember("item sem vetor")
        assert mem.get(item_id) is not None
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("SELECT emb FROM items").fetchone()
    finally:
        conn.close()
    assert row[0] is None


def test_embedder_ligado_guarda_e_pontua(tmp_path) -> None:
    embedder = FakeEmbedder()
    with SqliteMemory(tmp_path / "com_embedder.sqlite3", embedder=embedder) as mem:
        assert mem.embedder is embedder
        mem.remember("gato de estimação dorme na janela", kind="fact")
        mem.remember("receita de bolo de chocolate", kind="fact")
        found = mem.recall("gato janela", k=2)
        assert found
        assert 0.0 <= found[0].score <= 1.0
        assert embedder.calls, "embedder deveria ser usado em remember e recall"
    conn = sqlite3.connect(tmp_path / "com_embedder.sqlite3")
    try:
        rows = conn.execute("SELECT emb FROM items").fetchall()
    finally:
        conn.close()
    assert all(row[0] for row in rows), "vetores deveriam estar gravados"


def test_embedder_quebrado_nao_derruba(tmp_path) -> None:
    class _Quebrado:
        def embed(self, text: str) -> list[float]:
            raise RuntimeError("modelo indisponível")

    with SqliteMemory(tmp_path / "quebrado.sqlite3", embedder=_Quebrado()) as mem:
        item_id = mem.remember("registro com embedder quebrado")
        assert mem.get(item_id) is not None
        assert mem.recall("registro", k=3)
