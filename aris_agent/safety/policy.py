"""Política por risco: decide ``allow`` / ``confirm`` / ``deny`` para uma chamada.

Ordem das verificações (a negação absoluta nunca vira confirmação):
nomes reservados → cofres de credenciais → comando proibido → modo readonly →
risco efetivo → alvos protegidos → lote → regra por risco → taint.
"""

from __future__ import annotations

import logging
import re

from ..contract.types import Risk, ToolContext, ToolSpec
from ..contract.utils import redact_secrets
from . import commands as cmds
from . import paths as pathutil
from .settings import SafetySettings

log = logging.getLogger("aris.agent.safety.policy")

_BATCH_TEXT_RE = re.compile(r"^(?:todos?|todas?|tudo|all|any)\b", re.IGNORECASE)
_ALL_KEYS = frozenset(
    {"all", "select_all", "todos", "todas", "delete_all", "apagar_tudo", "incluir_todos", "marcar_todos"}
)
_INTERPRETERS = frozenset({"python", "python3", "py"})


class Decision:
    """Resultado da política: ação, motivo, se exige confirmação forte e prévia."""

    __slots__ = ("action", "reason", "hard", "risk", "preview")

    def __init__(
        self,
        action: str,
        reason: str = "",
        *,
        hard: bool = False,
        risk: Risk = Risk.READ,
        preview: str = "",
    ) -> None:
        self.action = action  # "allow" | "confirm" | "deny"
        self.reason = reason
        self.hard = hard
        self.risk = risk
        self.preview = preview

    def __repr__(self) -> str:  # pragma: no cover - debug
        return f"<Decision {self.action} hard={self.hard} {self.reason!r}>"


