"""Parte 8 — roteamento: parada de emergência, intenção e recados longos."""

from __future__ import annotations

from aris_agent.bridge.rota import Roteador, normalizar
from aris_agent.evals.intents import carregar_dataset

# (entrada, decisão esperada) — casos limpos do contrato do roteador
CASOS_LIMPOS = [
    ("apaga o arquivo teste.txt", "agente"),
    ("pesquisa as noticias de hoje sobre tech", "agente"),
    ("formata o disco", "agente"),
    ("me conta uma piada", "conversa"),
    ("bom dia, aris", "conversa"),
    ("qual é a capital da frança", "conversa"),
]

MAPEAMENTO_ESPERADO = {
    "comando_pc": "agente",
    "pesquisa": "agente",
    "perigoso": "agente",
    "conversa": "conversa",
    "pergunta": "conversa",
    "recado_ideia": "conversa",
}


def test_normalizar_sem_acentos_e_caixa() -> None:
    assert normalizar("  ÁRIS,  PARA Tudo ") == "aris, para tudo"
    # a pontuação não é removida aqui (cada caçador trata a sua)
    assert normalizar("  ÁRIS,  PARA Tudo!! ") == "aris, para tudo!!"
    # ...e o caçador de parada ainda encontra a frase com pontuação
    assert Roteador().eh_de_parada("ÁRIS, PARA TUDO!!!")


def test_decidir_casos_limpos() -> None:
    rota = Roteador()
    for entrada, esperado in CASOS_LIMPOS:
        assert rota.decidir(entrada) == esperado, entrada


def test_frase_de_parada_curta_dispara() -> None:
    rota = Roteador()
    for frase in ("aris, para tudo", "PARE TUDO", "cancela tudo agora", "chega disso"):
        assert rota.eh_de_parada(frase), frase


def test_frase_de_parada_negativos() -> None:
    rota = Roteador()
    assert not rota.eh_de_parada("")
    assert not rota.eh_de_parada("eu paro tudo que me pedem, né")
    # mesmo contendo a frase, texto longo demais não é ordem de parada
    longa = "para tudo isso que eu já falei com você " * 3
    assert not rota.eh_de_parada(longa)


def test_recado_longo_nao_vira_comando() -> None:
    # gate de tamanho: com limite baixo, tarefa curta vira conversa
    rota = Roteador(max_chars_tarefa=10)
    assert rota.decidir("apaga o arquivo teste.txt") == "conversa"
    # padrão: frases longas (>160 chars) seguem o caminho de conversa
    longa = ("apaga o arquivo teste.txt. " * 10).strip()
    assert len(longa) > 160
    assert Roteador().decidir(longa) == "conversa"


def test_entrada_vazia_e_erro_de_classificador_vao_para_conversa() -> None:
    rota = Roteador()
    assert rota.decidir("   ") == "conversa"


def test_perigoso_longo_ainda_vai_para_agente() -> None:
    """Segurança não espera o gate de tamanho: perigoso sempre vai ao agente."""
    pares = [
        (t, r) for t, r in carregar_dataset()
        if r == "perigoso" and len(t) > 160
    ]
    rota = Roteador()
    for texto, _rotulo in pares:
        assert rota.decidir(texto) == "agente", texto


def test_decisao_no_dataset_bate_meta() -> None:
    """O roteador inteiro (classificador + gates) precisa acertar ≥90%."""
    rota = Roteador()
    pares = carregar_dataset()
    acertos = sum(
        1
        for texto, rotulo in pares
        if rota.decidir(texto) == MAPEAMENTO_ESPERADO[rotulo]
    )
    taxa = acertos / len(pares)
    assert taxa >= 0.90, f"decisão de rota em {taxa:.3f} < 0.90"

    perigosos = [(t, r) for t, r in pares if r == "perigoso"]
    no_agente = sum(1 for texto, _ in perigosos if rota.decidir(texto) == "agente")
    assert no_agente / len(perigosos) >= 0.95, (
        f"perigoso roteado para agente: {no_agente}/{len(perigosos)}"
    )
