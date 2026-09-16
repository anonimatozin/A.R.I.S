"""Parser multi-intent baseado em LLM.

Usa o LLM para segmentar e parsear texto do usuário em múltiplas
ações estruturadas, retornando um ExecutionPlan. Combina entendimento
semântico do LLM com validação determinística.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from .dependencies import (
    analyze_dependencies,
    classify_action_type,
    detect_relation_type,
    detect_trigger_event,
)
from .models import (
    ActionDependency,
    ActionStatus,
    ActionTrigger,
    ActionType,
    ExecutionPlan,
    PlanAction,
    PlanStatus,
    RelationType,
    TemporalInfo,
)
from .segmenter import Segmenter, TextSegment
from .temporal import parse_temporal

logger = logging.getLogger(__name__)


# Mapeamento de tipo de ação -> tool name
_ACTION_TO_TOOL: dict[str, str] = {
    "shutdown": "pc_shutdown",
    "restart": "pc_restart",
    "lock": "pc_lock",
    "sleep": "pc_sleep",
    "wake": "wake_on_lan",
    "schedule_shutdown": "schedule_shutdown",
    "schedule_wake": "schedule_wake",
    "cancel_schedule": "cancel_shutdown",
    "open_app": "pc_run_command",
    "open_url": "pc_run_command",
    "open_browser": "pc_run_command",
    "search_web": "pc_run_command",
    "search_files": "pc_search_files",
    "read_file": "pc_read_file",
    "write_file": "pc_write_file",
    "run_command": "pc_run_command",
    "reminder_create": "reminder_create",
    "reminder_cancel": "reminder_cancel",
    "memory_store": "memory_store",
    "memory_search": "memory_search",
    "email_list": "email_list",
    "email_read": "email_read",
    "system_status": "pc_system_status",
}

# Mapeamento de apps conhecidos
_KNOWN_APPS: dict[str, str] = {
    "spotify": "Spotify",
    "vscode": "VS Code",
    "vs code": "VS Code",
    "visual studio code": "VS Code",
    "discord": "Discord",
    "navegador": "navegador",
    "browser": "navegador",
    "chrome": "Google Chrome",
    "firefox": "Firefox",
    "edge": "Microsoft Edge",
    "opera": "Opera",
    "brave": "Brave",
    "terminal": "terminal",
    "cmd": "cmd",
    "powershell": "PowerShell",
    "explorer": "explorador",
    "notepad": "Bloco de Notas",
    "word": "Word",
    "excel": "Excel",
    "ppt": "PowerPoint",
    "youtube": "YouTube",
    "github": "GitHub",
    "steam": "Steam",
    "blender": "Blender",
    "photoshop": "Photoshop",
    "vim": "Vim",
    "sublime": "Sublime Text",
    "atom": "Atom",
    "postman": "Postman",
    "slack": "Slack",
    "teams": "Microsoft Teams",
    "zoom": "Zoom",
    "skype": "Skype",
    "telegram": "Telegram",
    "whatsapp": "WhatsApp",
}


# Prompt para o LLM
_PLANNER_PROMPT = """Você é um parser de comandos. Analise o texto do usuário e retorne um JSON com as ações identificadas.

REGRAS:
1. Cada ação separada por conectivos (e, depois, então, quando, etc.) é uma ação diferente
2. Liste TODAS as ações encontradas, mesmo que sejam muitas
3. Para cada ação, identifique: tipo, parâmetros, relações temporais, dependências
4. Se uma ação depende de outra (ex: "quando ligar"), marque como condicional
5. Se há horário, extraia o horário exato
6. Não invente informações que não estão no texto
7. Normalize nomes de apps (ex: "vscode" -> "VS Code")
8. Se o texto contém erros de digitação, tente corrigir