class PolicyEngine:
    """Aplica a política descrita no README de ``aris_agent/safety``."""

    def __init__(self, config, settings: SafetySettings) -> None:
        self.config = config
        self.settings = settings

    # ------------------------------------------------------------- utilitários

    def _raw_paths(self, spec: ToolSpec, args: dict) -> list[str]:
        out: list[str] = []
        for name in spec.path_args:
            value = args.get(name)
            if isinstance(value, list):
                out.extend(str(v) for v in value if str(v).strip())
            elif value is not None and str(value).strip():
                out.append(str(value))
        return out

    def _resolve(self, spec: ToolSpec, args: dict, ctx: ToolContext) -> list[tuple[str, object]]:
        """Devolve ``(raw, caminho_resolvido, tem_curinga)`` para cada path_arg."""
        out: list[tuple[str, object]] = []
        for raw in self._raw_paths(spec, args):
            clean = pathutil.strip_extended_prefix(raw)
            base, wildcard = pathutil.split_wildcard_prefix(clean)
            target = base if wildcard and base.strip() else clean
            try:
                resolved = pathutil.resolve_path(target, ctx.workdir)
            except OSError:  # pragma: no cover - defensivo
                log.warning("não consegui resolver %r", raw)
                continue
            out.append((raw, resolved, wildcard))
        return out

    def _command_text(self, spec: ToolSpec, args: dict) -> str:
        if spec.command_arg:
            value = args.get(spec.command_arg)
            if isinstance(value, str):
                return value
        return ""

    def _detect_batch(
        self, spec: ToolSpec, args: dict, resolved: list[tuple[str, object]]
    ) -> str | None:
        """Muitos caminhos, curingas ou seleção "todos ..." => ação em lote."""
        total = 0
        for _raw, _path, wildcard in resolved:
            if wildcard:
                return "curinga (*) na seleção de caminhos"
            total += 1
        if total >= self.settings.batch_path_threshold:
            return f"{total} caminhos em uma única chamada"
        for key, value in args.items():
            if key in spec.path_args:
                continue
            if isinstance(value, bool) and value and str(key).lower() in _ALL_KEYS:
                return f"seleção geral ({key}=true)"
            if isinstance(value, str) and _BATCH_TEXT_RE.match(value.strip()):
                return f"seleção geral ({key}={value.strip()[:40]!r})"
        return None

    def _balanced_exec_ok(
        self, cmd: str, resolved: list[tuple[str, object]], roots: list
    ) -> bool:
        """Modo balanced: comando de verbo seguro com alvos 100% dentro das raízes."""
        allowed = self.settings.exec_allowlist + self.settings.balanced_verbs + ("python", "py")
        if not cmds.balanced_segments_ok(cmd, allowed):
            return False
        text = cmds.normalize_command(cmd)
        first = cmds.first_program(cmds.strip_wrappers(cmds.split_segments(text)[0]))
        if first in _INTERPRETERS and not any(
            tok.endswith((".py", ".pyw")) for tok in text.split()
        ):
            return False  # python -c continua exigindo confirmação
        for cpath in pathutil.command_paths(text):
            if not any(pathutil.is_within(cpath, root) for root in roots):
                return False
        if resolved and not pathutil.all_within([p for _r, p, _w in resolved], roots):
            return False
        return True

    def _preview(
        self,
        spec: ToolSpec,
        args: dict,
        resolved: list[tuple[str, object]],
        effective: Risk,
        cmd: str,
    ) -> str:
        """Pré-visualização legível e sem segredos do que será feito."""
        parts: list[str] = []
        for key, value in (args or {}).items():
            text = redact_secrets(str(value))
            if len(text) > 140:
                text = text[:137] + "..."
            parts.append(f"{key}={text}")
        lines = ["; ".join(parts) if parts else "(sem argumentos)"]
        targets = [p for _raw, p, _wc in resolved]
        if cmd and effective >= Risk.DESTRUCTIVE:
            targets += pathutil.command_paths(cmds.normalize_command(cmd))
        if effective >= Risk.DESTRUCTIVE and targets:
            lines.append("alvos resolvidos:")
            for target in targets:
                count = pathutil.count_files(target)
                suffix = f" ({count} arquivo(s))" if count is not None else ""
                lines.append(f"  - {target}{suffix}")
        return "\n".join(lines)[:800]

    # --------------------------------------------------------------- decisões

    @staticmethod
    def _deny(reason: str, risk: Risk) -> Decision:
        return Decision("deny", reason, risk=risk)

    @staticmethod
    def _allow(reason: str, risk: Risk) -> Decision:
        return Decision("allow", reason, risk=risk)

    def _confirm(
        self,
        reason: str,
        hard: bool,
        risk: Risk,
        spec: ToolSpec,
        args: dict,
        resolved: list[tuple[str, object]],
        cmd: str,
    ) -> Decision:
        preview = self._preview(spec, args, resolved, risk, cmd)
        return Decision("confirm", reason, hard=hard, risk=risk, preview=preview)

    def decide(self, spec: ToolSpec, args: dict, ctx: ToolContext) -> Decision:
        """Decide se a chamada é permitida, exige confirmação ou é negada."""
        settings = self.settings
        risk = spec.risk
        cmd = self._command_text(spec, args)

        # 1) nomes reservados / namespace de dispositivo
        for raw in self._raw_paths(spec, args):
            reason = pathutil.device_reason(raw)
            if reason:
                return self._deny(f"caminho inválido: {reason}", risk)

        # 2) cofres de credenciais nos caminhos declarados
        resolved = self._resolve(spec, args, ctx)
        for _raw, path, _wc in resolved:
            reason = pathutil.sensitive_path_reason(path)
            if reason:
                return self._deny(f"acesso negado (cofre de credenciais: {reason})", risk)

        # 3) comando negado absolutamente + cofres citadas no comando
        if cmd:
            reason = cmds.denied_command_reason(cmd)
            if reason:
                return self._deny(f"comando negado pela política: {reason}", risk)
            for cpath in pathutil.command_paths(cmds.normalize_command(cmd)):
                sreason = pathutil.sensitive_path_reason(cpath)
                if sreason:
                    return self._deny(f"acesso negado (cofre de credenciais: {sreason})", risk)

        # 4) modo somente leitura (a negação absoluta acima continua valendo)
        if settings.mode == "readonly" and risk > Risk.READ:
            return self._deny("modo somente leitura (safety.mode=readonly): apenas READ é permitido", risk)

        # 5) risco efetivo: comando destrutivo sobe para DESTRUCTIVE
        effective = risk
        if cmd and cmds.destructive_command_reason(cmd) and effective < Risk.DESTRUCTIVE:
            effective = Risk.DESTRUCTIVE

        # 6) ação em lote
        batch_reason = self._detect_batch(spec, args, resolved)

        # 7) alvos protegidos (raiz de disco, pastas de sistema, pasta do usuário)
        if effective >= Risk.WRITE or batch_reason:
            targets = [p for _raw, p, _wc in resolved]
            if cmd and effective >= Risk.DESTRUCTIVE:
                targets += pathutil.command_paths(cmds.normalize_command(cmd))
            for target in targets:
                preason = pathutil.protected_target_reason(target)
                if preason:
                    label = "ação em lote" if batch_reason else "operação"
                    return self._deny(f"{label} negada em área protegida ({preason})", effective)

        # 8) lote sempre pede confirmação forte
        if batch_reason:
            return self._confirm(
                f"ação em lote: {batch_reason}", True, effective, spec, args, resolved, cmd
            )

        # 9) regra por risco
        if effective == Risk.READ:
            decision = self._allow("leitura", effective)
        elif effective == Risk.WRITE:
            paths_list = [p for _raw, p, _wc in resolved]
            if paths_list and pathutil.all_within(paths_list, pathutil.resolved_roots(self.config)):
                decision = self._allow("escrita dentro das raízes permitidas", effective)
            elif paths_list:
                decision = self._confirm(
                    "escrita fora das raízes permitidas", False, effective, spec, args, resolved, cmd
                )
            else:
                decision = self._confirm(
                    "escrita sem caminho verificável", False, effective, spec, args, resolved, cmd
                )
        elif effective == Risk.EXEC:
            if spec.name in settings.exec_allowlist:
                decision = self._allow("ferramenta na lista de permissões", effective)
            elif cmd and cmds.is_allowlisted_command(cmd, settings.exec_allowlist):
                decision = self._allow("comando na lista de permissões", effective)
            elif settings.mode == "balanced" and cmd and self._balanced_exec_ok(cmd, resolved, pathutil.resolved_roots(self.config)):
                decision = self._allow("comando seguro dentro do workspace (modo balanced)", effective)
            else:
                decision = self._confirm(
                    "execução de comando/app requer confirmação", False, effective, spec, args, resolved, cmd
                )
        else:  # DESTRUCTIVE
            decision = self._confirm(
                "ação destrutiva: exige confirmação forte", True, effective, spec, args, resolved, cmd
            )

        # 10) contaminação (taint): depois de conteúdo não confiável, força
        #     confirmação forte para EXEC/DESTRUCTIVE/envio para fora.
        if ctx.taint and decision.action != "deny" and (
            effective >= Risk.EXEC or bool(spec.url_args)
        ):
            decision = self._confirm(
                f"{decision.reason}; esta ação veio depois de ler conteúdo externo",
                True,
                effective,
                spec,
                args,
                resolved,
                cmd,
            )
        return decision
