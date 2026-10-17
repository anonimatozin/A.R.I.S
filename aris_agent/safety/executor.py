"""``SafeExecutor``: implementa o protocolo ``ToolExecutor`` do contrato.

Fluxo: kill switch → ferramenta → schema → política → proteções de laço →
confirmação (timeout = negar) → execução com timeout/cancel → redação e
truncamento → taint → auditoria → ``ToolResult``. Nenhuma exceção vaza.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time

from ..contract.errors import ToolError
from ..contract.types import (
    ConfirmFn,
    ConfirmRequest,
    Risk,
    ToolCall,
    ToolContext,
    ToolResult,
    ToolSpec,
)
from ..contract.utils import redact_secrets, truncate_text, wrap_untrusted
from ..tools.registry import ToolRegistry
from .audit import AuditLogger
from .injection import scan_untrusted
from .killswitch import KillSwitch
from .limits import LoopGuard
from .policy import PolicyEngine
from .schema import validate_args
from .settings import SafetySettings

log = logging.getLogger("aris.agent.safety.executor")

# Chave de configuração cujo valor inteiro é credencial (vira [REDACTED]).
_SECRET_KEY_RE = re.compile(
    r"(?i)^(?:[a-z0-9]*[_-])?(?:"
    r"api[_-]?key|apikey|access[_-]?token|auth[_-]?token|refresh[_-]?token|token|"
    r"password|passwd|pwd|secret(?:[_-]?key)?|client[_-]?secret|private[_-]?key|"
    r"authorization|chave|senha|credential[s]?)$"
)


def redact_args(arguments) -> dict:
    """Cópia dos argumentos para auditoria, com credenciais substituídas."""
    if not isinstance(arguments, dict):
        return {"_valor": truncate_text(redact_secrets(str(arguments)), 200)}
    out: dict = {}
    for key, value in (arguments or {}).items():
        name = str(key)
        if _SECRET_KEY_RE.match(name.strip()):
            out[name] = "[REDACTED]"
        elif isinstance(value, str):
            out[name] = redact_secrets(value)
        elif value is None or isinstance(value, (int, float, bool)):
            out[name] = value
        else:
            text = json.dumps(value, ensure_ascii=False, default=str)
            out[name] = truncate_text(redact_secrets(text), 300)
    return out


def _err(message: str) -> ToolResult:
    return ToolResult(ok=False, error=message)


class SafeExecutor:
    """Executor com política: a única porta de entrada para ``tool.run()``."""

    def __init__(
        self,
        registry: ToolRegistry,
        config,
        *,
        kill_switch: KillSwitch | None = None,
        audit: AuditLogger | None = None,
        settings: SafetySettings | None = None,
    ) -> None:
        self.registry = registry
        self.config = config
        self.settings = settings or SafetySettings.from_section(config.section("safety"), config)
        self.policy = PolicyEngine(config, self.settings)
        self.guard = LoopGuard(
            repeat_limit=self.settings.repeat_limit,
            per_minute=self.settings.exec_per_minute,
            per_task=self.settings.exec_per_task,
        )
        self.kill_switch = kill_switch or KillSwitch(
            config.data_dir,
            enable_hotkey=self.settings.enable_hotkey,
            hotkey=self.settings.hotkey,
        )
        if self.settings.enable_hotkey:
            self.kill_switch.start_hotkey()
        self.audit = audit or AuditLogger(
            config.audit_log_path, max_bytes=self.settings.audit_max_bytes
        )

    # ------------------------------------------------------------ confirmação

    def _ask(self, confirm: ConfirmFn, request: ConfirmRequest) -> tuple[bool, str | None]:
        """Chama a ``ConfirmFn`` com timeout; timeout/erro = negar."""
        timeout = self.settings.resolve_confirm_timeout(self.config)
        box: dict = {}

        def _target() -> None:
            try:
                box["ok"] = bool(confirm(request))
            except Exception as exc:  # noqa: BLE001 - ConfirmFn é código de terceiros
                log.warning("ConfirmFn lançou exceção: %s", exc)
                box["err"] = f"{type(exc).__name__}: {exc}"

        worker = threading.Thread(target=_target, daemon=True, name="aris-confirm")
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            return False, f"timeout após {timeout:g}s (sem resposta = negar)"
        if "err" in box:
            return False, f"erro na confirmação: {box['err']}"
        return bool(box.get("ok", False)), None

    # --------------------------------------------------------------- execução

    def _run(self, tool, args: dict, ctx: ToolContext, spec: ToolSpec) -> ToolResult:
        """Roda a ferramenta em thread, com timeout, cancel e kill switch."""
        box: dict = {}

        def _target() -> None:
            try:
                box["r"] = tool.run(args, ctx)
            except Exception as exc:  # noqa: BLE001 - nada escapa para o laço
                log.exception("ferramenta %s lançou exceção", spec.name)
                box["e"] = f"{type(exc).__name__}: {exc}"

        worker = threading.Thread(target=_target, daemon=True, name=f"aris-tool-{spec.name}")
        worker.start()
        deadline = time.monotonic() + max(0.1, float(spec.timeout_s))
        while worker.is_alive():
            if ctx.cancel.is_set():
                return _err(f"cancelado pelo agente durante {spec.name}")
            self.kill_switch.check_sentinel()
            if self.kill_switch.engaged:
                ctx.cancel.set()
                return _err(f"kill switch ativo ({self.kill_switch.reason}): execução abortada")
            if time.monotonic() >= deadline:
                return _err(
                    f"timeout de {spec.timeout_s:g}s atingido em {spec.name}; a chamada foi "
                    "abandonada (o processo da ferramenta pode ter continuado em segundo plano)"
                )
            worker.join(0.05)
        if "e" in box:
            return _err(box["e"])
        result = box.get("r")
        if not isinstance(result, ToolResult):
            return _err(
                f"ferramenta {spec.name} devolveu {type(result).__name__} em vez de ToolResult"
            )
        return result

    def _postprocess(
        self, result: ToolResult, spec: ToolSpec, args: dict, ctx: ToolContext
    ) -> ToolResult:
        """Redige segredos, trunca, envolve conteúdo não confiável e marca taint."""
        max_chars = int(getattr(self.config, "max_tool_chars", 8000) or 8000)
        content = result.content if isinstance(result.content, str) else str(result.content or "")
        error = str(result.error) if result.error else None
        if content:
            content = redact_secrets(content)
            if spec.untrusted_output and "<conteudo_nao_confiavel" not in content:
                content = wrap_untrusted(content, self._source(spec, args))
            content = truncate_text(content, max_chars)
        if error:
            error = truncate_text(redact_secrets(error), 1000)
        return ToolResult(
            ok=bool(result.ok),
            content=content,
            data=result.data,
            error=error,
            artifacts=list(result.artifacts or []),
        )

    @staticmethod
    def _source(spec: ToolSpec, args: dict) -> str:
        """Origem do conteúdo não confiável para o ``wrap_untrusted``."""
        for name in spec.url_args:
            value = (args or {}).get(name)
            if isinstance(value, str) and value.strip():
                return value[:200]
        return spec.name

    # -------------------------------------------------------------- auditoria

    @staticmethod
    def _summary(result: ToolResult) -> str:
        """Resumo curto sem conteúdo de arquivos (só status e tamanho)."""
        if result.ok:
            base = f"ok, {len(result.content or '')} caracteres"
            if result.artifacts:
                base += f", {len(result.artifacts)} artefato(s)"
            return base
        return truncate_text(redact_secrets(str(result.error or "erro")), 300)

    def _record(
        self,
        call: ToolCall,
        ctx: ToolContext,
        result: ToolResult,
        spec: ToolSpec | None,
        decision: str,
        reason: str,
        confirmed: bool | None,
        duration_s: float,
        risk: Risk | None,
    ) -> None:
        effective = risk or (spec.risk if spec else None)
        event = {
            "session_id": ctx.session_id,
            "tool": call.name,
            "args": redact_args(call.arguments),
            "risk": effective.name if isinstance(effective, Risk) else None,
            "decision": decision,
            "reason": truncate_text(reason or "", 300),
            "confirmed": confirmed,
            "duration_ms": int(duration_s * 1000),
            "ok": bool(result.ok),
            "error": (
                truncate_text(redact_secrets(str(result.error)), 300) if result.error else None
            ),
            "resumo": self._summary(result),
            "taint": bool(ctx.taint),
            "mode": self.settings.mode,
            "injection": scan_untrusted(result.content or "") if result.content else [],
        }
        if self.settings.audit_preview and result.ok and result.content:
            event["preview"] = truncate_text(redact_secrets(str(result.content)), 200)
        self.audit.record(event)

    # ---------------------------------------------------------------- fluxo

    def execute(
        self, call: ToolCall, ctx: ToolContext, confirm: ConfirmFn | None = None
    ) -> ToolResult:
        """Executa ``call`` aplicando política, confirmação, timeout e auditoria."""
        started = time.monotonic()
        spec_box: dict[str, ToolSpec] = {}

        def finish(
            result: ToolResult,
            *,
            decision: str,
            why: str,
            risk: Risk | None = None,
            confirmed: bool | None = None,
        ) -> ToolResult:
            self._record(
                call,
                ctx,
                result,
                spec_box.get("spec"),
                decision,
                why,
                confirmed,
                time.monotonic() - started,
                risk,
            )
            return result

        # 0) interruptor de emergência
        self.kill_switch.check_sentinel()
        if self.kill_switch.engaged:
            return finish(
                _err(f"kill switch ativo ({self.kill_switch.reason}): novas chamadas bloqueadas"),
                decision="deny",
                why="kill switch ativo",
            )

        # 1) cancelamento pré-existente
        if ctx.cancel.is_set():
            return finish(
                _err("cancelado pelo agente antes da execução"),
                decision="deny",
                why="cancelado",
            )

        # 2) ferramenta registrada
        try:
            tool = self.registry.get(call.name)
        except ToolError as exc:
            return finish(_err(str(exc)), decision="deny", why="ferramenta desconhecida")
        spec = getattr(tool, "spec", None)
        if not isinstance(spec, ToolSpec) or not callable(getattr(tool, "run", None)):
            return finish(
                _err(f"ferramenta {call.name} inválida (sem spec/run)"),
                decision="deny",
                why="ferramenta inválida",
            )
        spec_box["spec"] = spec

        # 3) argumentos
        args = call.arguments if call.arguments is not None else {}
        if not isinstance(args, dict):
            return finish(
                _err("argumentos inválidos: esperado um objeto JSON"),
                decision="deny",
                why="schema inválido",
                risk=spec.risk,
            )

        # 4) validação de schema
        schema_error = validate_args(spec.parameters, args)
        if schema_error:
            return finish(
                _err(f"argumentos inválidos para {spec.name}: {schema_error}"),
                decision="deny",
                why="validação de schema",
                risk=spec.risk,
            )

        # 5) política por risco
        decision = self.policy.decide(spec, args, ctx)
        if decision.action == "deny":
            return finish(
                _err(f"negado pela política de segurança: {decision.reason}"),
                decision="deny",
                why=decision.reason,
                risk=decision.risk,
            )

        # 6) proteções de laço (repetição e limites por minuto/tarefa)
        key = LoopGuard.canonical(spec.name, args)
        limit_msg = self.guard.check(key, decision.risk, ctx.session_id)
        if limit_msg:
            return finish(
                _err(f"limite do agente: {limit_msg}"),
                decision="deny",
                why=limit_msg,
                risk=decision.risk,
            )

        # 7) confirmação (timeout = negar)
        confirmed: bool | None = None
        if decision.action == "confirm":
            if confirm is None:
                return finish(
                    _err(
                        f"ação requer confirmação ({decision.reason}), mas não há "
                        "função de confirmação disponível"
                    ),
                    decision="deny",
                    why="sem ConfirmFn",
                    risk=decision.risk,
                    confirmed=False,
                )
            request = ConfirmRequest(
                tool_name=spec.name,
                args_preview=decision.preview,
                risk=decision.risk,
                reason=decision.reason,
                hard_confirm=decision.hard,
            )
            approved, problem = self._ask(confirm, request)
            if not approved:
                if problem:
                    why = f"confirmação não obtida: {problem}"
                    message = f"confirmação não obtida ({problem}): {decision.reason}"
                else:
                    why = "usuário negou"
                    message = f"usuário negou a confirmação: {decision.reason}"
                return finish(
                    _err(message),
                    decision="deny",
                    why=why,
                    risk=decision.risk,
                    confirmed=False,
                )
            confirmed = True

        # 8) execução com timeout/cancel
        self.kill_switch.register(ctx.cancel)
        result = self._run(tool, args, ctx, spec)
        if spec.untrusted_output:
            ctx.taint = True
        result = self._postprocess(result, spec, args, ctx)
        return finish(
            result,
            decision=decision.action,
            why=decision.reason,
            risk=decision.risk,
            confirmed=confirmed,
        )
