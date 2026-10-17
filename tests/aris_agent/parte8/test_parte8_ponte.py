"""Parte 8 — ponte ponta a ponta com FakeLLM: roteio, kill, confirmação, queda."""

from __future__ import annotations

from types import SimpleNamespace

from aris_agent.bridge import build_bridge
from aris_agent.bridge.ponte import FALA_DE_ERRO, FALA_DE_PARADA
from aris_agent.config import AgentConfig
from aris_agent.contract.types import ChatMessage, ToolCall
from aris_agent.fakes import FakeLLM


def _montar(tmp_path, script, *, ouvir_resposta=None):
    """Monta a ponte ligada (cfg.agent_enabled=True) com FakeLLM roteirizado."""
    cfg = AgentConfig(
        workspace_dir=tmp_path / "ws",
        data_dir=tmp_path / "data",
        agent_enabled=True,
        max_steps=6,
        sections={},
    )
    falado: list[str] = []

    def falar(texto: str, *, sync: bool = False) -> None:
        falado.append(texto)

    def ouvir(_timeout_s: float) -> str | None:
        return ouvir_resposta

    ponte = build_bridge(falar=falar, ouvir=ouvir, cfg=cfg, llm=FakeLLM(script))
    assert ponte is not None, "a ponte deveria ter sido construída"
    return ponte, falado


def _assistant(texto: str) -> ChatMessage:
    return ChatMessage(role="assistant", content=texto)


def _tool_call(nome: str, arguments: dict) -> ChatMessage:
    return ChatMessage(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id="c1", name=nome, arguments=arguments)],
    )


# ------------------------------------------------------------------ roteio


def test_conversa_segue_o_caminho_antigo(tmp_path) -> None:
    llm = FakeLLM([_assistant("não devo ser chamado")])
    cfg = AgentConfig(
        workspace_dir=tmp_path / "ws",
        data_dir=tmp_path / "data",
        agent_enabled=True,
        sections={},
    )
    ponte = build_bridge(
        falar=lambda _t, *, sync=False: None,
        ouvir=lambda _t: None,
        cfg=cfg,
        llm=llm,
    )
    assert ponte.processar("me conta uma piada") is None
    assert ponte.processar("bom dia, aris") is None
    assert llm.calls == [], "conversa não pode acionar o agente"


def test_tarefa_vai_para_o_agente_e_devolve_texto(tmp_path) -> None:
    ponte, falado = _montar(tmp_path, [_assistant("Claro, chefe: uma piada sobre código.")])
    resposta = ponte.processar("apaga o arquivo teste.txt")
    assert resposta == "Claro, chefe: uma piada sobre código."
    assert falado == [], "sem ferramenta não há fala de status"


def test_processar_com_origin_usa_o_user_id(tmp_path) -> None:
    ponte, _ = _montar(tmp_path, [_assistant("ok")])
    origem = SimpleNamespace(user_id="dev")
    assert ponte.processar("pesquisa as noticias de hoje", origin=origem) == "ok"


def test_texto_vazio_retorna_none(tmp_path) -> None:
    ponte, _ = _montar(tmp_path, [])
    assert ponte.processar("   ") is None


# ------------------------------------------------------------------- kill


def test_frase_de_parada_engata_o_kill_switch(tmp_path) -> None:
    ponte, _ = _montar(tmp_path, [])
    assert ponte.processar("aris, para tudo") == FALA_DE_PARADA
    assert ponte.kill_switch.engaged


def test_depois_de_parar_agente_fica_quieto(tmp_path) -> None:
    ponte, _ = _montar(tmp_path, [])
    ponte.processar("para tudo")
    # tarefa que normalmente iria ao agente agora cai no caminho antigo
    assert ponte.processar("apaga o arquivo teste.txt") is None
    # e a ordem de parada continua sendo respondida
    assert ponte.processar("pare tudo") == FALA_DE_PARADA


def test_parar_no_shutdown_engata(tmp_path) -> None:
    ponte, _ = _montar(tmp_path, [])
    ponte.parar()
    assert ponte.kill_switch.engaged


