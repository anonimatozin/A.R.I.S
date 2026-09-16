"""Analisador de dependências entre ações.

Identifica relações de dependência, condicional, paralelismo
e sequência entre ações de um plano. Conecta ações que dependem
umas das outras e identifica ações que podem rodar em paralelo.
"""

from __future__ import annotations

import re
from .models import (
    ActionDependency,
    ActionType,
    PlanAction,
    RelationType,
)


# Mapeamento de ação -> tipo de ação
_ACTION_TYPE_KEYWORDS: dict[str, list[str]] = {
    "shutdown": ["desliga", "desligar", "shutdown", "off", "desligamento"],
    "restart": ["reinicia", "reiniciar", "restart", "reboot"],
    "lock": ["trava", "travar", "lock"],
    "sleep": ["dorme", "dormir", "sleep", "suspender"],
    "wake": ["liga", "ligar", "wake", "wol", "desperta"],
    "schedule_shutdown": ["agenda desligamento", "programa desligamento", "schedule shutdown"],
    "schedulewake": ["agenda ligamento", "programa ligamento", "schedule wake"],
    "cancel_schedule": ["cancela", "cancelar", "cancel"],
    "open_app": ["abre", "abrir", "open", "inicia", "iniciar", "executa"],
    "open_url": ["entra no", "acessa", "access", "vai para", "go to"],
    "open_browser": ["abre o navegador", "abrir navegador", "open browser"],
    "search_web": ["pesquisa", "pesquisar", "search", "procura", "procurar"],
    "read_file": ["le", "ler", "read"],
    "write_file": ["escreve", "escrever", "write", "salva", "salvar"],
    "run_command": ["executa", "executar", "roda", "rodar", "run"],
    "reminder": ["lembra", "lembrar", "reminder", "avisa"],
    "email": ["email", "e-mail", "gmail", "manda email"],
    "system_status": ["status", "informações", "informacoes"],
}


def classify_action_type(text: str) -> ActionType:
    """Classifica o tipo de ação baseado no texto."""
    text_lower = text.lower().strip()

    # Verificar em ordem de prioridade (mais específico primeiro)
    type_checks = [
        (ActionType.SCHEDULE_SHUTDOWN, ["desliga", "desligar", "shutdown"], ["as ", "às", "hora", "horas", "minutos", "daqui"]),
        (ActionType.SCHEDULE_WAKE, ["liga", "ligar", "wake"], ["as ", "às", "hora", "horas", "minutos", "daqui"]),
        (ActionType.CANCEL_SCHEDULE, ["cancela", "cancelar"], ["desligamento", "ligamento", "agendamento"]),
        (ActionType.SHUTDOWN, ["desliga", "desligar", "shutdown"], []),
        (ActionType.RESTART, ["reinicia", "reiniciar", "restart"], []),
        (ActionType.LOCK, ["trava", "travar", "lock"], []),
        (ActionType.SLEEP, ["dorme", "sleep", "suspender"], []),
        (ActionType.WAKE, ["liga", "ligar", "wake", "wol"], []),
        (ActionType.OPEN_BROWSER, ["navegador", "browser"], []),
        (ActionType.SEARCH_WEB, ["pesquisa", "pesquisar", "search", "procura"], []),
        (ActionType.OPEN_URL, ["youtube", "github", "site", "url", "http"], []),
        (ActionType.OPEN_APP, ["abre", "abrir", "open"], []),
        (ActionType.READ_FILE, ["le o arquivo", "ler arquivo"], []),
        (ActionType.WRITE_FILE, ["escreve", "salva o arquivo"], []),
        (ActionType.RUN_COMMAND, ["executa comando", "roda"], []),
        (ActionType.REMINDER_CREATE, ["lembra", "avisa"], []),
        (ActionType.EMAIL_LIST, ["lista email", "mostra email"], []),
        (ActionType.SYSTEM_STATUS, ["status do pc", "status do computador"], []),
    ]

    for action_type, must_have, nice_to_have in type_checks:
        has_must = any(kw in text_lower for kw in must_have)
        if not has_must:
            continue
        if nice_to_have:
            if any(kw in text_lower for kw in nice_to_have):
                return action_type
        else:
            return action_type

    # Se o texto é apenas o nome de um app conhecido, tratar como open_app
    known_apps_lower = {k.lower() for k in [
        "spotify", "discord", "vscode", "vs code", "chrome", "firefox",
        "edge", "opera", "brave", "terminal", "cmd", "powershell",
        "notepad", "word", "excel", "blender", "photoshop", "steam",
        "youtube", "github", "slack", "teams", "zoom", "telegram",
    ]}
    if text_lower in known_apps_lower:
        return ActionType.OPEN_APP

    return ActionType.UNKNOWN


