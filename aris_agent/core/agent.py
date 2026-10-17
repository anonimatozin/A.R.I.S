"""O laço do agente: entender → planejar → agir → verificar → responder.

Depende só das interfaces do contrato (`aris_agent/contract/`): LLMClient,
ToolExecutor, Memory, SkillCatalog e ToolRegistry. Toda chamada de ferramenta
passa pelo executor — o agente nunca chama ``tool.run()`` direto.

Pontos de extensão para o futuro (não implementados aqui):
  * HOOK subagentes: trocar ``_resolver`` por um despachante que pode delegar
    uma chamada a um subagente com o seu próprio histórico;
  * HOOK camada reflexo: ``_verificar`` é a única passada de autoconferência;
    uma Camada Reflexo externa pode observar ``events`` e reexecutar o laço.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import TYPE_CHECKING

from ..config import AgentConfig
from ..contract import (
    AgentResult,
    ChatMessage,
    ProviderError,
    ToolCall,
    ToolContext,
    ToolResult,
    ToolSpec,
    Usage,
    redact_secrets,
    truncate_text,
)
from ..tools.registry import ToolRegistry
from .context import ContextManager
from .heuristics import asks_to_verify, choose_difficulty, looks_like_correction
from .plan import PlanState, make_plan_tool
from .prompts import PromptBuilder, summarize_messages, verification_messages
from .selector import ToolSelector
from .state import Emitter, TaskState
from .trace import TraceWriter
from .validation import validate_args

if TYPE_CHECKING:
    from ..contract import (
        ConfirmFn,
        ConfirmRequest,
        EventSink,
        LLMClient,
        Memory,
        SkillCatalog,
        ToolExecutor,
    )

log = logging.getLogger("aris.agent.core")

MAX_TOKENS_MAIN = 1024
MAX_TOKENS_VERIFY = 512
MAX_TOKENS_SUMMARY = 384
TEMPERATURA = 0.3
MAX_TOOL_CALLS_PER_MSG = 6  # excedente vira erro, para não estourar a API
CORRECOES_MAX = 2  # duas correções de argumento por ferramenta; na 3ª, para
LOOP_LIMITE = 3  # 3ª chamada idêntica seguida = laço
TURNOS_MEMORIA = 8

_MOTIVOS_CONTRATO = {"max_steps": "max_steps", "budget": "budget", "cancelled": "cancelled"}

_CABECALHOS = {
    "max_steps": "Cheguei ao limite de etapas e parei aqui, chefe.",
    "budget": "Meu orcamento de tokens acabou antes de terminar, chefe.",
    "cancelled": "Tarefa cancelada, chefe.",
    "laco": "Fiquei repetindo a mesma chamada e parei para nao ficar em laco, chefe.",
    "argumentos": "Os argumentos continuaram invalidos depois das correcoes, chefe.",
    "provider": "Nao consegui falar com o modelo agora, chefe. Tenta de novo em instantes.",
    "erro": "Algo deu errado no meio do caminho, chefe.",
}


def _emitir(events: EventSink | None, tipo: str, data: dict) -> None:
    Emitter(events).emit(tipo, data)


def _id_da(chamada: ToolCall, indice: int) -> str:
    """Id da chamada; se o provedor veio sem id, gera um estável por posição."""
    return str(chamada.id or f"auto_{indice}")


def _assinatura(chamada: ToolCall) -> str:
    """Assinatura estável (nome + argumentos) para detectar laço."""
    try:
        args = json.dumps(chamada.arguments or {}, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # pragma: no cover - defensivo
        args = str(chamada.arguments)
    return f"{chamada.name}:{args}"


def _normalizar_args(argumentos: object) -> dict | None:
    """Aceita dict; tenta JSON quando o provedor manda string; devolve None se não der."""
    if isinstance(argumentos, dict):
        return argumentos
    if isinstance(argumentos, str):
        try:
            dados = json.loads(argumentos)
        except json.JSONDecodeError:
            return None
        return dados if isinstance(dados, dict) else None
    return None


class ArisAgent:
    """Implementa o protocolo ``Agent``: recebe o pedido e conduz o laço.

    Thread-safe entre sessões diferentes (um lock por ``session_id``) e com
    cancelamento por ``threading.Event`` (``cancel(session_id)`` ou o evento
    dentro do ``ToolContext``).
    """

    def __init__(
        self,
        llm: LLMClient,
        executor: ToolExecutor,
        registry: ToolRegistry,
        memory: Memory,
        skills: SkillCatalog,
        config: AgentConfig,
    ) -> None:
        self._llm = llm
        self._executor = executor
        self._registry = registry
        self._memory = memory
        self._skills = skills
        self._config = config
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._states: dict[str, TaskState] = {}
        self._pending: set[str] = set()  # cancel pedido sem tarefa ativa
        if "plan_update" not in registry:
            registry.register(make_plan_tool(self._state_for))
            log.debug("ferramenta interna plan_update registrada na instancia do agente")

    # ------------------------------------------------------------------ API

    def run(
        self,
        user_text: str,
        session_id: str,
        confirm: ConfirmFn,
        events: EventSink | None = None,
    ) -> AgentResult:
        """Roda uma tarefa completa. Não lança exceção para o chamador."""
        trace_id = uuid.uuid4().hex[:16]
        lock = self._lock_for(str(session_id))
        with lock:
            try:
                return self._executar(str(user_text), str(session_id), confirm, events, trace_id)
            except Exception as exc:  # noqa: BLE001 - defesa final do laço
                log.exception("o laço do agente falhou (trace %s)", trace_id)
                texto = "Desculpe, chefe: algo quebrou aqui dentro e eu nao consegui terminar."
                _emitir(events, "error", {"error": redact_secrets(str(exc))})
                _emitir(
                    events,
                    "final",
                    {"text": texto, "stopped_reason": "error", "trace_id": trace_id},
                )
                return AgentResult(
                    text=texto,
                    steps=0,
                    tool_calls=0,
                    ok=False,
                    stopped_reason="error",
                    usage=Usage(),
                    trace_id=trace_id,
                )

    def cancel(self, session_id: str | None = None) -> None:
        """Marca a tarefa atual como cancelada; sem tarefa ativa, vale para a próxima.

        O cancelamento é um ``threading.Event`` observado no topo do laço e dentro
        da execução de cada ferramenta (também fica em ``ToolContext.cancel``).
        """
        with self._guard:
            ativos = [
                estado
                for estado in self._states.values()
                if estado.active and (session_id is None or estado.session_id == session_id)
            ]
            if not ativos:
                if session_id is None:
                    if not any(estado.active for estado in self._states.values()):
                        self._pending.add("*")
                else:
                    self._pending.add(session_id)
        for estado in ativos:
            estado.cancel.set()
            log.info("cancelamento pedido para a sessao %s", estado.session_id)

    # --------------------------------------------------------------- laco

    def _executar(
        self,
        user_text: str,
        session_id: str,
        confirm: ConfirmFn,
        events: EventSink | None,
        trace_id: str,
    ) -> AgentResult:
        cfg = self._config
        sec = cfg.section("core")
        cancel = threading.Event()
        emitter = Emitter(events)
        estado = TaskState(
            session_id=session_id,
            trace_id=trace_id,
            cancel=cancel,
            plan=PlanState(),
            emitter=emitter,
        )
        with self._guard:
            self._states[session_id] = estado
            if session_id in self._pending:
                self._pending.discard(session_id)
                cancel.set()
            elif "*" in self._pending:
                self._pending.discard("*")
                cancel.set()
        trace = TraceWriter(cfg.data_dir / "traces", trace_id)
        trace.write("start", session_id=session_id, user_text=user_text)

        usage = Usage()
        passos = 0
        total_chamadas = 0
        feitas: list[str] = []
        detalhe: str | None = None
        texto_final = ""
        try:
            memorias = self._recuperar(user_text)

            def montar_prompt() -> str:
                return PromptBuilder().build(
                    user_text,
                    skills_prompt=self._skills_catalogo(),
                    memories=memorias,
                    plan_text=estado.plan.as_text(),
                    correction=looks_like_correction(user_text),
                    workspace=str(cfg.workspace_dir),
                )

            historico: list[ChatMessage] = [ChatMessage(role="system", content=montar_prompt())]
            historico.extend(self._turnos_recentes(session_id))
            historico.append(ChatMessage(role="user", content=user_text))
            versao_plano = estado.plan.version

            ctx = ToolContext(
                session_id=session_id,
                workdir=cfg.workspace_dir,
                config=cfg,
                cancel=cancel,
            )
            confirm_env = self._envolver_confirm(confirm, emitter)
            seletor = ToolSelector(self._registry)
            contexto = ContextManager(
                max_tokens=int(sec.get("max_context_tokens", 12000)),
                keep_recent=int(sec.get("keep_recent_messages", 6)),
            )
            usadas: list[str] = []
            invalidas: dict[str, int] = {}
            vistas: dict[str, int] = {}

            def resumidor(mensagens: list[ChatMessage]) -> str | None:
                """Resumo das mensagens antigas (uma vez por tarefa; difficulty easy)."""
                try:
                    resp = self._llm.chat(
                        summarize_messages(mensagens),
                        None,
                        difficulty="easy",
                        max_tokens=MAX_TOKENS_SUMMARY,
                        temperature=0.1,
                    )
                except Exception:  # noqa: BLE001 - resumo é melhor esforço
                    log.warning("resumo de contexto falhou", exc_info=True)
                    return None
                usage.prompt_tokens += resp.usage.prompt_tokens
                usage.completion_tokens += resp.usage.completion_tokens
                trace.write(
                    "llm",
                    papel="resumo",
                    dificuldade="easy",
                    tokens_prompt=resp.usage.prompt_tokens,
                    tokens_resposta=resp.usage.completion_tokens,
                )
                return (resp.message.content or "").strip() or None

            while True:
                if cancel.is_set():
                    detalhe = "cancelled"
                    break
                if passos >= cfg.max_steps:
                    detalhe = "max_steps"
                    break
                if usage.prompt_tokens + usage.completion_tokens >= cfg.max_total_tokens_per_task:
                    detalhe = "budget"
                    break

                # o system acompanha o plano da tarefa a cada volta
                if estado.plan.version != versao_plano:
                    versao_plano = estado.plan.version
                    if historico and historico[0].role == "system":
                        historico[0] = ChatMessage(role="system", content=montar_prompt())

                antes = len(historico)
                historico = contexto.fit(historico, resumidor)
                if len(historico) < antes:
                    trace.write("compactado", de_antes=antes, para=len(historico))

                ferramentas = seletor.select(user_text, usadas)
                dificuldade = choose_difficulty(
                    user_text,
                    first=passos == 0,
                    plan_size=len(estado.plan.items),
                    tool_calls_done=total_chamadas,
                    corrections=sum(invalidas.values()),
                )
                t0 = time.perf_counter()
                try:
                    resposta = self._llm.chat(
                        historico,
                        ferramentas or None,
                        difficulty=dificuldade,
                        max_tokens=MAX_TOKENS_MAIN,
                        temperature=TEMPERATURA,
                    )
                except Exception as exc:  # noqa: BLE001 - falha de provedor não derruba o laço
                    detalhe = "provider" if isinstance(exc, ProviderError) else "erro"
                    log.warning("chamada de LLM falhou: %s", exc)
                    emitter.emit("error", {"error": redact_secrets(str(exc))})
                    trace.write("erro", erro=str(exc), dificuldade=dificuldade)
                    break

                passos += 1
                usage.prompt_tokens += resposta.usage.prompt_tokens
                usage.completion_tokens += resposta.usage.completion_tokens
                trace.write(
                    "llm",
                    passo=passos,
                    dificuldade=dificuldade,
                    provedor=resposta.provider,
                    modelo=resposta.model,
                    tokens_prompt=resposta.usage.prompt_tokens,
                    tokens_resposta=resposta.usage.completion_tokens,
                    ms=round((time.perf_counter() - t0) * 1000, 1),
                )

                msg = resposta.message
                historico.append(msg)
                if not msg.tool_calls:
                    texto_final = (msg.content or "").strip()
                    break

                parar = False
                for indice, chamada in enumerate(msg.tool_calls):
                    if cancel.is_set():
                        detalhe = "cancelled"
                        parar = True
                        break
                    if indice >= MAX_TOOL_CALLS_PER_MSG:
                        historico.append(
                            ChatMessage(
                                role="tool",
                                tool_call_id=_id_da(chamada, indice),
                                name=chamada.name,
                                content="muitas chamadas numa mensagem so; continue com uma por vez",
                            )
                        )
                        continue

                    assinatura = _assinatura(chamada)
                    vistas[assinatura] = vistas.get(assinatura, 0) + 1
                    if vistas[assinatura] >= LOOP_LIMITE:
                        detalhe = "laco"
                        parar = True
                        break

                    emitter.emit(
                        "tool_call",
                        {
                            "name": chamada.name,
                            "id": _id_da(chamada, indice),
                            "arguments": chamada.arguments,
                        },
                    )
                    trace.write("tool_call", passo=passos, nome=chamada.name, argumentos=chamada.arguments)
                    t1 = time.perf_counter()
                    resultado, spec, invalida = self._resolver(chamada, ctx, confirm_env)
                    total_chamadas += 1
                    if invalida:
                        invalidas[chamada.name] = invalidas.get(chamada.name, 0) + 1
                    if spec is not None and spec.untrusted_output and resultado.ok:
                        ctx.taint = True
                    if resultado.ok and chamada.name not in feitas:
                        feitas.append(chamada.name)
                    if chamada.name not in usadas:
                        usadas.append(chamada.name)

                    emitter.emit(
                        "tool_result",
                        {
                            "name": chamada.name,
                            "ok": resultado.ok,
                            "content": truncate_text(
                                resultado.content or resultado.error or "", 400
                            ),
                            "error": resultado.error,
                        },
                    )
                    trace.write(
                        "tool",
                        nome=chamada.name,
                        ok=resultado.ok,
                        ms=round((time.perf_counter() - t1) * 1000, 1),
                        erro=resultado.error,
                    )
                    conteudo = truncate_text(
                        resultado.content if resultado.ok else (resultado.error or "ferramenta falhou"),
                        cfg.max_tool_chars,
                    )
                    historico.append(
                        ChatMessage(
                            role="tool",
                            tool_call_id=_id_da(chamada, indice),
                            name=chamada.name,
                            content=conteudo,
                        )
                    )
                    if invalida and invalidas[chamada.name] > CORRECOES_MAX:
                        detalhe = "argumentos"
                        parar = True
                        break
                if parar:
                    break

            # ---------------- pós-laço: verificação, motivo e resposta

            if detalhe is None and texto_final and (
                total_chamadas >= 3 or asks_to_verify(user_text)
            ):
                texto_final, novos = self._verificar(
                    historico, user_text, texto_final, usage, trace
                )
                passos += novos

            if detalhe is not None:
                motivo = _MOTIVOS_CONTRATO.get(detalhe, "error")
                texto_final = self._texto_parada(detalhe, feitas)
            elif texto_final:
                motivo = "done"
            else:
                motivo = "error"
                texto_final = "Nao consegui montar uma resposta, chefe."

            self._guardar_turnos(session_id, user_text, texto_final)
            trace.write(
                "messages",
                mensagens=[
                    {"role": m.role, "texto": truncate_text(m.content or "", 400)}
                    for m in historico
                ],
            )
            trace.write(
                "final",
                motivo=motivo,
                texto=texto_final,
                passos=passos,
                chamadas=total_chamadas,
                tokens_prompt=usage.prompt_tokens,
                tokens_resposta=usage.completion_tokens,
            )
            emitter.emit(
                "final",
                {
                    "text": texto_final,
                    "stopped_reason": motivo,
                    "steps": passos,
                    "tool_calls": total_chamadas,
                    "trace_id": trace_id,
                },
            )
            log.info(
                "tarefa %s terminou: motivo=%s passos=%d chamadas=%d",
                trace_id,
                motivo,
                passos,
                total_chamadas,
            )
            return AgentResult(
                text=texto_final,
                steps=passos,
                tool_calls=total_chamadas,
                ok=(motivo == "done"),
                stopped_reason=motivo,
                usage=usage,
                trace_id=trace_id,
            )
        finally:
            estado.active = False
            trace.close()

    # --------------------------------------------------------- ferramentas

    def _resolver(
        self,
        chamada: ToolCall,
        ctx: ToolContext,
        confirm: ConfirmFn,
    ) -> tuple[ToolResult, ToolSpec | None, bool]:
        """Valida e executa UMA chamada; devolve ``(resultado, spec, era_invalida)``.

        Ferramenta inexistente ou argumento que o schema rejeita vira
        ``ToolResult(ok=False)`` para o LLM se corrigir — sem tocar no executor.
        """
        if chamada.name not in self._registry:
            return (
                ToolResult(
                    ok=False,
                    error=(
                        f"ferramenta inexistente: {chamada.name}. "
                        "Use uma das ferramentas enviadas nesta chamada."
                    ),
                ),
                None,
                True,
            )
        spec = self._registry.get(chamada.name).spec  # type: ignore[attr-defined]
        args = _normalizar_args(chamada.arguments)
        if args is None:
            return ToolResult(ok=False, error="argumentos nao formam um objeto JSON valido"), spec, True
        erro = validate_args(spec, args)
        if erro:
            return ToolResult(ok=False, error=f"argumentos invalidos em {chamada.name}: {erro}"), spec, True
        execucao = chamada if args is chamada.arguments else ToolCall(id=chamada.id, name=chamada.name, arguments=args)
        try:
            resultado = self._executor.execute(execucao, ctx, confirm)
        except Exception as exc:  # noqa: BLE001 - nem PolicyDenied escapa para o laço
            log.warning("executor falhou em %s: %s", chamada.name, exc)
            return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}"), spec, False
        if not isinstance(resultado, ToolResult):
            return ToolResult(ok=False, error="executor devolveu um tipo invalido"), spec, False
        return resultado, spec, False

    @staticmethod
    def _envolver_confirm(confirm: ConfirmFn, emitter: Emitter) -> ConfirmFn:
        """Repassa o ``confirm`` do chamador e emite o evento ``confirm``."""
        if not callable(confirm):  # pragma: no cover - defensivo
            return lambda _pedido: False

        def envolucro(pedido: ConfirmRequest) -> bool:
            try:
                aprovado = bool(confirm(pedido))
            except Exception:  # noqa: BLE001 - recusa em caso de dúvida
                log.warning("confirm falhou para %s", pedido.tool_name, exc_info=True)
                aprovado = False
            emitter.emit(
                "confirm",
                {
                    "tool_name": pedido.tool_name,
                    "risk": pedido.risk.name,
                    "reason": pedido.reason,
                    "hard_confirm": pedido.hard_confirm,
                    "approved": aprovado,
                },
            )
            return aprovado

        return envolucro

    def _texto_parada(self, detalhe: str, feitas: list[str]) -> str:
        """Resposta de voz para limites: o que foi feito e o que faltou, sem inventar."""
        cabecalho = _CABECALHOS.get(detalhe, _CABECALHOS["erro"])
        if feitas:
            corpo = "Deu para fazer: " + ", ".join(feitas[:4]) + "."
        else:
            corpo = "Nao cheguei a executar nenhuma ferramenta."
        return (
            f"{cabecalho} {corpo} O pedido ficou incompleto e eu nao vou inventar — "
            "me diz por onde seguir."
        )

    def _verificar(
        self,
        historico: list[ChatMessage],
        user_text: str,
        rascunho: str,
        usage: Usage,
        trace: TraceWriter,
    ) -> tuple[str, int]:
        """Uma passada de conferência (máx. 1): devolve (texto, chamadas_usadas)."""
        mensagens = list(historico) + verification_messages(user_text, rascunho)
        t0 = time.perf_counter()
        try:
            resposta = self._llm.chat(
                mensagens,
                None,
                difficulty="easy",
                max_tokens=MAX_TOKENS_VERIFY,
                temperature=0.1,
            )
        except Exception:  # noqa: BLE001 - sem verificação, seguimos com o rascunho
            log.warning("passada de verificacao falhou; mantendo a resposta original")
            return rascunho, 0
        usage.prompt_tokens += resposta.usage.prompt_tokens
        usage.completion_tokens += resposta.usage.completion_tokens
        trace.write(
            "llm",
            papel="verificacao",
            dificuldade="easy",
            tokens_prompt=resposta.usage.prompt_tokens,
            tokens_resposta=resposta.usage.completion_tokens,
            ms=round((time.perf_counter() - t0) * 1000, 1),
        )
        texto = (resposta.message.content or "").strip()
        if not texto or (len(texto) < 10 and len(rascunho) > 40):
            return rascunho, 1
        return texto, 1

    # ------------------------------------------------------------- memória

    def _skills_catalogo(self) -> str:
        try:
            return self._skills.catalog_prompt() or ""
        except Exception:  # noqa: BLE001
            log.warning("catalog_prompt falhou", exc_info=True)
            return ""

    def _recuperar(self, user_text: str) -> list:
        try:
            return list(self._memory.recall(user_text, k=5))
        except Exception:  # noqa: BLE001
            log.warning("recall falhou", exc_info=True)
            return []

    def _turnos_recentes(self, session_id: str) -> list[ChatMessage]:
        try:
            turnos = self._memory.recent_turns(session_id, TURNOS_MEMORIA)
        except Exception:  # noqa: BLE001
            log.warning("recent_turns falhou", exc_info=True)
            return []
        saida: list[ChatMessage] = []
        for turno in turnos:
            if turno.role in ("user", "assistant"):
                saida.append(
                    ChatMessage(
                        role=turno.role,
                        content=truncate_text(turno.content or "", 600),
                    )
                )
        return saida

    def _guardar_turnos(self, session_id: str, user_text: str, resposta: str) -> None:
        """Grava o turno na memória (com segredos redigidos) após cada resposta."""
        for papel, conteudo in (("user", user_text), ("assistant", resposta)):
            try:
                self._memory.add_turn(
                    session_id, papel, redact_secrets(truncate_text(conteudo, 600))
                )
            except Exception:  # noqa: BLE001
                log.warning("add_turn falhou", exc_info=True)

    # -------------------------------------------------------- utilitários

    def _lock_for(self, session_id: str) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[session_id] = lock
            return lock

    def _state_for(self, session_id: str) -> TaskState | None:
        with self._guard:
            return self._states.get(session_id)


__all__ = ["ArisAgent"]
