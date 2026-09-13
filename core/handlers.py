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

from core.commands import registry
from utils.terminal import Terminal

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
    if "Indisponível" in report or "Nenhuma fonte" in report:
        return "Não consegui obter a previsão do tempo no momento."
    first = next((ln.strip() for ln in lines if ln.strip()), "previsão indisponível")
    return f"Previsão do tempo: {first}"


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
        if "Nenhum resultado" in result:
            return "Não encontrei resultados para essa busca."
        first = next((ln.strip() for ln in lines if ln.strip()), "resultado")
        return f"Sobre a busca: {first}"
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

    major = [a for a in alerts if "AVISO" in a or "CRÍTICO" in a]
    if any("CRÍTICO" in a for a in alerts):
        status = "atenção, existem problemas críticos no sistema"
    elif major:
        status = "todos os sistemas aparentam estar funcionando, com alguns avisos"
    else:
        status = "todos os sistemas operacionais normais"
    return (f"Análise do sistema: CPU em {cpu['usage_percent']} por cento, "
            f"memória em {mem['percent']}, disco em {disk['percent']}. {status}.")


# ── Desktop Tools ───────────────────────────────────────────

@registry.register_intent("desktop", description="Controle do desktop (mouse, teclado, mídia, janelas)")
def handle_desktop(action: str, params: dict, **ctx) -> str:
    result = ctx["desktop"].execute_action(action, params)
    print(f"  {result}")
    return result


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
                return f"Lembrete criado para {title}."
            except ValueError:
                print("  Formato de data inválido. Use: YYYY-MM-DD HH:MM")
                return "O formato da data está inválido."

    elif action == "list":
        tasks = scheduler.list_tasks()
        print(scheduler.format_task_list(tasks))
        return f"Você tem {len(tasks)} dependecias pendentes." if tasks else "Nenhuma dependencia pendente."

    elif action == "cancel":
        task_id = params.get("task_id", "")
        result = scheduler.cancel_task(task_id)
        print(f"  {result}")
        return result

    elif action == "pomodoro":
        minutes = params.get("minutes", 25)
        result = scheduler.start_pomodoro(minutes)
        print(f"  {result}")
        return result

    return ""


# ── Notifications ───────────────────────────────────────────

@registry.register_intent("notify", description="Notificações Windows")
def handle_notify(action: str, params: dict, **ctx) -> str:
    title = params.get("title", "A.R.I.S.")
    message = params.get("message", "")
    if message:
        result = ctx["notifications"].notify(title, message)
        print(f"  {result}")
        return result
    return "Notificação sem conteúdo."


# ── Context Detector ────────────────────────────────────────

@registry.register_intent("context", description="Detectar contexto/atividade atual")
def handle_context(action: str, params: dict, **ctx) -> str:
    context_text = ctx["context"].format_context()
    print()
    for line in context_text.split("\n"):
        print(f"  {line}")
    print()
    first = next((ln.strip() for ln in context_text.split("\n") if ln.strip()), "contexto indisponível")
    return f"Contexto atual: {first}"


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
        text = ent.get_random_joke()
        print(f"  {text}")
        return text
    elif action == "curiosity":
        text = ent.get_random_curiosity()
        print(f"  {text}")
        return text
    elif action == "quote":
        text = ent.get_random_quote()
        print(f"  {text}")
        return text
    elif action == "dice":
        sides = params.get("sides", 6)
        count = params.get("count", 1)
        text = ent.roll_dice(sides, count)
        print(f"  {text}")
        return f"Você tirou: {text}"
    elif action == "coin":
        text = ent.coin_flip()
        print(f"  {text}")
        return text
    elif action == "8ball":
        question = params.get("question", "")
        text = ent.eight_ball(question)
        print(f"  {text}")
        return text
    elif action == "card":
        text = ent.get_daily_card()
        print(f"  {text}")
        return text
    elif action == "game":
        text = ent.guess_number_game()
        print(f"  {text}")
        return text

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
        status = aw.format_status()
        print(f"  {status}")
        return "Tela monitorada com awareness."

    elif action in ("analyze", "describe"):
        info = aw.describe_screen()
        win = info.get("window") or {}
        title = win.get("title") or "desconhecida"
        if info.get("screenshot"):
            print(f"  Screenshot: {info['screenshot']}")
        if info.get("ocr_available") and info.get("text"):
            lines = [ln.strip() for ln in info["text"].splitlines() if ln.strip()][:12]
            print("  Texto na tela:")
            for ln in lines:
                print(f"    • {ln[:90]}")
            prev = " ".join(lines)
            print(f"  Janela ativa: {title}")
            return (f"Analisei a tela. Janela ativa: {title}. "
                    f"Texto visível: {prev[:180]}.")
        print(f"  Janela ativa: {title}")
        return (f"Sua janela ativa é {title}. O OCR não está ativo neste sistema; "
                "posso capturar a imagem se você desejar.")

    elif action == "capture":
        path = aw.capture_screenshot()
        if path:
            print(f"  Screenshot: {path}")
            return f"Screenshot salva: {path}"
        return "Não foi possível capturar a tela."

    elif action == "ocr":
        text = aw.extract_text_from_screen()
        print(f"  Texto na tela:\n{text[:500]}")
        if text.startswith("Erro") or "não disponível" in text:
            return text[:160]
        return "Texto da tela extraído (veja o detalhe acima)."

    elif action == "search":
        query = params.get("query", "")
        result = aw.search_on_screen(query)
        if result["found"]:
            print(f"  ✅ Encontrado: {result['context']}")
            return f"Encontrei '{query}' na tela."
        print("  ❌ Não encontrado na tela")
        return f"Não encontrei '{query}' na tela."

    elif action == "monitor":
        aw.monitor_screen(interval=params.get("interval", 30))
        print("  Monitoramento iniciado")
        return "Monitoramento da tela iniciado."

    return ""


