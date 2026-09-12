"""Intent Handlers do A.R.I.S.

Todos os handlers de intenção registrados via @registry.register_intent().
Cada handler recebe: action, params, **ctx (com instâncias dos módulos).

Para adicionar um novo handler:
    from core.commands import registry

    @registry.register_intent("meu_modulo", description="O que faz")
    def handle_meu_modulo(action: str, params: dict, **ctx) -> str:
        modulo = ctx["meu_modulo"]
        return modulo.faz_algo(params.get("arg"))
"""

from utils.terminal import Terminal, ArisUI
from core.commands import registry


# ── Weather ─────────────────────────────────────────────────

@registry.register_intent("weather", description="Previsão do tempo e clima")
def handle_weather(action: str, params: dict, **ctx) -> str:
    city = params.get("city", "São Paulo")
    report = ctx["weather"].format_report(city)
    lines = report.split("\n")
    print()
    for line in lines:
        print(f"  {line}")
    print()
    return ""


# ── Web Search ──────────────────────────────────────────────

@registry.register_intent("websearch", description="Pesquisa na web")
def handle_websearch(action: str, params: dict, **ctx) -> str:
    query = params.get("query", "")
    if query:
        result = ctx["search"].search_and_summarize(query)
        lines = result.split("\n")
        print()
        for line in lines:
            print(f"  {line}")
        print()
    return ""


# ── System Analysis ─────────────────────────────────────────

@registry.register_intent("sys", description="Análise do sistema (CPU, RAM, disco)")
def handle_sys(action: str, params: dict, **ctx) -> str:
    analyzer = ctx["analyzer"]
    report = analyzer.get_full_report()

    Terminal.print_separator()
    Terminal.print_centered("ANÁLISE DO SISTEMA")
    Terminal.print_separator()

    cpu = report["cpu"]
    print(f"  CPU: {cpu['cores_physical']}C/{cpu['cores_logical']}T @ {cpu['frequency_mhz']:.0f}MHz")
    print(f"       Uso: {Terminal.colorize(str(cpu['usage_percent']) + '%', Terminal.CYAN)}")

    mem = report["memory"]
    print(f"  RAM: {mem['used_gb']:.1f}GB / {mem['total_gb']:.1f}GB ({mem['percent']}%)")

    disk = report["disk"]
    print(f"  Disco: {disk['used_gb']:.1f}GB / {disk['total_gb']:.1f}GB ({disk['percent']}%)")

    net = report["network"]
    print(f"  Rede: ↓{net['bytes_recv_gb']:.2f}GB ↑{net['bytes_sent_gb']:.2f}GB")

    bat = report["battery"]
    if bat["percent"] is not None:
        print(f"  Bateria: {bat['percent']:.0f}% {'(carregando)' if bat['plugged'] else ''}")

    print(f"  Processos: {report['processes']}")
    print()

    alerts = analyzer.diagnose()
    for alert in alerts:
        color = Terminal.RED if "CRÍTICO" in alert else Terminal.YELLOW if "AVISO" in alert else Terminal.GREEN
        print(f"  {Terminal.colorize(alert, color)}")

    Terminal.print_separator()
    return ""


# ── Desktop Tools ───────────────────────────────────────────

@registry.register_intent("desktop", description="Controle do desktop (mouse, teclado, mídia, janelas)")
def handle_desktop(action: str, params: dict, **ctx) -> str:
    result = ctx["desktop"].execute_action(action, params)
    print(f"  {result}")
    return ""


# ── Scheduler ───────────────────────────────────────────────

@registry.register_intent("scheduler", description="Agendamentos e lembretes")
def handle_scheduler(action: str, params: dict, **ctx) -> str:
    scheduler = ctx["scheduler"]

    if action == "add":
        title = params.get("title", "")
        when = params.get("when", "")
        if title and when:
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(when)
                task = scheduler.add_reminder(title, dt)
                print(f"  Lembrete criado: {task.id} — {task.title}")
            except ValueError:
                print("  Formato de data inválido. Use: YYYY-MM-DD HH:MM")

    elif action == "list":
        tasks = scheduler.list_tasks()
        print(scheduler.format_task_list(tasks))

    elif action == "cancel":
        task_id = params.get("task_id", "")
        result = scheduler.cancel_task(task_id)
        print(f"  {result}")

    elif action == "pomodoro":
        minutes = params.get("minutes", 25)
        result = scheduler.start_pomodoro(minutes)
        print(f"  {result}")

    return ""


# ── Notifications ───────────────────────────────────────────

@registry.register_intent("notify", description="Notificações Windows")
def handle_notify(action: str, params: dict, **ctx) -> str:
    title = params.get("title", "A.R.I.S.")
    message = params.get("message", "")
    if message:
        result = ctx["notifications"].notify(title, message)
        print(f"  {result}")
    return ""