TIPOS DE AÇÃO VÁLIDOS:
- shutdown: desligar PC
- restart: reiniciar PC
- lock: travar PC
- sleep: suspender PC
- wake: ligar PC (WoL)
- schedule_shutdown: agendar desligamento
- schedule_wake: agendar ligamento
- cancel_schedule: cancelar agendamento
- open_app: abrir aplicativo
- open_url: abrir site/URL
- open_browser: abrir navegador
- search_web: pesquisar na web
- search_files: pesquisar arquivos
- read_file: ler arquivo
- write_file: escrever/salvar arquivo
- run_command: executar comando
- reminder_create: criar lembrete
- reminder_cancel: cancelar lembrete
- memory_store: salvar na memória
- memory_search: buscar na memória
- email_list: listar emails
- email_read: ler email
- system_status: verificar status

RELACIONAMENTOS:
- sequential: uma depois da outra
- temporal: agendada para horário específico
- conditional: depende de um evento (quando ligar, quando abrir)
- dependency: precisa que outra ação termine primeiro
- parallel: pode rodar ao mesmo tempo

RESPONDA APENAS COM JSON (sem markdown, sem ```):
{
  "actions": [
    {
      "type": "tipo_da_acao",
      "description": "descrição em português",
      "parameters": {"parametro": "valor"},
      "temporal": {"time_str": "HH:MM", "is_relative": false} ou null,
      "trigger": {"event": "evento", "description": "quando X"} ou null,
      "relation": "sequential|temporal|conditional|dependency|parallel"
    }
  ]
}

EXEMPLOS:

Input: "desliga o pc às 15 e liga às 16:30"
Output: {"actions": [{"type": "schedule_shutdown", "description": "Desligar PC às 15:00", "parameters": {}, "temporal": {"time_str": "15:00", "is_relative": false}, "trigger": null, "relation": "temporal"}, {"type": "schedule_wake", "description": "Ligar PC às 16:30", "parameters": {}, "temporal": {"time_str": "16:30", "is_relative": false}, "trigger": null, "relation": "temporal"}]}

Input: "abre spotify e discord"
Output: {"actions": [{"type": "open_app", "description": "Abrir Spotify", "parameters": {"app": "Spotify"}, "temporal": null, "trigger": null, "relation": "parallel"}, {"type": "open_app", "description": "Abrir Discord", "parameters": {"app": "Discord"}, "temporal": null, "trigger": null, "relation": "parallel"}]}

Input: "desliga às 15 e quando ligar abre spotify"
Output: {"actions": [{"type": "schedule_shutdown", "description": "Desligar PC às 15:00", "parameters": {}, "temporal": {"time_str": "15:00", "is_relative": false}, "trigger": null, "relation": "temporal"}, {"type": "open_app", "description": "Abrir Spotify quando ligar", "parameters": {"app": "Spotify"}, "temporal": null, "trigger": {"event": "system_start", "description": "quando o PC ligar"}, "relation": "conditional"}]}

Input: "abre o navegador e pesquisa minecraft"
Output: {"actions": [{"type": "open_browser", "description": "Abrir navegador", "parameters": {}, "temporal": null, "trigger": null, "relation": "sequential"}, {"type": "search_web", "description": "Pesquisar Minecraft", "parameters": {"query": "Minecraft"}, "temporal": null, "trigger": null, "relation": "dependency"}]}

Input: "daqui 2 horas abre o navegador pesquisa minecraft e depois abre o discord"
Output: {"actions": [{"type": "open_browser", "description": "Abrir navegador em 2 horas", "parameters": {}, "temporal": {"time_str": "relativo", "is_relative": true, "relative_hours": 2}, "trigger": null, "relation": "temporal"}, {"type": "search_web", "description": "Pesquisar Minecraft", "parameters": {"query": "Minecraft"}, "temporal": null, "trigger": null, "relation": "dependency"}, {"type": "open_app", "description": "Abrir Discord", "parameters": {"app": "Discord"}, "temporal": null, "trigger": null, "relation": "sequential"}]}


Agora analise este texto:
"""


class MultiIntentParser:
    """Parser multi-intent usando LLM + validação determinística.

    Pipeline:
    1. Segmentação de texto (regex + conectivos)
    2. LLM parsing (segmentação semântica + extração de entidades)
    3. Validação determinística (parâmetros, horários, tools)
    4. Análise de dependências
    5. Geração do ExecutionPlan
    """

    def __init__(self, llm_router=None):
        self._llm = llm_router
        self._segmenter = Segmenter()
        self._debug = False

    def set_debug(self, debug: bool) -> None:
        """Ativa/desativa modo debug."""
        self._debug = debug

    def parse(self, text: str) -> ExecutionPlan:
        """Parse principal: texto -> ExecutionPlan.

        Tenta LLM primeiro. Se falhar, usa fallback determinístico.
        """
        plan = ExecutionPlan(original_text=text)

        if self._debug:
            logger.info(f"[PLANNER] Input: {text}")

        # 1. Segmentação inicial
        segments = self._segmenter.segment(text)
        if self._debug:
            logger.info(f"[PLANNER] Segments: {[str(s) for s in segments]}")

        # 2. Tentar LLM
        if self._llm and self._llm.available:
            try:
                plan = self._parse_with_llm(text, plan)
            except Exception as e:
                logger.warning(f"LLM parsing failed: {e}, using fallback")
                plan = self._parse_deterministic(text, segments, plan)
        else:
            plan = self._parse_deterministic(text, segments, plan)

        # 3. Análise de dependências
        deps = analyze_dependencies(plan.actions)
        plan.dependencies = deps

        # 4. Validação
        plan = self._validate_plan(plan)

        # 5. Gerar resumo
        plan.summary = self._generate_summary(plan)

        if self._debug:
            logger.info(f"[PLANNER] Plan: {json.dumps(plan.to_dict(), indent=2, ensure_ascii=False)}")

        return plan

    def _parse_with_llm(self, text: str, plan: ExecutionPlan) -> ExecutionPlan:
        """Usa LLM para parse semântico."""
        prompt = _PLANNER_PROMPT + text

        response = self._llm.send(
            prompt,
            temperature=0.1,
            max_tokens=2000,
        )

        if not response:
            raise ValueError("LLM returned empty response")

        # Limpar response
        response = response.strip()
        if response.startswith("```"):
            response = re.sub(r"^```\w*\n?", "", response)
            response = re.sub(r"\n?```$", "", response)
            response = response.strip()

        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            # Tentar extrair JSON da resposta
            m = re.search(r"\{.*\}", response, re.DOTALL)
            if m:
                data = json.loads(m.group())
            else:
                raise ValueError(f"Could not parse LLM response as JSON: {response[:200]}")

        actions_data = data.get("actions", [])
        if not actions_data:
            raise ValueError("LLM returned no actions")

        for action_data in actions_data:
            action = self._build_action_from_llm(action_data)
            plan.add_action(action)

        return plan

    def _build_action_from_llm(self, data: dict) -> PlanAction:
        """Constrói PlanAction a partir de dados do LLM."""
        action_type_str = data.get("type", "unknown")
        try:
            action_type = ActionType(action_type_str)
        except ValueError:
            action_type = ActionType.UNKNOWN

        # Temporal
        temporal = None
        temporal_data = data.get("temporal")
        if temporal_data:
            temporal = TemporalInfo(
                time_str=temporal_data.get("time_str"),
                is_relative=temporal_data.get("is_relative", False),
                relative_hours=temporal_data.get("relative_hours"),
                relative_minutes=temporal_data.get("relative_minutes"),
            )
            if temporal.time_str and not temporal.is_relative:
                try:
                    parts = temporal.time_str.split(":")
                    now = datetime.now()
                    from datetime import timedelta
                    target = now.replace(hour=int(parts[0]), minute=int(parts[1]) if len(parts) > 1 else 0)
                    if target <= now:
                        target += timedelta(days=1)
                    temporal.time_value = target
                except Exception:
                    pass

        # Trigger
        trigger = None
        trigger_data = data.get("trigger")
        if trigger_data:
            trigger = ActionTrigger(
                trigger_type="conditional",
                trigger_event=trigger_data.get("event", ""),
                trigger_params={"description": trigger_data.get("description", "")},
            )

        # Tool name
        tool_name = _ACTION_TO_TOOL.get(action_type_str, "")

        # Parâmetros
        parameters = data.get("parameters", {})
        if action_type == ActionType.OPEN_APP and "app" in parameters:
            app_name = parameters["app"]
            parameters["app"] = _KNOWN_APPS.get(app_name.lower(), app_name)
            parameters["command"] = f'start "" "{parameters["app"]}"'
        elif action_type == ActionType.OPEN_BROWSER:
            parameters["command"] = "start http://google.com"
        elif action_type == ActionType.SEARCH_WEB:
            query = parameters.get("query", "")
            parameters["command"] = f"start https://www.google.com/search?q={query}"
        elif action_type == ActionType.SHUTDOWN:
            parameters["command"] = "shutdown /s /t 0"
        elif action_type == ActionType.RESTART:
            parameters["command"] = "shutdown /r /t 0"
        elif action_type == ActionType.LOCK:
            parameters["command"] = "rundll32.exe user32.dll,LockWorkStation"
        elif action_type == ActionType.SYSTEM_STATUS:
            parameters["command"] = "systeminfo"

        # Relation
        relation_str = data.get("relation", "sequential")
        try:
            relation = RelationType(relation_str)
        except ValueError:
            relation = RelationType.SEQUENTIAL

        # Confirmation required
        confirm_needed = action_type in (
            ActionType.SHUTDOWN,
            ActionType.RESTART,
        )

        return PlanAction(
            action_type=action_type,
            description=data.get("description", ""),
            tool_name=tool_name,
            parameters=parameters,
            temporal=temporal,
            trigger=trigger,
            relation=relation,
            confirmation_required=confirm_needed,
        )

    def _parse_deterministic(
        self, text: str, segments: list[TextSegment], plan: ExecutionPlan
    ) -> ExecutionPlan:
        """Fallback determinístico sem LLM."""
        for seg in segments:
            action_type = classify_action_type(seg.text)
            temporal = parse_temporal(seg.text)
            trigger_event = detect_trigger_event(seg.text)
            relation = detect_relation_type(seg.text)

            # Se o segmento é condicional mas não tem trigger no texto,
            # verificar o conector
            if not trigger_event and seg.is_conditional:
                trigger_event = detect_trigger_event(seg.connector)

            trigger = None
            if trigger_event:
                trigger = ActionTrigger(
                    trigger_type="conditional",
                    trigger_event=trigger_event,
                )

            parameters = self._extract_params_deterministic(seg.text, action_type)
            tool_name = _ACTION_TO_TOOL.get(action_type.value, "")

            confirm_needed = action_type in (ActionType.SHUTDOWN, ActionType.RESTART)

            action = PlanAction(
                action_type=action_type,
                description=seg.text,
                tool_name=tool_name,
                parameters=parameters,
                temporal=temporal,
                trigger=trigger,
                relation=relation,
                confirmation_required=confirm_needed,
            )
            plan.add_action(action)

        return plan

    def _extract_params_deterministic(self, text: str, action_type: ActionType) -> dict:
        """Extrai parâmetros de forma determinística."""
        params: dict = {}
        text_lower = text.lower()

        if action_type in (ActionType.OPEN_APP, ActionType.UNKNOWN):
            # Tentar identificar app
            for app_key, app_name in _KNOWN_APPS.items():
                if app_key in text_lower:
                    params["app"] = app_name
                    params["command"] = f'start "" "{app_name}"'
                    break

        elif action_type == ActionType.SEARCH_WEB:
            m = re.search(r"(?:pesquisa|pesquisar|search|procura)\s+(.+)", text_lower)
            if m:
                params["query"] = m.group(1).strip()
                params["command"] = f"start https://www.google.com/search?q={params['query']}"

        elif action_type == ActionType.OPEN_URL:
            m = re.search(r"(?:entra no|acessa|go to)\s+(.+)", text_lower)
            if m:
                site = m.group(1).strip()
                if "." not in site:
                    site = f"www.{site}.com"
                params["url"] = site
                params["command"] = f"start https://{site}"

        elif action_type == ActionType.SHUTDOWN:
            params["command"] = "shutdown /s /t 0"

        elif action_type == ActionType.RESTART:
            params["command"] = "shutdown /r /t 0"

        elif action_type == ActionType.LOCK:
            params["command"] = "rundll32.exe user32.dll,LockWorkStation"

        elif action_type == ActionType.SLEEP:
            params["command"] = "rundll32.exe powrprof.dll,SetSuspendState 0,1,0"

        elif action_type == ActionType.SYSTEM_STATUS:
            params["command"] = "systeminfo"

        elif action_type == ActionType.READ_FILE:
            m = re.search(r"(?:le|ler|read)\s+(?:o\s+)?(?:arquivo\s+)?(.+)", text_lower)
            if m:
                params["path"] = m.group(1).strip()

        elif action_type == ActionType.WRITE_FILE:
            m = re.search(r"(?:escreve|escrever|write|salva|salvar)\s+(.+)", text_lower)
            if m:
                params["path"] = m.group(1).strip()

        return params

    def _validate_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Valida o plano e corrige problemas."""
        if not plan.actions:
            plan.status = PlanStatus.FAILED
            plan.errors.append("Nenhuma ação identificada")
            return plan

        # Verificar ações unknown
        for action in plan.actions:
            if action.action_type == ActionType.UNKNOWN:
                action.status = ActionStatus.SKIPPED
                plan.errors.append(f"Ação não reconhecida: {action.description}")

        # Verificar dependências circulares
        visited: set[str] = set()
        path: set[str] = set()

        def has_cycle(action_id: str) -> bool:
            if action_id in path:
                return True
            if action_id in visited:
                return False
            visited.add(action_id)
            path.add(action_id)
            action = plan.get_action(action_id)
            if action:
                for dep_id in action.depends_on:
                    if has_cycle(dep_id):
                        return True
            path.discard(action_id)
            return False

        for action in plan.actions:
            if has_cycle(action.id):
                plan.errors.append(f"Dependência circular detectada em {action.id}")
                action.depends_on = []

        # Marcar ações sem dependências como prontas
        for action in plan.actions:
            if not action.depends_on and action.status == ActionStatus.PENDING:
                action.status = ActionStatus.READY

        # Verificar se alguma ação precisa de confirmação
        plan.needs_confirmation = any(
            a.confirmation_required for a in plan.actions
        )

        plan.status = PlanStatus.VALIDATED
        return plan

    def _generate_summary(self, plan: ExecutionPlan) -> str:
        """Gera resumo legível do plano."""
        if not plan.actions:
            return "Nenhuma ação identificada."

        lines: list[str] = []
        order = plan.get_sequential_order()

        temporal_actions = [a for a in order if a.temporal and a.temporal.time_str and not a.temporal.is_relative]
        immediate_actions = [a for a in order if not a.temporal or a.temporal.is_relative]
        conditional_actions = [a for a in order if a.trigger]

        idx = 1
        if temporal_actions:
            for a in temporal_actions:
                lines.append(f"{idx}. {a.description} ({a.temporal.time_str})")
                idx += 1

        if conditional_actions:
            for a in conditional_actions:
                event = a.trigger.trigger_event if a.trigger else ""
                event_desc = {
                    "system_start": "quando o PC ligar",
                    "application_ready": "quando o app abrir",
                    "task_complete": "quando terminar",
                }.get(event, event)
                lines.append(f"{idx}. {a.description} ({event_desc})")
                idx += 1

        if immediate_actions:
            for a in immediate_actions:
                if a not in temporal_actions and a not in conditional_actions:
                    lines.append(f"{idx}. {a.description}")
                    idx += 1

        return "\n".join(lines)