# ---------------------------------------------------- confirmação e ferramenta


def _arquivo_alvo(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    alvo = ws / "alvo.txt"
    alvo.write_text("conteudo", encoding="utf-8")
    return alvo


def test_confirmacao_negada_bloqueia_ferramenta(tmp_path) -> None:
    alvo = _arquivo_alvo(tmp_path)
    script = [
        _tool_call("pc_delete_file", {"path": str(alvo)}),
        _assistant("Você não confirmou; não apaguei nada."),
    ]
    ponte, falado = _montar(tmp_path, script, ouvir_resposta=None)  # timeout = negar
    resposta = ponte.processar("apaga o arquivo alvo.txt")
    assert resposta == "Você não confirmou; não apaguei nada."
    assert alvo.exists(), "confirmação negada não pode apagar"
    # DESTRUCTIVE é confirmação forte: a fala avisa que é ação destrutiva
    assert any("destrutiva" in f.lower() for f in falado), "tinha que falar a confirmação"


def test_confirmacao_sim_executa_e_fala_status(tmp_path) -> None:
    alvo = _arquivo_alvo(tmp_path)
    script = [
        _tool_call("pc_delete_file", {"path": str(alvo)}),
        _assistant("Arquivo enviado para a Lixeira, chefe."),
    ]
    ponte, falado = _montar(tmp_path, script, ouvir_resposta="sim")
    resposta = ponte.processar("apaga o arquivo alvo.txt")
    assert resposta == "Arquivo enviado para a Lixeira, chefe."
    assert not alvo.exists(), "com confirmação o arquivo deve sumir"
    assert any("apagando" in f for f in falado), "status da ferramenta devia ser falado"
    assert any("destrutiva" in f.lower() for f in falado), "tinha que falar a confirmação"


def test_perigo_sem_resposta_do_chefe_nega_mesmo_hard(tmp_path) -> None:
    alvo = _arquivo_alvo(tmp_path)
    script = [
        _tool_call("pc_delete_file", {"path": str(alvo)}),
        _assistant("Sem confirmação eu não faço."),
    ]
    ponte, _ = _montar(tmp_path, script, ouvir_resposta="talvez...")
    ponte.processar("apaga o arquivo alvo.txt sem perguntar nada")
    assert alvo.exists()


# ------------------------------------------------------- quebras e fronteiras


def test_llm_sem_roteiro_vira_resposta_nao_excecao(tmp_path) -> None:
    ponte, _ = _montar(tmp_path, [])  # primeira chamada já explode
    resposta = ponte.processar("apaga o arquivo teste.txt")
    assert isinstance(resposta, str) and resposta, "agente quebrado precisa responder"


def test_excecao_na_tarefa_vira_fala_de_erro(tmp_path) -> None:
    ponte, _ = _montar(tmp_path, [])

    class _Bomb:
        def run(self, *_args, **_kwargs):
            raise RuntimeError("explode")

    ponte._agente = _Bomb()  # defesa de fronteira: nunca propaga
    assert ponte.processar("apaga o arquivo teste.txt") == FALA_DE_ERRO


def test_build_bridge_desligado_devolve_none(tmp_path) -> None:
    cfg = AgentConfig(
        workspace_dir=tmp_path / "ws",
        data_dir=tmp_path / "data",
        agent_enabled=False,  # interruptor desligado (padrão)
        sections={},
    )
    ponte = build_bridge(
        falar=lambda _t, *, sync=False: None,
        ouvir=lambda _t: None,
        cfg=cfg,
        llm=FakeLLM([_assistant("não deveria rodar")]),
    )
    assert ponte is None


def test_build_bridge_sem_provedores_devolve_none(tmp_path) -> None:
    cfg = AgentConfig(
        workspace_dir=tmp_path / "ws",
        data_dir=tmp_path / "data",
        agent_enabled=True,
        sections={},
    )
    ponte = build_bridge(
        falar=lambda _t, *, sync=False: None,
        ouvir=lambda _t: None,
        cfg=cfg,
        llm=None,  # sem FakeLLM e sem seção "llm": fábrica recusa com aviso
    )
    assert ponte is None
