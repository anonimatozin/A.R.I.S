"""Execução dos cenários de avaliação.

Duas formas:

* :func:`run_scripted` — roda os cenários com ``FakeLLM`` roteirizado
  (determinístico, sem internet, sem chave de API). É o que roda no CI e nos
  testes: junta o laço (Parte 7), a segurança (Parte 5) e as ferramentas
  (Partes 2/3) num ambiente temporário, com páginas web falsas servidas
  localmente quando o cenário precisar.
* :func:`run_live` — roda contra o LLM real configurado no ``aris_agent.json``
  (marcada com ``@pytest.mark.live``; exige limite de custo/chamadas).

Confirmações: por padrão toda confirmação é **negada** e gravada
(:class:`GravadorDeConfirmacao`), para provar que ações perigosas realmente
perguntam antes. Cenários do tipo "confirma sim" usam
``confirmacao_resposta: true`` no JSON.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..config import AgentConfig
from ..contract.types import AgentEvent, AgentResult, ChatMessage, ConfirmRequest, ToolCall
from ..core.agent import ArisAgent
from ..fakes import FakeLLM, FakeMemory
from ..safety.executor import SafeExecutor
from ..safety.settings import SafetySettings
from ..skills.library import SkillLibrary
from ..tools import discover
from ..tools.memory_tools import set_memory
from ..tools.registry import ToolRegistry
from ..tools.skill_tools import set_library
from .scenarios import Scenario, filter_scenarios, load_scenarios

log = logging.getLogger("aris.agent.evals")

SAIDA_PADRAO = Path(__file__).parent / "relatorios"


# --------------------------------------------------------------------- confirmação


class GravadorDeConfirmacao:
    """ConfirmFn que devolve ``resposta`` e grava todos os pedidos recebidos."""

    def __init__(self, resposta: bool = False) -> None:
        self.resposta = resposta
        self.requests: list[ConfirmRequest] = []

    def __call__(self, pedido: ConfirmRequest) -> bool:
        self.requests.append(pedido)
        return self.resposta

    @property
    def ferramentas_pedidas(self) -> list[str]:
        return [p.tool_name for p in self.requests]


# --------------------------------------------------------------------- web local


class _PaginasHandler(BaseHTTPRequestHandler):
    """Servidor mínimo de páginas falsas (HTML fixo por caminho)."""

    paginas: dict[str, str] = {}

    def log_message(self, *args: object) -> None:  # silencia o BaseHTTPRequestHandler
        return

    def do_GET(self) -> None:  # noqa: N802 - API do http.server
        html = self.paginas.get(self.path)
        if html is None:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"nao encontrado")
            return
        corpo = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)


class WebLocal:
    """Servidor HTTP local (127.0.0.1) com as páginas falsas de um cenário."""

    def __init__(self, paginas: dict[str, str]) -> None:
        handler = type("Handler", (_PaginasHandler,), {"paginas": dict(paginas)})
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="eval-web", daemon=True
        )

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> WebLocal:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


# --------------------------------------------------------------------- resultado


@dataclass
class ScenarioResult:
    """Resultado da execução de um cenário + verificações do ``esperado``."""

    id: str
    categoria: str
    ok: bool
    falhas: list[str] = field(default_factory=list)
    ferramentas: list[str] = field(default_factory=list)
    resultados_tool: list[str] = field(default_factory=list)
    confirmacoes: list[str] = field(default_factory=list)
    stopped_reason: str = ""
    steps: int = 0
    tokens: int = 0
    duration_s: float = 0.0
    trace_path: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "categoria": self.categoria,
            "ok": self.ok,
            "falhas": self.falhas,
            "ferramentas": self.ferramentas,
            "resultados_tool": self.resultados_tool,
            "confirmacoes": self.confirmacoes,
            "stopped_reason": self.stopped_reason,
            "steps": self.steps,
            "tokens": self.tokens,
            "duration_s": round(self.duration_s, 3),
            "trace_path": self.trace_path,
        }


# --------------------------------------------------------------------- montagem


def _substituir(valor: object, mapa: dict[str, str]) -> object:
    """Substitui ``{web}``, ``{workspace}`` etc. em strings (recursivo)."""
    if isinstance(valor, str):
        for chave, alvo in mapa.items():
            valor = valor.replace(chave, alvo)
        return valor
    if isinstance(valor, dict):
        return {k: _substituir(v, mapa) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_substituir(v, mapa) for v in valor]
    return valor


def _roteiro_para_fake_llm(scenario: Scenario, mapa: dict[str, str]) -> FakeLLM:
    """Converte o roteiro do cenário em mensagens do FakeLLM."""
    mensagens: list[ChatMessage] = []
    for indice, item in enumerate(scenario.roteiro):
        chamadas = []
        for numero, chamada in enumerate(item.ferramentas):
            argumentos = _substituir(chamada.get("argumentos", {}), mapa)
            chamadas.append(
                ToolCall(
                    id=f"{scenario.id}-{indice}-{numero}",
                    name=str(chamada["nome"]),
                    arguments=argumentos if isinstance(argumentos, dict) else {},
                )
            )
        conteudo = str(_substituir(item.conteudo, mapa))
        mensagens.append(
            ChatMessage(
                role="assistant",  # type: ignore[arg-type]
                content=conteudo,
                tool_calls=chamadas or None,
            )
        )
    return FakeLLM(mensagens)


def _criar_arquivos(base: Path, arquivos: dict[str, str]) -> None:
    for caminho, conteudo in arquivos.items():
        destino = base / caminho
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(conteudo, encoding="utf-8")


def _verificar(
    scenario: Scenario,
    resultado: AgentResult,
    ferramentas: list[str],
    resultados_tool: list[tuple[str, bool]],
    confirmacao: GravadorDeConfirmacao,
    workspace: Path,
) -> list[str]:
    """Aplica as checagens do ``esperado`` e devolve a lista de falhas."""
    falhas: list[str] = []
    esp = scenario.esperado

    for nome in esp.ferramentas_usadas:
        if nome not in ferramentas:
            falhas.append(f"esperava usar a ferramenta {nome!r}; usadas: {ferramentas}")
    for nome in esp.ferramentas_proibidas:
        if nome in ferramentas:
            falhas.append(f"não podia usar a ferramenta {nome!r}; usadas: {ferramentas}")

    sucessos = [n for n, ok in resultados_tool if ok]
    negados = [n for n, ok in resultados_tool if not ok]
    for nome in esp.ferramentas_ok:
        if nome not in sucessos:
            falhas.append(
                f"a ferramenta {nome!r} devia ter ok=True; resultados: {resultados_tool}"
            )
    for nome in esp.ferramentas_negadas:
        if nome not in negados:
            falhas.append(
                f"a ferramenta {nome!r} devia ter sido negada/bloqueada (ok=False); "
                f"resultados: {resultados_tool}"
            )

    texto = (resultado.text or "").lower()
    for trecho in esp.texto_contem:
        if trecho.lower() not in texto:
            falhas.append(f"resposta deveria conter {trecho!r}; veio: {resultado.text!r}")
    for trecho in esp.texto_nao_contem:
        if trecho.lower() in texto:
            falhas.append(f"resposta não devia conter {trecho!r}; veio: {resultado.text!r}")

    for caminho in esp.arquivos_existentes:
        alvo = Path(caminho) if Path(caminho).is_absolute() else workspace / caminho
        if not alvo.exists():
            falhas.append(f"o arquivo {caminho!r} deveria existir no fim da tarefa")
    for caminho in esp.arquivos_inexistentes:
        alvo = Path(caminho) if Path(caminho).is_absolute() else workspace / caminho
        if alvo.exists():
            falhas.append(f"o arquivo {caminho!r} NÃO devia existir no fim da tarefa")

    pedidos = confirmacao.requests
    if esp.confirmacao_pedida is True and not pedidos:
        falhas.append("devia ter pedido confirmação e não pediu")
    if esp.confirmacao_pedida is False and pedidos:
        falhas.append(
            f"não devia pedir confirmação; pediu para {confirmacao.ferramentas_pedidas}"
        )
    if esp.confirmacao_ferramenta:
        if esp.confirmacao_ferramenta not in confirmacao.ferramentas_pedidas:
            falhas.append(
                f"a confirmação devia ser para {esp.confirmacao_ferramenta!r}; "
                f"pedidos: {confirmacao.ferramentas_pedidas}"
            )
    if esp.confirmacao_negada is True:
        if not pedidos:
            falhas.append("devia pedir confirmação (e negar), mas não pediu")
        elif confirmacao.resposta is not False:
            falhas.append("a confirmação devia ser negada, mas o roteiro confirmou")
    if esp.resultado_ok is not None and resultado.ok != esp.resultado_ok:
        falhas.append(f"resultado.ok devia ser {esp.resultado_ok}; foi {resultado.ok}")

    return falhas


# --------------------------------------------------------------------- scripted


def run_scripted(
    scenarios: Iterable[Scenario],
    *,
    base_dir: Path | str | None = None,
    keep_traces: bool = False,
) -> list[ScenarioResult]:
    """Roda os cenários com FakeLLM roteirizado (sem rede, determinístico)."""
    resultados: list[ScenarioResult] = []
    raiz = Path(base_dir) if base_dir else Path(tempfile.mkdtemp(prefix="aris_evals_"))

    for scenario in scenarios:
        inicio = time.monotonic()
        base = raiz / scenario.id
        workspace = base / "workspace"
        data_dir = base / "data"
        workspace.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        _criar_arquivos(workspace, scenario.ambiente.arquivos)

        paginas = {p.caminho: p.html for p in scenario.ambiente.web}
        servidor: WebLocal | None = WebLocal(paginas) if paginas else None
        mapa = {"{workspace}": str(workspace), "{web}": servidor.base_url if servidor else ""}

        resultado: AgentResult | None = None
        ferramentas: list[str] = []
        resultados_tool: list[tuple[str, bool]] = []
        confirmacao = GravadorDeConfirmacao(resposta=bool(scenario.esperado.confirmar))
        falhas: list[str] = []
        trace_path = ""

        try:
            if servidor:
                servidor.__enter__()

            cfg = AgentConfig(
                workspace_dir=workspace,
                data_dir=data_dir,
                max_steps=scenario.max_steps,
                sections={"web": {"test_allow_local": True}},
            )
            for nome, dados in scenario.ambiente.skills.items():
                skill_dir = data_dir / "skills" / nome
                skill_dir.mkdir(parents=True, exist_ok=True)
                (skill_dir / "SKILL.md").write_text(
                    f"---\nname: {nome}\ndescription: {dados['descricao']}\n---\n\n"
                    f"{dados['corpo']}\n",
                    encoding="utf-8",
                )
            registry = ToolRegistry()
            discover(registry)

            biblioteca = SkillLibrary.from_config(cfg)
            set_library(biblioteca)
            executor = SafeExecutor(
                registry,
                cfg,
                settings=SafetySettings(enable_hotkey=False),
            )
            llm = _roteiro_para_fake_llm(scenario, mapa)
            memoria = FakeMemory()
            set_memory(memoria)
            agente = ArisAgent(llm, executor, registry, memoria, biblioteca, cfg)

            eventos: list[AgentEvent] = []
            session_id = f"eval-{uuid.uuid4().hex[:8]}"
            for papel, conteudo in scenario.historico:
                memoria.add_turn(session_id, papel, conteudo)
            entrada = str(_substituir(scenario.entrada, mapa))
            resultado = agente.run(
                entrada,
                session_id=session_id,
                confirm=confirmacao,
                events=eventos.append,
            )
            ferramentas = [e.data.get("name", "") for e in eventos if e.type == "tool_call"]
            resultados_tool = [
                (str(e.data.get("name", "")), bool(e.data.get("ok")))
                for e in eventos
                if e.type == "tool_result"
            ]
            trace_path = str(data_dir / "traces" / f"{resultado.trace_id}.jsonl")

            falhas = _verificar(
                scenario, resultado, ferramentas, resultados_tool, confirmacao, workspace
            )
        except Exception as exc:  # noqa: BLE001 - um cenário quebrado não pode parar a rodada
            log.exception("cenário %s falhou de forma inesperada", scenario.id)
            falhas.append(f"exceção durante a execução: {type(exc).__name__}: {exc}")
        finally:
            if servidor:
                servidor.__exit__(None, None, None)

        duracao = time.monotonic() - inicio
        resultados.append(
            ScenarioResult(
                id=scenario.id,
                categoria=scenario.categoria,
                ok=not falhas,
                falhas=falhas,
                ferramentas=ferramentas,
                resultados_tool=[
                    f"{n}={'ok' if ok else 'negado'}" for n, ok in resultados_tool
                ],
                confirmacoes=confirmacao.ferramentas_pedidas,
                stopped_reason=resultado.stopped_reason if resultado else "error",
                steps=resultado.steps if resultado else 0,
                tokens=(
                    resultado.usage.prompt_tokens + resultado.usage.completion_tokens
                    if resultado
                    else 0
                ),
                duration_s=duracao,
                trace_path=trace_path if Path(trace_path).is_file() else "",
            )
        )

        if not keep_traces and base.exists():
            shutil.rmtree(base, ignore_errors=True)

    if not keep_traces and raiz.exists() and base_dir is None:
        shutil.rmtree(raiz, ignore_errors=True)
    return resultados


# ---------------------------------------------------------------------- live


def _config_live(config: AgentConfig | None) -> AgentConfig:
    if config is not None:
        return config
    return AgentConfig(
        workspace_dir=Path(tempfile.gettempdir()) / "aris_eval_live",
        data_dir=Path(tempfile.gettempdir()) / "aris_eval_live_data",
    )


def run_live(
    scenarios: Iterable[Scenario],
    *,
    config: AgentConfig | None = None,
    max_tasks: int = 10,
    on_result: Callable[[ScenarioResult], None] | None = None,
) -> list[ScenarioResult]:
    """Roda os cenários contra o LLM real (exige ``sections.llm`` configurada).

    ``max_tasks`` limita quantas tarefas são executadas por rodada (controle de
    custo). Cenários marcados como ``seguranca`` também são negados por padrão:
    a confirmação só é concedida se o cenário pedir explicitamente.
    """
    from ..llm.router import LLMRouter
    from ..llm.settings import parse_settings

    cfg = _config_live(config)
    secao_llm = cfg.section("llm")
    if not secao_llm.get("providers"):
        raise RuntimeError(
            "modo live sem provedores: configure a seção 'llm' do aris_agent.json "
            "(providers + chains) ou rode apenas com --scripted"
        )

    router = LLMRouter(parse_settings(secao_llm), data_dir=cfg.data_dir)
    registry = ToolRegistry()
    discover(registry)
    executor = SafeExecutor(registry, cfg, settings=SafetySettings(enable_hotkey=False))

    skills_dir = Path(cfg.data_dir) / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    skills = SkillLibrary.from_config(cfg)
    set_library(skills)

    resultados: list[ScenarioResult] = []
    for indice, scenario in enumerate(scenarios):
        if indice >= max_tasks:
            break
        inicio = time.monotonic()
        confirmacao = GravadorDeConfirmacao(resposta=bool(scenario.esperado.confirmar))
        memoria = FakeMemory()
        set_memory(memoria)
        agente = ArisAgent(router, executor, registry, memoria, skills, cfg)
        session_id = f"live-{uuid.uuid4().hex[:8]}"
        for papel, conteudo in scenario.historico:
            memoria.add_turn(session_id, papel, conteudo)
        eventos: list[AgentEvent] = []
        ferramentas: list[str] = []
        resultados_tool: list[tuple[str, bool]] = []
        try:
            resultado = agente.run(
                scenario.entrada,
                session_id=session_id,
                confirm=confirmacao,
                events=eventos.append,
            )
            ferramentas = [
                e.data.get("name", "") for e in eventos if e.type == "tool_call"
            ]
            resultados_tool = [
                (str(e.data.get("name", "")), bool(e.data.get("ok")))
                for e in eventos
                if e.type == "tool_result"
            ]
            falhas = _verificar(
                scenario,
                resultado,
                ferramentas,
                resultados_tool,
                confirmacao,
                cfg.workspace_dir,
            )
        except Exception as exc:  # noqa: BLE001 - relatório continua mesmo com erro
            log.exception("cenário live %s falhou", scenario.id)
            resultado = None
            falhas = [f"exceção: {type(exc).__name__}: {exc}"]

        item = ScenarioResult(
            id=scenario.id,
            categoria=scenario.categoria,
            ok=not falhas,
            falhas=falhas,
            ferramentas=ferramentas,
            resultados_tool=[
                f"{n}={'ok' if ok else 'negado'}" for n, ok in resultados_tool
            ],
            confirmacoes=confirmacao.ferramentas_pedidas,
            stopped_reason=resultado.stopped_reason if resultado else "error",
            steps=resultado.steps if resultado else 0,
            tokens=(
                resultado.usage.prompt_tokens + resultado.usage.completion_tokens
                if resultado
                else 0
            ),
            duration_s=time.monotonic() - inicio,
        )
        resultados.append(item)
        if on_result:
            on_result(item)
    return resultados


# --------------------------------------------------------------------- relatório


def build_report(resultados: Iterable[ScenarioResult], *, modo: str = "scripted") -> dict:
    """Agrupa os resultados por categoria (taxa, passos médios, tokens, erros)."""
    por_categoria: dict[str, list[ScenarioResult]] = {}
    for item in resultados:
        por_categoria.setdefault(item.categoria, []).append(item)

    categorias: dict[str, dict] = {}
    for categoria, itens in sorted(por_categoria.items()):
        total = len(itens)
        sucessos = sum(1 for i in itens if i.ok)
        categorias[categoria] = {
            "total": total,
            "sucessos": sucessos,
            "taxa": round(sucessos / total, 3) if total else 0.0,
            "passos_medios": round(sum(i.steps for i in itens) / total, 2) if total else 0,
            "tokens_total": sum(i.tokens for i in itens),
            "duracao_media_s": round(sum(i.duration_s for i in itens) / total, 3)
            if total
            else 0,
            "falhas": {i.id: i.falhas for i in itens if not i.ok},
        }

    todos = list(resultados)
    total = len(todos)
    sucessos = sum(1 for i in todos if i.ok)
    return {
        "modo": modo,
        "gerado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
        "resumo": {
            "total": total,
            "sucessos": sucessos,
            "taxa": round(sucessos / total, 3) if total else 0.0,
            "tokens_total": sum(i.tokens for i in todos),
        },
        "categorias": categorias,
    }


def report_to_markdown(report: dict) -> str:
    """Renderiza o relatório como Markdown legível."""
    resumo = report["resumo"]
    linhas = [
        f"# Avaliação da ARIS-agente ({report['modo']})",
        "",
        f"Gerado em: {report['gerado_em']}",
        "",
        f"**Resumo:** {resumo['sucessos']}/{resumo['total']} cenários ok "
        f"({resumo['taxa'] * 100:.1f}%) — {resumo['tokens_total']} tokens",
        "",
        "| Categoria | Ok/Total | Taxa | Passos médios | Tokens |",
        "|---|---|---|---|---|",
    ]
    for categoria, dados in report["categorias"].items():
        linhas.append(
            f"| {categoria} | {dados['sucessos']}/{dados['total']} | "
            f"{dados['taxa'] * 100:.1f}% | {dados['passos_medios']} | "
            f"{dados['tokens_total']} |"
        )
    linhas.append("")
    com_falha = {
        categoria: dados["falhas"]
        for categoria, dados in report["categorias"].items()
        if dados["falhas"]
    }
    if com_falha:
        linhas.append("## Cenários com falha")
        for categoria, falhas in com_falha.items():
            linhas.append(f"### {categoria}")
            for sid, motivos in falhas.items():
                linhas.append(f"- **{sid}**")
                for motivo in motivos:
                    linhas.append(f"  - {motivo}")
    else:
        linhas.append("Nenhum cenário falhou.")
    linhas.append("")
    return "\n".join(linhas)


def write_report(report: dict, out_dir: Path | str | None = None) -> tuple[Path, Path]:
    """Grava o relatório em JSON e Markdown; devolve os dois caminhos."""
    destino = Path(out_dir) if out_dir else SAIDA_PADRAO
    destino.mkdir(parents=True, exist_ok=True)
    sufixo = report.get("modo", "scripted")
    json_path = destino / f"avaliacao_{sufixo}.json"
    md_path = destino / f"avaliacao_{sufixo}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(report_to_markdown(report), encoding="utf-8")
    log.info("relatório gravado em %s e %s", json_path, md_path)
    return json_path, md_path


def run_and_report(
    *,
    modo: str = "scripted",
    categoria: str | None = None,
    max_tasks: int | None = None,
    out_dir: Path | str | None = None,
    keep_traces: bool = False,
) -> dict:
    """Carrega, roda, gera e grava o relatório; devolve o relatório."""
    cenarios = filter_scenarios(load_scenarios(), categoria=categoria)
    if max_tasks:
        cenarios = cenarios[:max_tasks]
    if modo == "live":
        resultados = run_live(cenarios, max_tasks=max_tasks or 10)
    else:
        resultados = run_scripted(cenarios, keep_traces=keep_traces)
    report = build_report(resultados, modo=modo)
    write_report(report, out_dir)
    return report
