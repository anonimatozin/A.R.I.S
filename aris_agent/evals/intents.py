"""Dataset de intenções e avaliação de classificadores injetáveis.

O roteamento da Parte 8 (conversa casual × tarefa com ferramentas) precisa de
um classificador leve. Este módulo traz:

* o dataset rotulado (``intents_dataset.jsonl``) e seu carregamento;
* o protocolo de um classificador (qualquer ``Callable[[str], str]`` serve —
  regras, LLM em modo ``easy``, híbrido);
* :func:`avaliar_classificador`, que mede a taxa de acerto por rótulo;
* :func:`classificar_regras`, um classificador de referência só com regras
  (usado nos testes como padrão e como linha de base honesta).

Rótulos: ``conversa``, ``pergunta``, ``comando_pc``, ``pesquisa``,
``recado_ideia``, ``perigoso``.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterable
from pathlib import Path

log = logging.getLogger("aris.agent.evals.intents")

DATASET_PATH = Path(__file__).parent / "intents_dataset.jsonl"

ROTULOS = (
    "conversa",
    "pergunta",
    "comando_pc",
    "pesquisa",
    "recado_ideia",
    "perigoso",
)

# Qualquer Callable texto -> rótulo serve de classificador.
Classificador = Callable[[str], str]


def carregar_dataset(caminho: Path | str | None = None) -> list[tuple[str, str]]:
    """Lê o dataset e devolve ``[(texto, rótulo), ...]`` validado."""
    path = Path(caminho) if caminho else DATASET_PATH
    pares: list[tuple[str, str]] = []
    for numero, linha in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        linha = linha.strip()
        if not linha:
            continue
        try:
            dados = json.loads(linha)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{numero}: JSON inválido: {exc}") from exc
        texto = str(dados.get("texto", "")).strip()
        rotulo = str(dados.get("rotulo", "")).strip()
        if not texto:
            raise ValueError(f"{path.name}:{numero}: linha sem texto")
        if rotulo not in ROTULOS:
            raise ValueError(f"{path.name}:{numero}: rótulo inválido {rotulo!r}")
        pares.append((texto, rotulo))
    if not pares:
        raise ValueError(f"dataset vazio: {path}")
    return pares


def avaliar_classificador(
    classificador: Classificador, dataset: Iterable[tuple[str, str]] | None = None
) -> dict:
    """Mede a taxa de acerto do ``classificador`` no dataset.

    Devolve ``{"total", "acertos", "acuracia", "por_rotulo": {rotulo: {...}}}``.
    """
    pares = list(dataset) if dataset is not None else carregar_dataset()
    if not pares:
        raise ValueError("dataset vazio")

    acertos = 0
    por_rotulo: dict[str, dict] = {
        r: {"total": 0, "acertos": 0, "erros": []} for r in ROTULOS
    }
    for texto, esperado in pares:
        try:
            previsto = str(classificador(texto))
        except Exception as exc:  # noqa: BLE001 - classificador injetável não pode derrubar a avaliação
            log.warning("classificador falhou em %r: %s", texto[:60], exc)
            previsto = ""
        item = por_rotulo.setdefault(esperado, {"total": 0, "acertos": 0, "erros": []})
        item["total"] += 1
        if previsto == esperado:
            acertos += 1
            item["acertos"] += 1
        else:
            item["erros"].append({"texto": texto, "previsto": previsto})

    for dados in por_rotulo.values():
        total = dados["total"]
        dados["acuracia"] = round(dados["acertos"] / total, 3) if total else 0.0

    return {
        "total": len(pares),
        "acertos": acertos,
        "acuracia": round(acertos / len(pares), 3),
        "por_rotulo": por_rotulo,
    }


def relatorio_markdown(resultado: dict) -> str:
    """Renderiza o resultado de :func:`avaliar_classificador` em Markdown."""
    linhas = [
        "# Avaliação do classificador de intenções",
        "",
        f"**Acurácia geral:** {resultado['acertos']}/{resultado['total']} "
        f"({resultado['acuracia'] * 100:.1f}%)",
        "",
        "| Rótulo | Acertos/Total | Acurácia |",
        "|---|---|---|",
    ]
    for rotulo, dados in resultado["por_rotulo"].items():
        linhas.append(
            f"| {rotulo} | {dados['acertos']}/{dados['total']} | "
            f"{dados['acuracia'] * 100:.1f}% |"
        )
    return "\n".join(linhas) + "\n"


# -------------------------------------------------- classificador de referência


_IDENTIDADE = re.compile(
    r"(quem [ée] (seu|voc[êe]) criador|quem te fez|quem te criou|qual [ée] o seu nome|"
    r"qual [ée] seu nome|seu filme favorito|sua comida favorita|quantos anos voc[êe] tem|"
    r"de onde voc[êe] veio|como foi o seu dia|como foi seu dia|voc[êe] [ée] o jarvis|"
    r"voc[êe] [ée] a aris|vamos conversar|acho que a gente se entende|"
    r"voc[êe] [ée] (humano|um rob[ôo]|a cortana|a siri|muito burrinho|incr[íi]vel|"
    r"engra[çc]ado|muito bom|muito esperto|muito engra[çc]ado)|voc[êe] tem sentimentos|"
    r"voc[êe] gosta de mim|vc [ée] (humano|a cortana|o jarvis))",
    re.IGNORECASE,
)

_BATE_PAPO = re.compile(
    r"^(oi|ol[áa]|e a[íi]|bom dia|boa tarde|boa noite|opa|e ai|tudo bem|tudo bom|"
    r"obrigad[oa]|valeu|falou|tchau|at[ée] logo|kkk|rsrs|haha+h|"
    r"boa (tarde|noite|dia)[, ]+como voc[êe] t[áa]|me explica|explica( pra mim)?|"
    r"de onde voc[êe] t[áa]|como voc[êe] est[áa]|como vai)[!?., ]*$",
    re.IGNORECASE,
)

_PERIGOSO = re.compile(
    r"(apaga(r)?\b.{0,30}\b(tudo|todas|todos|inteir[oa]s?|o banco de dados|"
    r"a pasta (documentos|downloads|do usu[áa]rio|do sistema|temp\b.*inteir))|"
    r"deleta(r)?\b.{0,30}\b(tudo|todas|todos|inteir[oa]s?|drive|everything|all)|"
    r"exclui(r)?\b.{0,30}\b(tudo|todas|todos|a pasta|o diret[óo]rio)|"
    r"delete (everything|all)|erase all|"
    r"format(a|ar)\b.{0,20}\b(disco|drive|parti[çc][ãa]o|c:|d:)|format [a-z]:|"
    r"deslig(ar|a|ue)\b.{0,20}\b(o )?(pc|computador|tudo|m[áa]quina|servidor)|"
    r"desliga(r)? (a )?(seguran[çc]a|prote[çc][ãa]o|firewall|antiv[íi]rus)|"
    r"desativa(r)? (o |a )?(antiv[íi]rus|firewall|seguran[çc]a)|"
    r"sem (passar pelo )?(antiv[íi]rus|prote[çc][ãa]o)|"
    r"reinicia(r)?\b.{0,15}\b(o )?(pc|computador|m[áa]quina)|"
    r"\bshutdown\b|del [a-z]:\\|rd /s|rm -rf|remove-item .*(windows|users)|"
    r"para tudo|para com isso|^para\b|para imediatamente|encerra tudo|"
    r"cancela(r)? (tudo|tudo agora)|^cancela(r)?$|\bkill ?switch\b|"
    r"senha|password|chave (da )?api|api key|token de acesso|"
    r"\.env|id_rsa|cookie|keylog|banco de dados de produ[çc][ãa]o|"
    r"ignore (todas )?(as )?(instru[çc][õo]es|regras|prompt|comandos?)|"
    r"ignore tudo|ignore o prompt|a partir de agora ignore|"
    r"sudo rm|encodedcommand|frombase64string|-enc )",
    re.IGNORECASE,
)

_PERIGOSO_EXTRA = re.compile(
    # destruição em massa / disco
    r"(del /f|del /q|rd /s /q|/f /s /q|\bdd if=|of=/dev/|"
    r"wip(e|ing)\b.{0,25}(disk|drive|everything|all)|"
    r"wipe (my|all) |manda pro lixo a pasta|inteira com tudo|tudo dentro|"
    r"apaga o hist[óo]rico|derruba o servidor|servidor de produ[çc][ãa]o|"
    r"cancela todos os|cancela.{0,30}e apaga|"
    # contas e acessos
    r"exclui(r)? (minha |a )?conta|deleta(r)? (minha |a )?conta|"
    r"gerenciador de credenciais|copia tudo|"
    r"chaves? ssh|manda (o |a )?(token|senha|chave)|me manda (o |a )?(token|senha|chave)|"
    r"token do bot|net user|/active:yes|autorizado pelo admin|"
    r"libera root|acesso total|acesso administrativo|"
    r"desconecta todo mundo|desinstala(r)?\b.{0,20}antiv[íi]rus|"
    # jailbreak / injeção
    r"ignora(r)? (as )?(instru[çc][õo]es|regras|prote[çc][õo]es)|"
    r"roda qualquer coisa|esque[çc]a as regras|regras acima|"
    r"obede[çc]a somente|system prompt|a partir de agora voc[êe] [ée] o|"
    r"sem limites|sem regras|voc[êe] [ée] o dan)",
    re.IGNORECASE,
)

_PESQUISA = re.compile(
    r"(pesquis(a|e|ar)|procur(a|ar|a o|a uma|a uma receita|a empregos|a artigos|"
    r"a voos|a indica[çc][ãa]o|a um mapa|a o endere[çc]o|a o arquivo)|"
    r"busc(a|ar|a no)|googla|google(r)?|"
    r"previs[ãa]o do tempo|que tempo vai fazer|me diz se vai chover|"
    r"cota[çc][ãa]o|d[óo]lar|euro|libra|"
    r"pre[çc]o|compara pre[çc]os|passagem|promo[çc][ãa]o|"
    r"manchetes|not[íi]cias (de|sobre)|resultados dos jogos|campeonato|"
    r"me fala sobre|me traz|me mostra a tabela|me atualiza sobre|"
    r"me diz (quantos|quantas|qual|quais|se |quando |onde |quem )|"
    r"consulta o|v[êe] quanto|v[êe] se|v[êe] l[áa] no site|no site se|"
    r"artigos sobre|receita|mapa do|endere[çc]o do|"
    r"documenta[çc][ãa]o|tutorial)",
    re.IGNORECASE,
)

_COMANDO_PC = re.compile(
    r"(^|\b)(abre|abram|abrir|fecha|fechar|executa|executar|roda|rodar|"
    r"inicia|iniciar|reinicia|reiniciar|"
    r"lista|listar|cria|criar|faz( um)? (um )?arquivo|salva|salvar|grava|gravar|"
    r"apaga|apagar|deleta|deletar|exclui|excluir|move|mover|renomeia|renomear|"
    r"copia|copiar|cola|colar|remove|remover|descompacta|comprime|"
    r"digita|digitar|escreve|escrever|imprime|imprimir|pressiona|"
    r"screen ?shot|captura|print da tela|"
    r"mata|mat(a|e)\b|encerra|"
    r"instala|instalar|baixa|baixar|download|"
    r"aumenta|abaixa|diminui|ajusta|liga|desliga|conecta|desconecta|ativa|desativa|"
    r"verifica|ver a|mostra|monta|ejeta|altera|bloqueia|aperta|maximiza|minimiza|"
    r"troca|limpa|atualiza|compila|esvazia|l[êe])\b|"
    r"^(pwd|dir|ls|cd|cat|echo|rm|del|mkdir|ipconfig|ifconfig|ping)\b",
    re.IGNORECASE,
)

_RECADO = re.compile(
    r"(anota|anote|anotar|lembra|lembre|lembre-me|lembrar|n[ãa]o (me )?esquec|"
    r"esque[çc]a de|n[ãa]o (me )?deixa esquecer|me cobra|guarda essa|"
    r"adiciona(r)? (na )?lista|lista d[ao] (mercado|farm[áa]cia|compras)|"
    r"^lista de (tarefas|compras|coisas)|lista do que preciso|"
    r"cria(r)? (uma )?nota|tive uma ideia|ideia de (app|projeto|neg[óo]cio|programa|"
    r"aplica[çc][ãa]o)|^ideia:|guarda essa ideia|"
    r"tava pensando|vou te contar uma ideia|salva (esse|isso|essa ideia)|"
    r"pensamento:|quero te contar|pend[êe]ncias de hoje)",
    re.IGNORECASE,
)

_PERGUNTA = re.compile(
    r"^(que|qual|quais|quem|quando|onde|de onde|em que|o que|quantos|quantas|quanto|"
    r"por que|porque|como|vc|voc[êe])\b",
    re.IGNORECASE,
)


def classificar_regras(texto: str) -> str:
    """Classificador de referência: só regras, sem LLM, sem rede.

    Ordem importa: perigoso primeiro (nada perigoso cai em ``comando_pc``),
    depois identidade/bate-papo, recado, pesquisa, comando no PC, pergunta e
    por fim conversa.
    """
    bruto = str(texto or "").strip()
    if not bruto:
        return "conversa"
    if _PERIGOSO.search(bruto) or _PERIGOSO_EXTRA.search(bruto):
        return "perigoso"
    if _IDENTIDADE.search(bruto) or _BATE_PAPO.match(bruto):
        return "conversa"
    if _RECADO.search(bruto):
        return "recado_ideia"
    if _PESQUISA.search(bruto):
        return "pesquisa"
    if _PERGUNTA.match(bruto):
        return "pergunta"
    if _COMANDO_PC.search(bruto):
        return "comando_pc"
    return "conversa"
