"""Testes de turnos da conversa, sumarização com FakeLLM e import_records (Parte 4)."""

from __future__ import annotations

import time

import pytest

from aris_agent.contract.types import ChatMessage
from aris_agent.fakes import FakeLLM
from aris_agent.memory import SqliteMemory


@pytest.fixture
def mem(tmp_path):
    instance = SqliteMemory(tmp_path / "memory.sqlite3")
    yield instance
    instance.close()


def assistant(text: str) -> ChatMessage:
    return ChatMessage(role="assistant", content=text)


def test_add_e_recent_turns(mem: SqliteMemory) -> None:
    mem.add_turn("s1", "user", "olá")
    mem.add_turn("s1", "assistant", "olá! como vai?")
    mem.add_turn("s1", "user", "bem, e você?")
    turns = mem.recent_turns("s1", n=10)
    assert [turn.content for turn in turns] == ["olá", "olá! como vai?", "bem, e você?"]
    assert [turn.role for turn in turns] == ["user", "assistant", "user"]
    assert all(isinstance(turn, ChatMessage) for turn in turns)


def test_recent_turns_limita_e_isola_sessao(mem: SqliteMemory) -> None:
    for index in range(5):
        mem.add_turn("s1", "user", f"mensagem {index}")
    mem.add_turn("s2", "user", "de outra sessão")
    assert [turn.content for turn in mem.recent_turns("s1", 2)] == ["mensagem 3", "mensagem 4"]
    assert mem.recent_turns("s1", 0) == []
    assert [turn.content for turn in mem.recent_turns("s2")] == ["de outra sessão"]
    assert mem.recent_turns("sessao_inexistente") == []


def test_turno_com_role_invalido(mem: SqliteMemory) -> None:
    with pytest.raises(ValueError, match="papel inválido"):
        mem.add_turn("s1", "human", "oi")
    with pytest.raises(ValueError, match="session_id"):
        mem.add_turn("", "user", "oi")


def test_turno_vazio_ignorado(mem: SqliteMemory) -> None:
    mem.add_turn("s1", "user", "   ")
    assert mem.recent_turns("s1") == []


def test_summarize_respeita_keep_last(tmp_path) -> None:
    script = [assistant("Resumo: o usuário pediu ajuda com o computador.")]
    fake = FakeLLM(script)
    with SqliteMemory(tmp_path / "resumo.sqlite3") as mem:
        for index in range(15):
            mem.add_turn("s1", "user" if index % 2 == 0 else "assistant", f"mensagem {index}")
        episode_id = mem.summarize_old_turns("s1", fake, keep_last=10)
        assert episode_id is not None
        assert len(fake.calls) == 1, "LLM deve ser chamado uma única vez"
        restantes = mem.recent_turns("s1", n=100)
        assert [turn.content for turn in restantes] == [f"mensagem {index}" for index in range(5, 15)]
        item = mem.get(episode_id)
        assert item is not None and item.kind == "episode"
        assert "ajuda com o computador" in item.text
        transcript = fake.calls[0]["messages"][1].content
        assert "[user] mensagem 0" in transcript
        assert "mensagem 4" in transcript
        assert "mensagem 5" not in transcript  # os 10 últimos ficaram de fora


def test_summarize_sem_excesso_nao_chama_llm(tmp_path) -> None:
    fake = FakeLLM([assistant("não deveria ser usado")])
    with SqliteMemory(tmp_path / "sem_excesso.sqlite3") as mem:
        for index in range(3):
            mem.add_turn("s1", "user", f"mensagem {index}")
        assert mem.summarize_old_turns("s1", fake, keep_last=10) is None
        assert fake.calls == [], "LLM não deve ser chamado abaixo do limite"
        assert len(mem.recent_turns("s1", 100)) == 3


def test_summarize_keep_last_zero(tmp_path) -> None:
    fake = FakeLLM([assistant("episódio completo da conversa")])
    with SqliteMemory(tmp_path / "zero.sqlite3") as mem:
        for index in range(4):
            mem.add_turn("s1", "user", f"turno {index}")
        episode_id = mem.summarize_old_turns("s1", fake, keep_last=0)
        assert episode_id is not None
        assert mem.recent_turns("s1", 100) == []


