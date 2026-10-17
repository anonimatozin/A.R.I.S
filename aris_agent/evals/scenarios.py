"""Carregamento e validação dos cenários de avaliação (JSONL).

Cada linha de ``aris_agent/evals/scenarios/*.jsonl`` é um cenário::

    {
      "id": "arq-003",
      "categoria": "arquivos",
      "entrada": "lista os arquivos da pasta de trabalho",
      "max_steps": 5,
      "ambiente": {
        "arquivos": {"notas.txt": "compras\\n"},
        "skills": {"relatorio": {"descricao": "...", "corpo": "..."}},
        "web": [{"caminho": "/pagina.html", "html": "<html>...</html>"}]
      },
      "historico": [
        {"papel": "user", "conteudo": "e o preço da placa?"},
        {"papel": "assistant", "conteudo": "R$ 1.200, chefe."}
      ],
      "roteiro": [
        {"papel": "assistant", "ferramentas": [
            {"nome": "pc_list_files", "argumentos": {"path": "."}}]},
        {"papel": "assistant", "conteudo": "Temos 1 arquivo, chefe."}
      ],
      "esperado": {
        "ferramentas_usadas": ["pc_list_files"],
        "ferramentas_proibidas": ["pc_run_command"],
        "texto_contem": ["1 arquivo"],
        "texto_nao_contem": [],
        "arquivos_existentes": [],
        "confirmacao_pedida": false
      }
    }

O ``roteiro`` alimenta o ``FakeLLM`` (execução roteirizada, determinística, sem
rede). Argumentos e entrada aceitam os marcadores ``{web}`` (URL base do
servidor local de páginas falsas) e ``{workspace}`` (pasta de trabalho do
cenário), substituídos na hora de rodar.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCENARIOS_DIR = Path(__file__).parent / "scenarios"

CATEGORIAS_VALIDAS = {
    "conversa",
    "identidade",
    "conta",
    "pesquisa",
    "arquivos",
    "codigo",
    "memoria",
    "skills",
    "recado",
    "contexto",
    "seguranca",
}

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")


class ScenarioError(ValueError):
    """Cenário malformado (falta campo, tipo errado ou rótulo inválido)."""


@dataclass
class WebPage:
    """Página falsa servida localmente durante o cenário."""

    caminho: str
    html: str


@dataclass
class Ambiente:
    """Arquivos, skills e páginas web criados num diretório temporário."""

    arquivos: dict[str, str] = field(default_factory=dict)
    skills: dict[str, dict[str, str]] = field(default_factory=dict)
    web: list[WebPage] = field(default_factory=list)


@dataclass
class Esperado:
    """Verificações aplicadas depois que o agente termina a tarefa."""

    ferramentas_usadas: list[str] = field(default_factory=list)
    ferramentas_proibidas: list[str] = field(default_factory=list)
    ferramentas_ok: list[str] = field(default_factory=list)
    ferramentas_negadas: list[str] = field(default_factory=list)
    texto_contem: list[str] = field(default_factory=list)
    texto_nao_contem: list[str] = field(default_factory=list)
    arquivos_existentes: list[str] = field(default_factory=list)
    arquivos_inexistentes: list[str] = field(default_factory=list)
    confirmacao_pedida: bool | None = None
    confirmacao_ferramenta: str | None = None
    confirmacao_negada: bool | None = None
    resultado_ok: bool | None = None
    # resposta que o roteiro dá quando o executor pergunta (padrão: nega)
    confirmar: bool = False


@dataclass
class MensagemRoteiro:
    """Mensagem falsa do assistente (com ou sem chamadas de ferramenta)."""

    papel: str = "assistant"
    conteudo: str = ""
    ferramentas: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Scenario:
    """Um cenário completo de avaliação."""

    id: str
    categoria: str
    entrada: str
    max_steps: int = 6
    ambiente: Ambiente = field(default_factory=Ambiente)
    roteiro: list[MensagemRoteiro] = field(default_factory=list)
    esperado: Esperado = field(default_factory=Esperado)
    # turnos anteriores da sessão (contexto encadeado), semeados na memória
    historico: list[tuple[str, str]] = field(default_factory=list)
    source: str = ""  # arquivo de origem, para relatórios


def _require(dados: dict, chave: str, tipo, onde: str) -> Any:
    if chave not in dados:
        raise ScenarioError(f"{onde}: falta o campo obrigatório {chave!r}")
    valor = dados[chave]
    if not isinstance(valor, tipo):
        raise ScenarioError(
            f"{onde}: campo {chave!r} deveria ser {tipo}, veio {type(valor).__name__}"
        )
    return valor


def _parse_ambiente(valor: Any, onde: str) -> Ambiente:
    if valor is None:
        return Ambiente()
    if not isinstance(valor, dict):
        raise ScenarioError(f"{onde}: 'ambiente' deveria ser objeto")
    amb = Ambiente()
    arquivos = valor.get("arquivos", {})
    if not isinstance(arquivos, dict):
        raise ScenarioError(f"{onde}: ambiente.arquivos deveria ser objeto")
    for caminho, conteudo in arquivos.items():
        if not isinstance(conteudo, str):
            raise ScenarioError(f"{onde}: conteúdo de {caminho!r} deveria ser texto")
        amb.arquivos[str(caminho)] = conteudo

    skills = valor.get("skills", {})
    if not isinstance(skills, dict):
        raise ScenarioError(f"{onde}: ambiente.skills deveria ser objeto")
    for nome, corpo in skills.items():
        if not isinstance(corpo, dict):
            raise ScenarioError(f"{onde}: skill {nome!r} deveria ser objeto")
        amb.skills[str(nome)] = {
            "descricao": str(corpo.get("descricao", "")),
            "corpo": str(corpo.get("corpo", "")),
        }

    paginas = valor.get("web", [])
    if not isinstance(paginas, list):
        raise ScenarioError(f"{onde}: ambiente.web deveria ser lista")
    for pagina in paginas:
        if not isinstance(pagina, dict) or "caminho" not in pagina:
            raise ScenarioError(f"{onde}: página web malformada")
        caminho = str(pagina["caminho"])
        if not caminho.startswith("/"):
            caminho = "/" + caminho
        amb.web.append(WebPage(caminho=caminho, html=str(pagina.get("html", ""))))
    return amb


def _parse_roteiro(valor: Any, onde: str) -> list[MensagemRoteiro]:
    if valor is None:
        return []
    if not isinstance(valor, list):
        raise ScenarioError(f"{onde}: 'roteiro' deveria ser lista")
    mensagens: list[MensagemRoteiro] = []
    for i, item in enumerate(valor):
        if not isinstance(item, dict):
            raise ScenarioError(f"{onde}: roteiro[{i}] deveria ser objeto")
        ferramentas = item.get("ferramentas", [])
        if not isinstance(ferramentas, list):
            raise ScenarioError(f"{onde}: roteiro[{i}].ferramentas deveria ser lista")
        for chamada in ferramentas:
            if not isinstance(chamada, dict) or "nome" not in chamada:
                raise ScenarioError(f"{onde}: roteiro[{i}] tem chamada sem 'nome'")
            if not isinstance(chamada.get("argumentos", {}), dict):
                raise ScenarioError(f"{onde}: roteiro[{i}] argumentos deveriam ser objeto")
        mensagens.append(
            MensagemRoteiro(
                papel=str(item.get("papel", "assistant")),
                conteudo=str(item.get("conteudo", "")),
                ferramentas=list(ferramentas),
            )
        )
    return mensagens


def _parse_esperado(valor: Any, onde: str) -> Esperado:
    if valor is None:
        return Esperado()
    if not isinstance(valor, dict):
        raise ScenarioError(f"{onde}: 'esperado' deveria ser objeto")
    esp = Esperado()
    for chave in (
        "ferramentas_usadas",
        "ferramentas_proibidas",
        "ferramentas_ok",
        "ferramentas_negadas",
        "texto_contem",
        "texto_nao_contem",
        "arquivos_existentes",
        "arquivos_inexistentes",
    ):
        lista = valor.get(chave, [])
        if not isinstance(lista, list):
            raise ScenarioError(f"{onde}: esperado.{chave} deveria ser lista")
        setattr(esp, chave, [str(x) for x in lista])
    for chave in (
        "confirmacao_pedida",
        "confirmacao_negada",
        "resultado_ok",
        "confirmar",
    ):
        if chave in valor:
            setattr(esp, chave, bool(valor[chave]))
    if "confirmacao_ferramenta" in valor:
        esp.confirmacao_ferramenta = str(valor["confirmacao_ferramenta"])
    return esp


def _parse_historico(valor: Any, onde: str) -> list[tuple[str, str]]:
    """Turnos anteriores da sessão: ``[{"papel": "user", "conteudo": "..."}]``."""
    if valor is None:
        return []
    if not isinstance(valor, list):
        raise ScenarioError(f"{onde}: 'historico' deveria ser lista")
    turnos: list[tuple[str, str]] = []
    for i, item in enumerate(valor):
        if not isinstance(item, dict) or "conteudo" not in item:
            raise ScenarioError(f"{onde}: historico[{i}] deveria ter 'conteudo'")
        turnos.append((str(item.get("papel", "user")), str(item["conteudo"])))
    return turnos


def parse_scenario(dados: dict, source: str = "") -> Scenario:
    """Converte um dict (linha do JSONL) em :class:`Scenario`, validando tudo."""
    onde = source or "cenário"
    sid = str(_require(dados, "id", str, onde))
    if not _ID_RE.match(sid):
        raise ScenarioError(f"{onde}: id {sid!r} inválido (use algo como 'arq-003')")
    categoria = str(_require(dados, "categoria", str, onde))
    if categoria not in CATEGORIAS_VALIDAS:
        raise ScenarioError(
            f"{onde}: categoria {categoria!r} inválida; use uma de {sorted(CATEGORIAS_VALIDAS)}"
        )
    entrada = str(_require(dados, "entrada", str, onde))
    if not entrada.strip():
        raise ScenarioError(f"{onde}: 'entrada' vazia")

    roteiro = _parse_roteiro(dados.get("roteiro"), onde)
    if not roteiro:
        raise ScenarioError(f"{onde}: 'roteiro' vazio; o FakeLLM precisa de uma resposta")

    max_steps = dados.get("max_steps", 6)
    if not isinstance(max_steps, int) or max_steps < 1:
        raise ScenarioError(f"{onde}: 'max_steps' deveria ser inteiro >= 1")

    return Scenario(
        id=sid,
        categoria=categoria,
        entrada=entrada,
        max_steps=max_steps,
        ambiente=_parse_ambiente(dados.get("ambiente"), onde),
        roteiro=roteiro,
        esperado=_parse_esperado(dados.get("esperado"), onde),
        historico=_parse_historico(dados.get("historico"), onde),
        source=source,
    )


def load_scenarios(path: Path | str | None = None) -> list[Scenario]:
    """Carrega todos os cenários de um arquivo ou da pasta ``scenarios/``."""
    alvo = Path(path) if path is not None else SCENARIOS_DIR
    arquivos = [alvo] if alvo.is_file() else sorted(alvo.glob("*.jsonl"))
    if not arquivos:
        raise FileNotFoundError(f"nenhum cenário encontrado em {alvo}")

    cenarios: list[Scenario] = []
    vistos: set[str] = set()
    for arquivo in arquivos:
        for numero, linha in enumerate(
            arquivo.read_text(encoding="utf-8").splitlines(), start=1
        ):
            linha = linha.strip()
            if not linha or linha.startswith("//"):
                continue
            try:
                dados = json.loads(linha)
            except json.JSONDecodeError as exc:
                raise ScenarioError(f"{arquivo.name}:{numero}: JSON inválido: {exc}") from exc
            cenario = parse_scenario(dados, source=f"{arquivo.name}:{numero}")
            if cenario.id in vistos:
                raise ScenarioError(f"{arquivo.name}:{numero}: id duplicado {cenario.id!r}")
            vistos.add(cenario.id)
            cenarios.append(cenario)
    return cenarios


def filter_scenarios(
    cenarios: list[Scenario], *, categoria: str | None = None, ids: list[str] | None = None
) -> list[Scenario]:
    """Faz um recorte dos cenários por categoria e/ou ids."""
    recorte = list(cenarios)
    if categoria:
        recorte = [c for c in recorte if c.categoria == categoria]
    if ids:
        alvo = set(ids)
        recorte = [c for c in recorte if c.id in alvo]
    return recorte