# ── Context Detector ────────────────────────────────────────

@registry.register_intent("context", description="Detectar contexto/atividade atual")
def handle_context(action: str, params: dict, **ctx) -> str:
    context_text = ctx["context"].format_context()
    print()
    for line in context_text.split("\n"):
        print(f"  {line}")
    print()
    return ""


# ── Safety ──────────────────────────────────────────────────

@registry.register_intent("safety", description="Segurança e permissões")
def handle_safety(action: str, params: dict, **ctx) -> str:
    report = ctx["safety"].get_safety_report()
    print()
    for line in report.split("\n"):
        print(f"  {line}")
    print()
    return ""


# ── Entertainment ───────────────────────────────────────────

@registry.register_intent("entertainment", description="Entretenimento (piadas, curiosidades, jogos)")
def handle_entertainment(action: str, params: dict, **ctx) -> str:
    ent = ctx["entertainment"]

    if action == "joke":
        print(f"  {ent.get_random_joke()}")
    elif action == "curiosity":
        print(f"  {ent.get_random_curiosity()}")
    elif action == "quote":
        print(f"  {ent.get_random_quote()}")
    elif action == "dice":
        sides = params.get("sides", 6)
        count = params.get("count", 1)
        print(f"  {ent.roll_dice(sides, count)}")
    elif action == "coin":
        print(f"  {ent.coin_flip()}")
    elif action == "8ball":
        question = params.get("question", "")
        print(f"  {ent.eight_ball(question)}")
    elif action == "card":
        print(f"  {ent.get_daily_card()}")
    elif action == "game":
        print(f"  {ent.guess_number_game()}")

    return ""


# ── Turbo Mode ──────────────────────────────────────────────

@registry.register_intent("turbo", description="Análise profunda de arquivos e código")
def handle_turbo(action: str, params: dict, **ctx) -> str:
    turbo = ctx["turbo"]

    if action == "activate":
        result = turbo.activate()
        print(f"  {result}")
    elif action == "deactivate":
        result = turbo.deactivate()
        print(f"  {result}")
    elif action == "analyze_file":
        filepath = params.get("path", "")
        if filepath:
            result = turbo.analyze_file(filepath)
            print(f"  {result}")
    elif action == "analyze_dir":
        dirpath = params.get("path", ".")
        result = turbo.analyze_directory(dirpath)
        print(f"  {result}")
    elif action == "review":
        filepath = params.get("path", "")
        if filepath:
            result = turbo.code_review(filepath)
            print(f"  {result}")

    return ""


# ── Knowledge Graph ─────────────────────────────────────────

@registry.register_intent("knowledge", description="Grafo de conhecimento (entidades, fatos, relacionamentos)")
def handle_knowledge(action: str, params: dict, **ctx) -> str:
    kg = ctx["knowledge"]

    if action == "stats":
        print(f"  {kg.format_graph_summary()}")

    elif action == "add_entity":
        name = params.get("name", "")
        etype = params.get("type", "conceito")
        if name:
            entity = kg.add_entity(name, etype)
            print(f"  Entidade criada: {entity.name} ({entity.id})")

    elif action == "add_fact":
        entity_name = params.get("entity", "")
        content = params.get("content", "")
        if entity_name and content:
            fact = kg.add_fact(entity_name, content)
            if fact:
                print(f"  Fato adicionado: {fact.id}")

    elif action == "search":
        query = params.get("query", "")
        results = kg.search_entities(query)
        for entity in results:
            print(kg.format_entity(entity))

    elif action == "neighbors":
        name = params.get("name", "")
        neighbors = kg.get_neighbors(name)
        for n in neighbors:
            print(f"  → {n['relation']}: {n['target']}")

    return ""


# ── Desktop Awareness ───────────────────────────────────────

@registry.register_intent("awareness", description="Desktop awareness (captura de tela, OCR, monitoramento)")
def handle_awareness(action: str, params: dict, **ctx) -> str:
    aw = ctx["awareness"]

    if action == "status":
        print(f"  {aw.format_status()}")

    elif action == "capture":
        path = aw.capture_screenshot()
        if path:
            print(f"  Screenshot: {path}")

    elif action == "ocr":
        text = aw.extract_text_from_screen()
        print(f"  Texto na tela:\n{text[:500]}")

    elif action == "search":
        query = params.get("query", "")
        result = aw.search_on_screen(query)
        if result["found"]:
            print(f"  ✅ Encontrado: {result['context']}")
        else:
            print(f"  ❌ Não encontrado na tela")

    elif action == "monitor":
        aw.monitor_screen(interval=params.get("interval", 30))
        print("  Monitoramento iniciado")

    return ""