def detect_trigger_event(text: str) -> str:
    """Detecta evento de gatilho em texto condicional.

    Exemplos:
    - "quando ligar" -> "system_start"
    - "quando abrir" -> "application_ready"
    - "quando terminar" -> "task_complete"
    """
    text_lower = text.lower()

    trigger_map = [
        (r"quando\s+(?:o\s+pc|o\s+computador)?\s*ligar", "system_start"),
        (r"quando\s+estiver\s+ligado", "system_start"),
        (r"assim\s+que\s+ligar", "system_start"),
        (r"ao\s+ligar", "system_start"),
        (r"quando\s+abrir", "application_ready"),
        (r"quando\s+estiver\s+pronto", "application_ready"),
        (r"quando\s+terminar", "task_complete"),
        (r"quando\s+voltar", "system_start"),
        (r"quando\s+chegar", "system_start"),
    ]

    for pattern, event in trigger_map:
        if re.search(pattern, text_lower):
            return event

    return ""


def analyze_dependencies(actions: list[PlanAction]) -> list[ActionDependency]:
    """Analisa e cria dependências entre ações.

    Regras:
    1. Ações com trigger condicional dependem da ação que causa o trigger
    2. Ações temporais são sequenciais por tempo
    3. Pesquisa depende de navegador ter aberto
    4. Ações explícitas de sequência ("depois") são sequenciais
    """
    import re

    dependencies: list[ActionDependency] = []

    # Mapear ações por tipo
    shutdown_actions = [a for a in actions if a.action_type in (ActionType.SHUTDOWN, ActionType.SCHEDULE_SHUTDOWN)]
    wake_actions = [a for a in actions if a.action_type in (ActionType.WAKE, ActionType.SCHEDULE_WAKE)]
    open_actions = [a for a in actions if a.action_type == ActionType.OPEN_APP]
    browser_actions = [a for a in actions if a.action_type == ActionType.OPEN_BROWSER]
    search_actions = [a for a in actions if a.action_type == ActionType.SEARCH_WEB]
    url_actions = [a for a in actions if a.action_type == ActionType.OPEN_URL]

    # 1. Ações condicionais dependem de trigger
    for action in actions:
        if action.trigger and action.trigger.trigger_event:
            trigger_event = action.trigger.trigger_event
            if trigger_event == "system_start":
                # Dependem de desligamento/ligamento
                for wake in wake_actions:
                    if wake.id != action.id:
                        dependencies.append(
                            ActionDependency(
                                source_id=wake.id,
                                target_id=action.id,
                                relation=RelationType.CONDITIONAL,
                                description="Aguarda ligação do sistema",
                            )
                        )
                        if action.id not in action.depends_on:
                            action.depends_on.append(wake.id)
                # Ou restart
                for restart in [a for a in actions if a.action_type == ActionType.RESTART]:
                    if restart.id != action.id:
                        dependencies.append(
                            ActionDependency(
                                source_id=restart.id,
                                target_id=action.id,
                                relation=RelationType.CONDITIONAL,
                                description="Aguarda reinicialização",
                            )
                        )
                        if action.id not in action.depends_on:
                            action.depends_on.append(restart.id)

            elif trigger_event == "application_ready":
                # Depende da ação de abrir o app correspondente
                for open_act in open_actions:
                    if open_act.id != action.id:
                        dependencies.append(
                            ActionDependency(
                                source_id=open_act.id,
                                target_id=action.id,
                                relation=RelationType.CONDITIONAL,
                                description="Aguarda app abrir",
                            )
                        )
                        if action.id not in action.depends_on:
                            action.depends_on.append(open_act.id)

    # 2. Pesquisa depende de navegador
    for search in search_actions:
        for browser in browser_actions:
            if browser.id != search.id:
                dependencies.append(
                    ActionDependency(
                        source_id=browser.id,
                        target_id=search.id,
                        relation=RelationType.DEPENDENCY,
                        description="Navegador precisa abrir antes da pesquisa",
                    )
                )
                if search.id not in search.depends_on:
                    search.depends_on.append(browser.id)

    # 3. URL depende de navegador
    for url_act in url_actions:
        for browser in browser_actions:
            if browser.id != url_act.id:
                dependencies.append(
                    ActionDependency(
                        source_id=browser.id,
                        target_id=url_act.id,
                        relation=RelationType.DEPENDENCY,
                        description="Navegador precisa abrir antes de acessar URL",
                    )
                )
                if url_act.id not in url_act.depends_on:
                    url_act.depends_on.append(browser.id)

    return dependencies


def detect_relation_type(text: str) -> RelationType:
    """Detecta o tipo de relação a partir do texto e conectivos."""
    text_lower = text.lower()

    # Paralelo: lista de itens
    items = re.split(r",\s*|\s+e\s+", text_lower)
    if len(items) >= 2:
        return RelationType.PARALLEL

    # Temporal: tem horário
    if re.search(r"(?:às|as|@)\s*\d", text_lower):
        return RelationType.TEMPORAL

    # Condicional: tem gatilho
    if detect_trigger_event(text_lower):
        return RelationType.CONDITIONAL

    return RelationType.SEQUENTIAL
