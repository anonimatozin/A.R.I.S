"""Testes de CRUD, deduplicação, privacidade e esquema da SqliteMemory (Parte 4)."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from aris_agent.config import AgentConfig
from aris_agent.contract.protocols import Memory
from aris_agent.memory import WIPE_CONFIRM_TOKEN, SqliteMemory, open_memory
from aris_agent.memory.textutil import clean_tags, normalize, similar


@pytest.fixture
def mem(tmp_path):
    instance = SqliteMemory(tmp_path / "memory.sqlite3")
    yield instance
    instance.close()


def test_aceita_o_protocolo_memory(mem: SqliteMemory) -> None:
    assert isinstance(mem, Memory)


def test_remember_e_recall(mem: SqliteMemory) -> None:
    item_id = mem.remember("Vinicius gosta de café coado", kind="preference", tags=("café",))
    found = mem.recall("café coado", k=3)
    assert [item.id for item in found] == [item_id]
    item = found[0]
    assert item.kind == "preference"
    assert item.tags == ("café",)
    assert item.score > 0
    assert "café" in item.text


def test_get_e_count(mem: SqliteMemory) -> None:
    item_id = mem.remember("fato qualquer sobre o dia")
    item = mem.get(item_id)
    assert item is not None and item.text == "fato qualquer sobre o dia"
    assert mem.count() == 1
    assert mem.get("id_que_nao_existe") is None
    assert mem.get("") is None


def test_forget(mem: SqliteMemory) -> None:
    item_id = mem.remember("apague isto depois")
    assert mem.forget(item_id) is True
    assert mem.forget(item_id) is False
    assert mem.forget("") is False
    assert mem.count() == 0
    assert mem.recall("apague") == []


def test_texto_vazio_recusado(mem: SqliteMemory) -> None:
    with pytest.raises(ValueError, match="vazio"):
        mem.remember("")
    with pytest.raises(ValueError, match="vazio"):
        mem.remember("    \n  ")
    with pytest.raises(ValueError, match="vazio"):
        mem.remember(None)  # type: ignore[arg-type]


def test_texto_longo_recusado(tmp_path) -> None:
    with SqliteMemory(tmp_path / "curto.sqlite3", max_text_chars=50) as mem:
        with pytest.raises(ValueError, match="muito longo"):
            mem.remember("x" * 51)
        assert mem.remember("y" * 50)


def test_kind_invalido_recusado(mem: SqliteMemory) -> None:
    with pytest.raises(ValueError, match="kind inválido"):
        mem.remember("texto ok", kind="coisa")
    assert mem.count() == 0


def test_dedup_acentos_e_caixa(mem: SqliteMemory) -> None:
    first = mem.remember("Usuário prefere café com açúcar", kind="preference")
    second = mem.remember("usuario prefere cafe com acucar", kind="preference")
    assert first == second
    assert mem.count() == 1


def test_dedup_texto_quase_igual(mem: SqliteMemory) -> None:
    first = mem.remember("O usuário prefere café com leite")
    second = mem.remember("usuario prefere cafe com leite.")  # pontuação e "o" sobrando
    third = mem.remember("USUARIO PREFERE CAFE COM LEITE")
    assert first == second == third
    assert mem.count() == 1


def test_dedup_nao_funde_textos_diferentes(mem: SqliteMemory) -> None:
    mem.remember("reunião de segunda sobre o projeto ARIS")
    mem.remember("receita de bolo de cenoura com cobertura")
    assert mem.count() == 2


def test_dedup_limiar_configuravel(tmp_path) -> None:
    with SqliteMemory(tmp_path / "rigida.sqlite3", dedup_threshold=0.99) as mem:
        mem.remember("usuario prefere cafe com leite")
        mem.remember("o usuario prefere cafe com leite")  # ~0.96 < 0.99
        assert mem.count() == 2


def test_dedup_merge_tags_e_importance(mem: SqliteMemory) -> None:
    item_id = mem.remember("Vinicius dirige de manhã", kind="fact", tags=("rotina",))
    mem.remember("vinicius dirige de manha", tags=("trânsito",), importance=0.9)
    item = mem.get(item_id)
    assert item is not None
    assert item.tags == ("rotina", "trânsito")
    assert mem.count() == 1


def test_redacao_de_chave_antes_de_gravar(mem: SqliteMemory) -> None:
    item_id = mem.remember("chave da API do projeto é gsk_abc123def456ghi")
    item = mem.get(item_id)
    assert item is not None
    assert "[REDACTED]" in item.text
    assert "gsk_abc123def456ghi" not in item.text


def test_redacao_de_senha_em_turno(mem: SqliteMemory) -> None:
    mem.add_turn("sessao1", "user", "meu senha=hunter2 para tudo")
    turns = mem.recent_turns("sessao1")
    assert turns
    assert "hunter2" not in turns[0].content
    assert "[REDACTED]" in turns[0].content


def test_wipe_exige_token(mem: SqliteMemory) -> None:
    mem.remember("item que deve sobreviver ao token errado")
    mem.add_turn("s1", "user", "oi")
    with pytest.raises(ValueError, match="token"):
        mem.wipe_all("apagar tudo")  # caixa/acentos diferentes do token
    assert mem.count() == 1
    assert len(mem.recent_turns("s1", 10)) == 1


def test_wipe_apaga_tudo_com_token(mem: SqliteMemory) -> None:
    mem.remember("um")
    mem.remember("dois")
    mem.add_turn("s1", "user", "oi")
    removed = mem.wipe_all(WIPE_CONFIRM_TOKEN)
    assert removed == 2
    assert mem.count() == 0
    assert mem.recent_turns("s1", 10) == []
    payload = json.loads(mem.export_all())
    assert payload["itens"] == [] and payload["turnos"] == []


def test_export_all_json(mem: SqliteMemory) -> None:
    mem.remember("item exportável", tags=("export",))
    mem.add_turn("s1", "assistant", "resposta pronta")
    payload = json.loads(mem.export_all())
    assert payload["formato"] == "aris_agent.memoria.v1"
    assert payload["schema_version"] == 1
    texts = [item["text"] for item in payload["itens"]]
    assert "item exportável" in texts
    assert payload["itens"][0]["tags"] == ["export"]
    assert payload["turnos"][0]["content"] == "resposta pronta"
    sem_turnos = json.loads(mem.export_all(include_turns=False))
    assert sem_turnos["turnos"] == []


def test_esquema_versionado_no_meta(tmp_path) -> None:
    path = tmp_path / "versionado.sqlite3"
    with SqliteMemory(path) as mem:
        mem.remember("algo")
        assert mem.schema_version == 1
    conn = sqlite3.connect(path)
    try:
        raw = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
    finally:
        conn.close()
    assert raw is not None and raw[0] == "1"


def test_recusa_banco_de_esquema_mais_novo(tmp_path) -> None:
    path = tmp_path / "futuro.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta VALUES ('schema_version', '99')")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="esquema"):
        SqliteMemory(path)


def test_persiste_entre_sessoes(tmp_path) -> None:
    path = tmp_path / "persistente.sqlite3"
    with SqliteMemory(path) as primeira:
        item_id = primeira.remember("lembrança persistente da ARIS")
    with SqliteMemory(path) as segunda:
        assert segunda.count() == 1
        found = segunda.recall("lembrança persistente")
        assert [item.id for item in found] == [item_id]


def test_context_manager_fecha(tmp_path) -> None:
    with SqliteMemory(tmp_path / "ctx.sqlite3") as memoria:
        memoria.remember("algo para lembrar")
        assert memoria.count() == 1
    with pytest.raises(RuntimeError, match="fechada"):
        memoria.count()


def test_banco_em_memoria(tmp_path) -> None:
    with SqliteMemory(":memory:") as memoria:
        assert memoria.path == ":memory:"
        item_id = memoria.remember("registro só na memória")
        memoria.add_turn("s1", "user", "oi")
        assert memoria.count() == 1
        assert [item.id for item in memoria.recall("memoria")] == [item_id]
        assert len(memoria.recent_turns("s1")) == 1


def test_banco_padrao_no_data_dir(tmp_path) -> None:
    cfg = AgentConfig(workspace_dir=tmp_path / "ws", data_dir=tmp_path / "dados")
    memoria = open_memory(cfg)
    try:
        assert memoria.path == tmp_path / "dados" / "memory.sqlite3"
        assert Path(memoria.path).exists()
        memoria.remember("gravado no data_dir")
    finally:
        memoria.close()


def test_open_memory_lê_seção_memory(tmp_path) -> None:
    cfg = AgentConfig(
        workspace_dir=tmp_path / "ws",
        data_dir=tmp_path / "dados",
        sections={"memory": {"max_text_chars": 10, "fts": False}},
    )
    memoria = open_memory(cfg)
    try:
        assert memoria.max_text_chars == 10
        assert memoria.fts_enabled is False
        with pytest.raises(ValueError, match="muito longo"):
            memoria.remember("texto bem maior que dez")
    finally:
        memoria.close()


def test_open_memory_config_ruina_usa_padrao(tmp_path) -> None:
    cfg = AgentConfig(
        workspace_dir=tmp_path / "ws",
        data_dir=tmp_path / "dados",
        sections={"memory": {"max_text_chars": "abc", "fts": "sim"}},
    )
    memoria = open_memory(cfg)
    try:
        assert memoria.max_text_chars == 2000
        assert memoria.fts_enabled is True
    finally:
        memoria.close()


# ------------------------------------------------------------------ textutil


def test_normalize_ignora_acento_caixa_e_pontuacao() -> None:
    assert normalize("Configuração, TÉCNICA!") == "configuracao tecnica"
    assert normalize("  multi   espaço \n") == "multi espaco"


def test_similar_distingue_textos() -> None:
    assert similar("abc", "abc") is True
    assert similar("prefere cafe", "prefere cafe com leite") is False
    assert similar("", "") is False  # vazio nunca é "quase igual" a nada além de si


def test_clean_tags() -> None:
    assert clean_tags("casa, trabalho , casa") == ("casa", "trabalho")
    assert clean_tags(("a", None, "  ", "b")) == ("a", "b")
    assert clean_tags(None) == ()
    assert clean_tags(123) == ()


def test_import_records_respeita_created_at(tmp_path) -> None:
    with SqliteMemory(tmp_path / "import_ts.sqlite3") as mem:
        epoch = time.time() - 400 * 86400
        mem.import_records([{"text": "registro antigo do ARIS", "created_at": epoch}])
        payload = json.loads(mem.export_all())
        assert payload["itens"][0]["created_at"] == pytest.approx(epoch)
        iso = mem.import_records(
            [{"text": "registro em iso", "created_at": "2020-05-05T12:00:00"}]
        )
        assert iso["created"] == 1