# ── Auto Redaction ──────────────────────────────────────────

@registry.register_intent("redact", description="Auto-redação de dados sensíveis")
def handle_redact(action: str, params: dict, **ctx) -> str:
    redact = ctx["redaction"]

    if action == "check":
        text = params.get("text", "")
        findings = redact.detect(text)
        if findings:
            print(f"  ⚠️ Dados sensíveis encontrados: {len(findings)}")
            for f in findings:
                print(f"    {f['type']}: {f['value']}")
        else:
            print("  ✅ Nenhum dado sensível encontrado")

    elif action == "redact":
        text = params.get("text", "")
        result = redact.redact(text)
        print(f"  {result}")

    elif action == "report":
        print(f"  {redact.format_report()}")

    return ""


# ── Morning Digest ──────────────────────────────────────────

@registry.register_intent("digest", description="Briefing diário automatizado")
def handle_digest(action: str, params: dict, **ctx) -> str:
    digest = ctx["digest"]

    if action == "generate":
        weather_data = ctx.get("weather_report", "")
        tasks_data = ctx.get("tasks_report", "")
        system_data = ctx.get("system_report", "")
        digest_text = digest.generate(
            weather_data=weather_data,
            tasks_data=tasks_data,
            system_data=system_data,
        )
        print(digest_text)

    elif action == "config":
        key = params.get("key", "")
        value = params.get("value", True)
        result = digest.set_config(key, value)
        print(f"  {result}")

    elif action == "history":
        history = digest.get_history()
        for entry in history:
            print(f"  {entry['date'][:10]}: {entry['preview'][:80]}...")

    return ""


# ── Browser Automation ──────────────────────────────────────

@registry.register_intent("browser", description="Automação de navegador web")
def handle_browser(action: str, params: dict, **ctx) -> str:
    browser = ctx["browser"]

    if action == "status":
        print(f"  {browser.format_status()}")

    elif action == "start":
        result = browser.navigate_sync("about:blank")
        print(f"  {result}")

    elif action == "navigate":
        url = params.get("url", "")
        if url:
            result = browser.navigate_sync(url)
            print(f"  {result}")

    elif action == "content":
        text = browser.get_content_sync()
        print(f"  {text[:1000]}")

    elif action == "search":
        query = params.get("query", "")
        if query:
            result = browser.search_sync(query)
            print(f"  {result}")

    elif action == "screenshot":
        result = browser.screenshot_sync()
        print(f"  {result}")

    return ""


# ── Multi-Agent ─────────────────────────────────────────────

@registry.register_intent("agents", description="Multi-agente e delegação de tarefas")
def handle_agents(action: str, params: dict, **ctx) -> str:
    agents = ctx["agents"]

    if action == "status":
        print(f"  {agents.format_status()}")

    elif action == "list":
        agent_list = agents.list_agents()
        for a in agent_list:
            print(f"  🤖 {a['name']} ({a['type']}) — {a['status']} — {a['tasks_completed']} tarefas")

    elif action == "delegate":
        desc = params.get("description", "")
        if desc:
            task = agents.delegate_task(desc)
            if task:
                print(f"  Tarefa delegada: {task.id}")
            else:
                print("  Nenhum agente disponível")

    elif action == "tasks":
        tasks = agents.list_tasks()
        for t in tasks:
            print(f"  [{t['id']}] {t['description'][:50]} — {t['status']}")

    return ""


# ── Skills System ───────────────────────────────────────────

@registry.register_intent("skills", description="Sistema de skills e habilidades")
def handle_skills(action: str, params: dict, **ctx) -> str:
    skills = ctx["skills"]

    if action == "list":
        print(skills.format_skills())

    elif action == "search":
        query = params.get("query", "")
        results = skills.search_skills(query)
        for skill in results:
            print(f"  🧩 {skill.name} — {skill.description}")

    elif action == "enable":
        name = params.get("name", "")
        result = skills.enable_skill(name)
        print(f"  {result}")

    elif action == "disable":
        name = params.get("name", "")
        result = skills.disable_skill(name)
        print(f"  {result}")

    return ""


# ── Dictation Mode ──────────────────────────────────────────

@registry.register_intent("dictation", description="Modo dictação (falar e digitar)")
def handle_dictation(action: str, params: dict, **ctx) -> str:
    dictation = ctx["dictation"]

    if action == "status":
        print(f"  {dictation.format_status()}")

    elif action == "start":
        result = dictation.start_dictation()
        print(f"  {result}")

    elif action == "stop":
        result = dictation.stop_dictation()
        print(f"  {result}")

    elif action == "listen":
        text = dictation.listen_once()
        if text:
            print(f"  🎤 {text}")
        else:
            print("  Nenhuma fala detectada")

    elif action == "key":
        key = params.get("key", "capslock")
        result = dictation.set_hold_key(key)
        print(f"  {result}")

    elif action == "language":
        lang = params.get("lang", "pt-BR")
        result = dictation.set_language(lang)
        print(f"  {result}")

    return ""