# ── Vision Engine (visão computacional) ────────────────────

@registry.register_intent("vision", description="Vision Engine (captura, OCR, VLM, análise de tela)")
def handle_vision(action: str, params: dict, **ctx) -> str:
    vision = ctx["vision"]

    if action == "status":
        print(f" {vision.format_status()}")
        return "Sistema de visão computacional ativo (veja o detalhe acima)."

    elif action == "camera":
        if vision is None:
            return "Sistema de visão não disponível no momento."
        status = vision.camera_status()
        print(f" {status}")
        return status

    elif action == "read" or action == "ocr":
        if vision is None:
            return "Sistema de visão não disponível no momento."
        ocr = vision.read_screen()
        if not ocr.available:
            message = ocr.note or "leitura de texto indisponível"
            print(f" {message}")
            return f"Não consegui ler a tela agora ({message})."
        lines = [ln.strip() for ln in ocr.lines if ln.strip()]
        for ln in lines[:15]:
            print(f"   • {ln[:90]}")
        return f"Texto da tela extraído ({len(' '.join(ocr.lines))} caracteres)."

    elif action == "errors":
        if vision is None:
            return "Sistema de visão não disponível no momento."
        errors = vision.detect_errors()
        if errors:
            for term in errors:
                print(f"   • possível erro: {term}")
            return "Possíveis erros detectados na tela: " + ", ".join(errors) + "."
        print("  Nenhum termo de erro visível na tela.")
        return "Não detectei erros visíveis na tela."

    elif action == "find":
        if vision is None:
            return "Sistema de visão não disponível no momento."
        query = params.get("query", "")
        if not query:
            return "Para procurar texto na tela, diga 'procure por <texto>'."
        result = vision.find_on_screen(query)
        if result["found"]:
            pos = result["position"]
            print(f"  Encontrado em ({pos['x']:.0f}, {pos['y']:.0f}) — confiança {result['confidence']:.2f}")
            return f"Encontrei '{query}' na tela."
        reason = result.get("reason", "texto não visível")
        print(f"  Não encontrado: {reason}")
        return f"Não encontrei '{query}' na tela ({reason})."

    elif action == "analyze" or action == "describe":
        if vision is None:
            return "Sistema de visão não disponível no momento."
        question = params.get("question", "") or params.get("query", "") or None
        result = vision.analyze_screen(question=question)

        print(f"  Janela ativa: {result.active_application or 'desconhecida'}")

        # Se VLM forneceu descrição, usar direto
        if result.vision.available and result.vision.description:
            summary = result.vision.description[:300]
            print(f"  {summary}")
        # Se há texto OCR mas sem VLM, gerar resumo via LLM
        elif result.ocr.available and result.ocr.text:
            multi_chat = ctx.get("multi_chat")
            if multi_chat and multi_chat.available:
                ocr_text = result.ocr.text[:2000]
                window = result.active_application or "desconhecida"
                prompt = (
                    "Aqui está o texto extraído de uma captura de tela. "
                    f"Janela ativa: {window}.\n\n"
                    f"Texto OCR:\n{ocr_text}\n\n"
                    "Descreva em 1-2 frases naturais o que parece estar acontecendo "
                    "na tela, sem listar cada item. Seja conciso e útil."
                )
                try:
                    response = multi_chat.send(prompt, temperature=0.3, max_tokens=200)
                    if response and not response.startswith("Nenhum provedor") and not response.startswith("Todos os provedores"):
                        summary = response[:300]
                    else:
                        summary = "Detectei texto na tela, mas não consegui gerar um resumo agora."
                except Exception:
                    summary = "Detectei texto na tela, mas não consegui gerar um resumo agora."
            else:
                summary = "Detectei texto na tela, mas não consegui gerar um resumo agora."
            print(f"  {summary}")
        else:
            summary = "Sem texto detectável e sem modelo de visão ativo no momento."
            print(f"  {summary}")

        if result.errors_detected:
            for term in result.errors_detected:
                print(f"  ⚠ possível erro: {term}")
            summary += f" Possíveis erros detectados: {', '.join(result.errors_detected)}."

        return summary

    elif action == "ask":
        if vision is None:
            return "Sistema de visão não disponível no momento."
        question = params.get("question", "") or params.get("query", "") or ""
        answer = vision.ask(question)
        if answer:
            print(f"  {answer[:400]}")
            return answer[:300]
        return "Não consegui analisar visualmente agora (sem modelo de visão ativo)."

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
        return f"Pronto, memorizei: {text}"

    return ""