def test_summarize_falha_do_llm_preserva_turnos(tmp_path) -> None:
    fake = FakeLLM([])  # roteiro esgotado -> ProviderError
    with SqliteMemory(tmp_path / "falha.sqlite3") as mem:
        for index in range(12):
            mem.add_turn("s1", "user", f"turno {index}")
        assert mem.summarize_old_turns("s1", fake, keep_last=10) is None
        assert len(mem.recent_turns("s1", 100)) == 12, "falha de LLM não pode perder turnos"


def test_summarize_sem_llm(tmp_path) -> None:
    with SqliteMemory(tmp_path / "sem_llm.sqlite3") as mem:
        mem.add_turn("s1", "user", "oi")
        with pytest.raises(ValueError, match="llm obrigatório"):
            mem.summarize_old_turns("s1", None, keep_last=0)  # type: ignore[arg-type]


def test_summarize_redige_o_resumo(tmp_path) -> None:
    fake = FakeLLM([assistant("O usuário revelou a chave gsk_zzz111222333 no meio da conversa.")])
    with SqliteMemory(tmp_path / "resumo_segredo.sqlite3") as mem:
        for index in range(3):
            mem.add_turn("s1", "user", f"conteúdo {index}")
        episode_id = mem.summarize_old_turns("s1", fake, keep_last=1)
        assert episode_id is not None
        item = mem.get(episode_id)
        assert item is not None
        assert "gsk_zzz111222333" not in item.text
        assert "[REDACTED]" in item.text


def test_summarize_exige_sessao(tmp_path) -> None:
    with SqliteMemory(tmp_path / "sessao.sqlite3") as mem:
        with pytest.raises(ValueError, match="session_id"):
            mem.summarize_old_turns("", FakeLLM([assistant("x")]), keep_last=0)


def test_import_records_idempotente(tmp_path) -> None:
    registros = [
        {"text": "usuário mora em Belo Horizonte", "kind": "fact", "tags": ["casa"]},
        {"text": "usuário prefere resposta curta", "kind": "preference"},
        {"text": "ao corrigir, guardar a lição", "kind": "lesson", "tags": ("aprender",)},
    ]
    with SqliteMemory(tmp_path / "import.sqlite3") as mem:
        primeira = mem.import_records(registros)
        assert primeira == {"created": 3, "updated": 0, "skipped": 0}
        assert mem.count() == 3
        segunda = mem.import_records(registros)
        assert segunda == {"created": 0, "updated": 3, "skipped": 0}
        assert mem.count() == 3, "rodar duas vezes não pode duplicar"
        found = mem.recall("mora belo horizonte", k=3)
        assert found and found[0].tags == ("casa",)


def test_import_records_pula_registros_ruins(tmp_path) -> None:
    with SqliteMemory(tmp_path / "import_ruim.sqlite3") as mem:
        stats = mem.import_records(
            [
                {"text": "registro válido"},
                {"text": "   "},
                {"outro": "formato"},
                "não é dict",
                None,
            ]
        )
        assert stats == {"created": 1, "updated": 0, "skipped": 4}
        assert mem.count() == 1
        assert mem.import_records(None) == {"created": 0, "updated": 0, "skipped": 0}


def test_import_records_coage_kind_desconhecido(tmp_path) -> None:
    with SqliteMemory(tmp_path / "import_kind.sqlite3") as mem:
        mem.import_records([{"text": "registro do ARIS antigo", "kind": "semantic"}])
        payload = mem.export_all()
        assert '"fact"' in payload
        assert "semantic" not in payload


def test_import_records_redige_segredos(tmp_path) -> None:
    with SqliteMemory(tmp_path / "import_segredo.sqlite3") as mem:
        mem.import_records([{"text": "token: gsk_abc999888777"}])
        payload = mem.export_all()
        assert "gsk_abc999888777" not in payload
        assert "[REDACTED]" in payload


def test_import_records_created_at_invalido_usa_agora(tmp_path) -> None:
    with SqliteMemory(tmp_path / "import_data.sqlite3") as mem:
        agora = time.time()
        mem.import_records(
            [
                {"text": "data quebrada", "created_at": "não é data"},
                {"text": "data futura", "created_at": -10},
            ]
        )
        items = mem.recall("data", k=5)
        assert len(items) == 2
        for item in items:
            assert item.created_at >= agora