# ── Memory (remember) ──────────────────────────────────────

@registry.register_intent("remember", description="Salvar informação na memória")
def handle_remember(action: str, params: dict, **ctx) -> str:
    from core.memory_models import MemoryCategory

    text = params.get("text", "")
    if text:
        memory = ctx["memory"]
        importance = 5
        category = MemoryCategory.KNOWLEDGE
        tags = []
        text_lower = text.lower()

        if any(w in text_lower for w in ["meu nome", "me chamo", "sou o", "pode me chamar"]):
            category = MemoryCategory.PROFILE
            importance = 10
            tags = ["perfil", "pessoal"]
        elif any(w in text_lower for w in ["projeto", "código", "script"]):
            category = MemoryCategory.PROJECTS
            importance = 8
            tags.append("projeto")
        elif any(w in text_lower for w in ["dispositivo", "esp32", "arduino"]):
            category = MemoryCategory.DEVICES
            importance = 8
            tags.append("dispositivo")
        elif any(w in text_lower for w in ["config", "configuração", "preferência"]):
            category = MemoryCategory.CONFIG
            importance = 10
            tags.append("configuração")

        entry = memory.save(
            title=text[:50],
            content=text,
            category=category,
            importance=importance,
            tags=tags,
        )
        print(f"  Memória salva: {Terminal.colorize(entry.id, Terminal.CYAN)}")

    return ""


# ── Memory Search ───────────────────────────────────────────

@registry.register_intent("search", description="Buscar memória salva")
def handle_search_memory(action: str, params: dict, **ctx) -> str:
    query = params.get("query", "")
    if query:
        memory = ctx["memory"]
        results = memory.search(query=query)
        if not results:
            print("  Nenhuma memória encontrada.")
        else:
            Terminal.print_separator()
            for entry in results:
                imp_color = Terminal.GREEN if entry.importance >= 7 else Terminal.YELLOW
                print(f"  [{Terminal.colorize(entry.id, Terminal.CYAN)}] {entry.title}")
                print(f"    {entry.category.value} | Imp: {Terminal.colorize(str(entry.importance), imp_color)}")
            Terminal.print_separator()

    return ""


# ── Config ──────────────────────────────────────────────────

@registry.register_intent("config", description="Configurações do sistema")
def handle_config(action: str, params: dict, **ctx) -> str:
    settings = ctx.get("settings")
    if settings:
        print(f"  Diretório base: {settings.BASE_DIR}")
        print(f"  Modelo de chat: {settings.CHAT_MODEL}")
        print(f"  Safety level: {settings.SAFETY_LEVEL}")
        print(f"  Voz: rate={settings.VOICE_RATE}, volume={settings.VOICE_VOLUME}")
    else:
        print("  Configurações indisponíveis.")
    return ""


# ── Voice Toggle ────────────────────────────────────────────

@registry.register_intent("speak", description="Ativar/desativar voz")
def handle_speak(action: str, params: dict, **ctx) -> str:
    voice = ctx.get("voice")
    if voice:
        if voice.enabled:
            voice.enabled = False
            print("  Voz desativada.")
        else:
            voice.enabled = True
            print("  Voz ativada.")
    return ""


# ── Safety Level Mapping ────────────────────────────────────
# 1=SAFE, 2=CAUTION, 3=DANGER, 4=CRITICAL

_SAFETY_LEVELS = {
    # SAFE (1) — leitura, informação, sem efeitos colaterais
    "weather": 1,
    "websearch": 1,
    "sys": 1,
    "search": 1,
    "remember": 1,
    "config": 1,
    "speak": 1,
    "context": 1,
    "knowledge": 1,
    "safety": 1,
    "digest": 1,
    "calc": 1,

    # CAUTION (2) — ações que afetam o estado mas são reversíveis
    "desktop": 2,
    "scheduler": 2,
    "notify": 2,
    "entertainment": 2,
    "turbo": 2,
    "awareness": 2,
    "redact": 2,
    "skills": 2,
    "dictation": 2,
    "browser": 2,
    "agents": 2,

    # DANGER (3) — ações destrutivas ou difíceis de reverter
    # (desktop fechar/kill já tratado internamente)

    # CRITICAL (4) — desligar, formatar, etc.
    "exit": 4,
}

for _mod, _level in _SAFETY_LEVELS.items():
    registry.register_safety_level(_mod, _level)