# ── Memory Search ───────────────────────────────────────────

@registry.register_intent("search", description="Buscar memória salva")
def handle_search_memory(action: str, params: dict, **ctx) -> str:
    if "query" not in params:
        return ""
    query = params.get("query", "")
    memory = ctx["memory"]
    results = memory.search(query=query)
    if not results:
        print("  Nenhuma memória encontrada.")
        return (f"Não encontrei nenhuma memória sobre {query}." if query
                else "Não encontrei nenhuma memória salva sobre você.")
    else:
        Terminal.print_separator()
        spoken = []
        for entry in results[:3]:
            imp_color = Terminal.GREEN if entry.importance >= 7 else Terminal.YELLOW
            print(f"  [{Terminal.colorize(entry.id, Terminal.CYAN)}] {entry.title}")
            print(f"    {entry.category.value} | Imp: {Terminal.colorize(str(entry.importance), imp_color)}")
            spoken.append(entry.content or entry.title)
        if len(results) > 3:
            print(f"  ... e mais {len(results) - 3} resultado(s).")
        Terminal.print_separator()
        total = len(results)
        if total == 1:
            return f"Encontrei uma memória: {spoken[0]}."
        return "Encontrei " + f"{total} memórias" + (f": {'; '.join(spoken)}." if spoken else ".")

    return ""


# ── Config ──────────────────────────────────────────────────

@registry.register_intent("config", description="Configurações do sistema")
def handle_config(action: str, params: dict, **ctx) -> str:
    settings = ctx.get("settings")
    if settings:
        print(f"  Diretório base: {settings.BASE_DIR}")
        print(f"  Modelo de chat: {settings.CHAT_MODEL}")
        safety_level = getattr(settings, "SAFETY_LEVEL", None)
        print(f"  Safety level: {safety_level if safety_level is not None else 'CAUTION (2) - padrão do registry'}")
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


# ── Percepção ───────────────────────────────────────────────

@registry.register_intent("perception", description="Percepção: o que o ARIS percebe (sensores, atenção, câmera)")
def handle_perception(action: str, params: dict, **ctx) -> str:
    perception = ctx.get("perception")
    if perception is None:
        print("  Percepção indisponível.")
        return "Percepção indisponível."

    action = (action or "status").lower()

    def _show(text: str) -> str:
        first = ""
        lines = [ln for ln in text.split("\n") if ln.strip()]
        for line in lines:
            print(line)
        if lines:
            first = lines[0].strip()
        return first

    if action == "sensors":
        return _show(perception.format_sensors())
    if action == "attention":
        return _show(perception.format_attention())
    if action == "camera":
        return _show(perception.format_camera())
    if action == "toggle":
        target = (params or {}).get("target")
        if target == "off":
            output = perception.toggle_perception(False)
        elif target == "on":
            output = perception.toggle_perception(True)
        else:
            output = perception.toggle_perception()
        print(f"  Percepção {'ativada.' if output else 'desativada.'}")
        return f"Percepção {'ativada' if output else 'desativada'}."
    return _show(perception.describe())


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
    "perception": 1,

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
