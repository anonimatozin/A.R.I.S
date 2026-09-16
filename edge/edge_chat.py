"""Edge Chat — instancia A.R.I.S. para modo edge (PC offline).

Conversa via Groq com chave separada, usa personalidade sincronizada,
e informa quando algo esta fora do escopo (requer PC).
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from urllib.request import Request, urlopen

from edge.edge_config import EdgeConfig

try:
    from core.neural.mode import get_mode_manager, ARISMode
    from core.neural.capabilities import get_capability_registry
except ImportError:
    get_mode_manager = None
    get_capability_registry = None
    ARISMode = None


def _detect_pc_ip() -> str | None:
    """Detecta IP do PC automaticamente na rede local."""
    import os
    import socket
    import struct

    # Tentar via env var primeiro
    env_host = os.getenv("PC_HOST")
    if env_host:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            if s.connect_ex((env_host, 8770)) == 0:
                s.close()
                return env_host
            s.close()
        except Exception:
            pass

    # Detectar IP local e escanear subrede
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        base = ".".join(local_ip.split(".")[:3]) + "."
    except Exception:
        base = "192.168.1."

    # Escanear IPs comuns
    for i in range(1, 255):
        ip = f"{base}{i}"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            if s.connect_ex((ip, 8770)) == 0:
                s.close()
                return ip
            s.close()
        except Exception:
            continue
    return None


_cached_pc_ip: str | None = None


def _get_pc_ip() -> str:
    """Retora IP do PC (cached ou detectado)."""
    global _cached_pc_ip
    if _cached_pc_ip:
        # Verificar se ainda esta acessivel
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            if s.connect_ex((_cached_pc_ip, 8770)) == 0:
                s.close()
                return _cached_pc_ip
            s.close()
        except Exception:
            pass
        _cached_pc_ip = None

    ip = _detect_pc_ip()
    if ip:
        _cached_pc_ip = ip
        return ip
    return os.getenv("PC_HOST", "192.168.0.109")


_pc_online_cache = {"result": None, "time": 0}

def _check_pc_online() -> bool:
    """Verifica se o PC esta acessivel via TCP (porta 8770 do pc_listener).
    Cache de 10 segundos pra evitar checks repetidos na mesma request."""
    import os
    import socket
    import time
    now = time.time()
    if _pc_online_cache["result"] is not None and now - _pc_online_cache["time"] < 10:
        return _pc_online_cache["result"]
    host = _get_pc_ip()
    port = int(os.getenv("PC_LISTENER_PORT", "8770"))
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        result = s.connect_ex((host, port))
        s.close()
        online = result == 0
    except Exception:
        online = False
    _pc_online_cache["result"] = online
    _pc_online_cache["time"] = now
    return online


def _send_pc_command(command: str, code: str = "") -> dict:
    """Envia comando ao PC listener HTTP."""
    import os
    host = _get_pc_ip()
    port = int(os.getenv("PC_LISTENER_PORT", "8770"))
    url = f"http://{host}:{port}"
    try:
        payload = {"command": command}
        if code:
            payload["code"] = code
        data = json.dumps(payload).encode()
        req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

DISCORD_MAX_LENGTH = 2000


class EdgeChat:
    """Chat da instancia edge (CLL1/PC offline).

    Args:
        config: Configuracao do edge.
    """

    def __init__(self, config: EdgeConfig | None = None) -> None:
        self._config = config or EdgeConfig.from_env()
        self._has_key = bool(self._config.edge_groq_api_key)
        self._personality = self._config.load_personality()
        self._history: list[dict[str, str]] = []
        self._memory_db: sqlite3.Connection | None = None
        self._request_count = 0
        self._request_window_start = time.time()
        self._pc_url = f"http://{_get_pc_ip()}:8770"

        self._init_memory_db()

    def _init_memory_db(self) -> None:
        """Inicializa SQLite local para memoria do edge."""
        try:
            db_dir = self._config.memory_dir / "database"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = db_dir / "aris_memory.db"
            self._memory_db = sqlite3.connect(str(db_path))
            self._memory_db.row_factory = sqlite3.Row
            self._memory_db.execute("PRAGMA journal_mode=WAL")
            self._memory_db.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    importance INTEGER DEFAULT 5,
                    created_at TEXT NOT NULL,
                    synced_to_pc INTEGER DEFAULT 0
                )
            """)
            self._memory_db.commit()
        except Exception:
            self._memory_db = None

    @property
    def available(self) -> bool:
        """Se o edge pode processar mensagens."""
        return self._has_key

    def respond(self, text: str, origin_info: dict | None = None) -> str:
        """Processa mensagem e retorna resposta.

        Args:
            text: Texto do usuario.
            origin_info: Metadados de origem.

        Returns:
            Resposta do edge.
        """
        if not self.available:
            return (
                "Estou no modo offline e nao tenho conexao com IA no momento. "
                "Tente novamente mais tarde."
            )

        if not self._check_rate_limit():
            return (
                "Limite de requisicoes atingido no modo edge. "
                "Aguarde um momento."
            )

        # Fast path — conversacao simples sem IA
        fast_result = self._try_fast_path(text)
        if fast_result is not None:
            return fast_result

        # Planner multi-intent — tenta resolver como plano de múltiplas ações
        planner_result = self._try_planner(text)
        if planner_result is not None:
            return planner_result

        # NLU fast path — tenta resolver sem LLM
        nlu_result = self._try_nlu(text)
        if nlu_result is not None:
            return nlu_result

        # Browser automation — controle de navegador
        browser_result = self._try_browser_tools(text)
        if browser_result is not None:
            return browser_result

        # Web intelligence — pesquisa autonoma
        web_result = self._try_web_intel(text)
        if web_result is not None:
            return web_result

        memories = self._search_memories(text)

        prompt = self._build_prompt(text, memories)

        self._history.append({"role": "user", "content": text})

        try:
            messages = [{"role": "system", "content": prompt}]
            messages.extend(self._history[-10:])

            # Rota LLM via PC listener (resolve bloqueio de IP no Groq)
            response = self._call_llm_via_pc(messages)
            if response is not None:
                self._history.append({"role": "assistant", "content": response})
                self._save_memory(text, response)
                try:
                    from core.personality import get_personality
                    personality = get_personality()
                    personality.record_interaction(text, response)
                except Exception:
                    pass
                return response

            # Fallback: Ollama local no CLL1
            response = self._call_ollama(messages)
            if response is not None:
                self._history.append({"role": "assistant", "content": response})
                self._save_memory(text, response)
                try:
                    from core.personality import get_personality
                    personality = get_personality()
                    personality.record_interaction(text, response)
                except Exception:
                    pass
                return response

            return "No momento nao consigo processar isso. O PC pode estar indisponivel. Tente novamente em instantes."

        except Exception as e:
            return (
                f"Erro no modo edge: {e}. "
                "Tente novamente ou espere o PC ficar online."
            )

    def _try_fast_path(self, text: str) -> str | None:
        """Conversacao simples que nao precisa de IA."""
        import re
        msg = text.lower().strip()

        if re.match(r"^(?:eai|oi|ola|fala|bom dia|boa tarde|boa noite|hey|hello|hi)\b", msg):
            from datetime import datetime
            hour = datetime.now().hour
            if hour < 12:
                salve = "Bom dia"
            elif hour < 18:
                salve = "Boa tarde"
            else:
                salve = "Boa noite"
            return f"{salve}! Como posso ajudar?"

        if re.match(r"^(?:aris\s+)?(?:obrigad[oa]|valeu|thanks|vlw|brigad)", msg):
            return "De nada! Sempre que precisar, e so chamar."

        if re.match(r"^(?:aris\s+)?(?:ta\s+)?(?:consegu(?:e|indo)|pode|sabe|esta)\s+.+", msg):
            return "Sim, to aqui e funcionando! Pode pedir o que precisar."

        if re.match(r"^(?:eai|oi|ola|fala)\s+(?:aris|man|amigo|bro)", msg):
            return "Fala! To no ar, pode mandar."

        if re.match(r"^(?:como\s+(?:vc|voce|ta|esta|vai)|tudo\s+(?:bem|certa|ok|beleza))", msg):
            return "Tudo bem! Aqui e a A.R.I.S., no ar e pronta pra ajudar."

        if re.match(r"^(?:aris\s+)?(?:atualiz(?:[aao]|ai|ou)|upgrade|new\s*version)", msg):
            return "Minha ultima atualizacao foi a versao mais recente do codigo. Quer que eu verifique algo especifico?"

        if re.match(r"^(?:aris\s+)?(?:vc|voce)\s+(?:e|eh|é)\s+(?:uma?|o)\s+.+", msg):
            return "Sou a A.R.I.S., sua assistente virtual! Posso ajudar com muitas coisas."

        # Status do PC — fast path sem LLM
        if msg in ("status", "status do pc", "pc status", "pc ta ligado", "pc ligado", "pc online"):
            import socket
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.5)
                result = s.connect_ex(("192.168.0.109", 8770))
                s.close()
                if result == 0:
                    return "O PC esta **online**. Posso executar comandos nele."
                else:
                    return "O PC esta **offline**. Posso operar no modo edge com funcoes basicas."
            except Exception:
                return "Nao consegui verificar o PC."

        # Comandos de PC — fast path sem LLM
        if msg in ("desligar", "desliga", "shutdown", "desligar pc"):
            return "Confirmar desligamento? Responda 'sim' pra confirmar."

        if msg in ("reiniciar", "reinicia", "restart", "reboot"):
            return "Confirmar reinicio? Responda 'sim' pra confirmar."

        if msg in ("travar", "trava", "lock", "bloquear"):
            return "Confirmar travamento? Responda 'sim' pra confirmar."

        if msg in ("hora", "que horas sao", "horas", "relogio"):
            from datetime import datetime
            now = datetime.now()
            return f"Sao **{now.strftime('%H:%M')}**."

        if msg in ("data", "que dia e hoje", "hoje"):
            from datetime import datetime
            now = datetime.now()
            return f"Hoje e **{now.strftime('%d/%m/%Y')}**."

        return None

    def _call_llm_via_pc(self, messages: list[dict]) -> str | None:
        """Rota LLM via PC listener — resolve bloqueio de IP no Groq."""
        import json as _json
        import urllib.request

        if not self._pc_url:
            return None

        try:
            payload = _json.dumps({
                "messages": messages,
                "model": self._config.edge_model,
                "api_key": self._config.edge_groq_api_key,
            }).encode("utf-8")

            req = urllib.request.Request(
                f"{self._pc_url}/api/llm",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=15) as resp:
                body = _json.loads(resp.read().decode("utf-8"))
                if body.get("ok"):
                    return body.get("response", "")
                return None

        except Exception:
            return None

    def _call_ollama(self, messages: list[dict]) -> str | None:
        """Chama Ollama local no CLL1 como fallback."""
        import json as _json
        import urllib.request
        import os

        ollama_host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
        model = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")

        # Verificar se Ollama ta rodando
        try:
            req = urllib.request.Request(f"{ollama_host}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                pass
        except Exception:
            return None

        try:
            payload = _json.dumps({
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"num_predict": 1024, "temperature": 0.7},
            }).encode("utf-8")

            req = urllib.request.Request(
                f"{ollama_host}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                body = _json.loads(resp.read().decode("utf-8"))
                return body.get("message", {}).get("content", "")

        except Exception:
            return None

    def _try_planner(self, text: str) -> str | None:
        """Tenta resolver como plano de múltiplas ações.

        Returns:
            Resposta se planner resolveu, None se precisa de outro handler.
        """
        try:
            from core.planner import create_planner, PlanStatus

            planner = create_planner(pc_listener_url=self._pc_url)

            # Verificar se a mensagem parece ter múltiplas ações
            # (pelo menos 2 conectivos ou 2 verbos de ação)
            import re
            action_verbs = [
                "desliga", "liga", "abre", "pesquisa", "reinicia",
                "trava", "dorme", "cancela", "entra", "executa",
            ]
            verb_count = sum(1 for v in action_verbs if v in text.lower())
            connectors = [" e ", " depois ", " então ", " quando ", " tambem ", " ai "]
            conn_count = sum(1 for c in connectors if c in text.lower())

            # Só usar planner se parece ter múltiplas ações
            if verb_count < 2 and conn_count < 1:
                return None

            plan = planner.parse(text)

            if plan.status == PlanStatus.FAILED:
                return None

            if not plan.actions:
                return None

            # Se tem apenas 1 ação, deixar o NLU fast path tratar
            if len(plan.actions) == 1:
                return None

            # Gerar resumo do plano
            summary = plan.to_human_summary()

            # Responder com o plano
            response = f"Entendi! Vou executar:\n{summary}"

            # Se tem ações que precisam de confirmação
            if plan.needs_confirmation:
                critical = [a for a in plan.actions if a.confirmation_required]
                if critical:
                    critical_desc = ", ".join(a.description for a in critical)
                    response += f"\n\nAtencao: {critical_desc} - essas acoes serao executadas. Confirmar?"

            return response

        except Exception as e:
            return None

    def _build_prompt(self, text: str, memories: list[dict]) -> str:
        """Construi prompt com personalidade e contexto edge."""
        try:
            from core.personality import get_personality
            personality = get_personality()
            situation = personality.detect_situation(text)
            personality_prompt = personality.generate_prompt(situation)
        except Exception:
            personality_prompt = self._personality

        parts = [personality_prompt]

        # Obter modo real do ModeManager
        mode_label = "EDGE (PC offline)"
        if get_mode_manager and get_capability_registry:
            try:
                mm = get_mode_manager()
                cr = get_capability_registry()
                mode_label = mm.describe()
                caps = cr.available_in_mode(mm.mode)
                caps_names = [c.name for c in caps[:15]]
                parts.append(f"\n## Modo atual: {mode_label}")
                parts.append(f"Capacidades disponiveis: {', '.join(caps_names)}")
                unavailable = [c.name for c in cr.available_in_mode(ARISMode.PRIMARY)
                               if not cr.is_available(c.name, mm.mode)][:10]
                if unavailable:
                    parts.append(f"Capacidades indisponiveis (requerem PC): {', '.join(unavailable)}")
            except Exception:
                parts.append(f"\n## Modo atual: {mode_label}")
                parts.append("Capacidades: conversa, memoria, pesquisa basica.")
        else:
            parts.append(f"\n## Modo atual: {mode_label}")
            parts.append("Capacidades: conversa, memoria, pesquisa basica.")

        parts.append(
            "Se o usuario pedir algo que voce nao consegue fazer no modo edge, "
            "explique naturalmente e sugira ligar o PC."
        )

        if memories:
            parts.append("\n## Memorias relevantes:")
            for m in memories[:5]:
                parts.append(f"- {m.get('content', '')[:160]}")

        # UI Skills — design engineering guidelines
        ui_keywords = ["ui", "dashboard", "interface", "design", "css", "html",
                       "component", "layout", "typography", "animation", "accessibility",
                       "a11y", "frontend", "estilo", "visual", "tela"]
        if any(kw in text.lower() for kw in ui_keywords):
            try:
                from core.ui_skills import get_ui_skills
                ui_skills = get_ui_skills()
                context = "ui" if "ui" in text.lower() else "general"
                skills_prompt = ui_skills.get_rules_for_context(context)
                if skills_prompt:
                    parts.append(f"\n{skills_prompt}")
            except Exception:
                pass

        # Knowledge Graph context
        try:
            from core.knowledge_graph import get_knowledge_graph
            kg = get_knowledge_graph()
            kg_context = kg.export_context(text, max_chars=1500)
            if kg_context:
                parts.append(f"\n{kg_context}")
        except Exception:
            pass

        return "\n".join(parts)

    def _try_nlu(self, text: str) -> str | None:
        """Tenta resolver via NLU + tools locais.

        Returns:
            Resposta se NLU resolveu, None se precisa de LLM.
        """
        try:
            from core.nlu import IntentType, NLUEngine
            from core.tools.wol import WakeOnLan

            nlu = NLUEngine()
            result = nlu.detect(text)

            if nlu.should_use_llm(result):
                return None

            # PC Control (shutdown, restart, sleep, lock, wake, status)
            if result.intent == IntentType.PC_CONTROL:
                action = result.params.get("action", "")

                if action == "status":
                    pc_online = _check_pc_online()
                    if pc_online:
                        return "O PC esta **online** no momento. Modo: PRIMARY."
                    else:
                        return "O PC esta **offline** no momento. Estou operando no modo edge (CLL1)."

                if action == "wake":
                    wol = WakeOnLan()
                    if not wol.configured:
                        return "A capacidade de Wake-on-LAN nao esta habilitada. Preciso do MAC address do PC."
                    r = wol.send_magic_packet()
                    if r:
                        return "Enviando sinal Wake-on-LAN para o PC. O PC deve ligar em alguns segundos."
                    return "Erro ao enviar Wake-on-LAN."

                if action == "shutdown":
                    pc_online = _check_pc_online()
                    if not pc_online:
                        return "O PC esta offline. Nao consigo desligar um PC que ja esta desligado."
                    r = _send_pc_command("shutdown")
                    if r.get("ok"):
                        return "Desligando o PC agora."
                    return f"Erro ao desligar: {r.get('error', 'desconhecido')}"

                if action == "restart":
                    pc_online = _check_pc_online()
                    if not pc_online:
                        return "O PC esta offline. Nao consigo reiniciar."
                    r = _send_pc_command("restart")
                    if r.get("ok"):
                        return "Reiniciando o PC agora."
                    return f"Erro ao reiniciar: {r.get('error', 'desconhecido')}"

                if action == "lock":
                    pc_online = _check_pc_online()
                    if not pc_online:
                        return "O PC esta offline. Nao consigo travar."
                    r = _send_pc_command("lock")
                    if r.get("ok"):
                        return "PC travado."
                    return f"Erro ao travar: {r.get('error', 'desconhecido')}"

                if action == "sleep":
                    pc_online = _check_pc_online()
                    if not pc_online:
                        return "O PC esta offline. Nao consigo colocar em sleep."
                    return "Sleep remoto ainda nao esta disponivel."

            # Pesquisa
            if result.intent in (IntentType.SEARCH, IntentType.RESEARCH, IntentType.EXPLAIN):
                query = result.params.get("query", text)
                pc_online = _check_pc_online()
                if pc_online:
                    code = f"import webbrowser; webbrowser.open('https://www.google.com/search?q={query}')"
                    r = _send_pc_command("exec", code)
                    if r.get("ok"):
                        return f"Pesquisando sobre: {query}"
                return f"Vou pesquisar sobre: {query}"

            # Abrir/Executar
            if result.intent == IntentType.OPEN:
                target = result.params.get("target", "")
                pc_online = _check_pc_online()
                if not pc_online:
                    return f"O PC esta offline. Nao consigo executar '{target}'."
                code = f"import subprocess; subprocess.Popen(['cmd', '/c', 'start', '', '{target}'], shell=False)"
                r = _send_pc_command("exec", code)
                if r.get("ok"):
                    return f"Abrindo {target} no PC."
                return f"Erro ao abrir {target}: {r.get('error', 'desconhecido')}"

            # Visitar URL
            if result.intent == IntentType.VISIT:
                url = result.params.get("url", text)
                pc_online = _check_pc_online()
                if not pc_online:
                    return f"O PC esta offline. Nao consigo abrir {url}."
                if not url.startswith("http"):
                    url = f"https://www.google.com/search?q={url}"
                code = f"import webbrowser; webbrowser.open('{url}')"
                r = _send_pc_command("exec", code)
                if r.get("ok"):
                    return f"Abrindo {url} no PC."
                return f"Erro ao abrir: {r.get('error', 'desconhecido')}"

            # Verificar
            if result.intent == IntentType.VERIFY:
                return f"Vou verificar: '{result.params.get('claim', text)}'. Buscando informacoes..."

            # Comparar
            if result.intent == IntentType.COMPARE:
                items = result.params.get("items", [])
                if len(items) >= 2:
                    return f"Vou comparar {items[0]} com {items[1]}..."

            # Latest
            if result.intent == IntentType.LATEST:
                topic = result.params.get("topic", text)
                return f"Vou buscar as ultimas noticias sobre: {topic}"

            # Tempo
            if result.intent == IntentType.WEATHER:
                city = result.params.get("city", "sua regiao")
                return f"Vou consultar o tempo em {city}..."

            # Agendamento
            if result.intent == IntentType.SCHEDULE:
                action = result.params.get("action", "")
                time_str = result.params.get("time", "")

                if action == "cancel":
                    pc_online = _check_pc_online()
                    if pc_online:
                        code = "from core.tools.power_scheduler import cancel_shutdown; print(cancel_shutdown())"
                        r = _send_pc_command("exec", code)
                        return "Desligamento cancelado."
                    return "Nao ha agendamentos para cancelar."

                if action == "query":
                    pc_online = _check_pc_online()
                    if pc_online:
                        code = "from core.tools.power_scheduler import get_scheduled_shutdown; print(get_scheduled_shutdown())"
                        r = _send_pc_command("exec", code)
                        return "Verificando agendamentos..."
                    return "Nao consigo verificar agendamentos com PC offline."

                if action == "shutdown" and time_str:
                    pc_online = _check_pc_online()
                    if not pc_online:
                        return "O PC esta offline. Nao posso agendar desligamento."
                    code = f"from core.tools.power_scheduler import schedule_shutdown; print(schedule_shutdown(at='{time_str}'))"
                    r = _send_pc_command("exec", code)
                    if r.get("ok"):
                        return f"Desligamento agendado para {time_str}."
                    return f"Erro ao agendar: {r.get('error', 'desconhecido')}"

                if action == "wake" and time_str:
                    pc_online = _check_pc_online()
                    if not pc_online:
                        return "O PC esta offline. Nao posso agendar ligamento."
                    code = f"from core.tools.power_scheduler import schedule_wake; print(schedule_wake(at='{time_str}'))"
                    r = _send_pc_command("exec", code)
                    if r.get("ok"):
                        return f"Ligamento agendado para {time_str}."
                    return f"Erro ao agendar: {r.get('error', 'desconhecido')}"

                return "Qual agendamento voce quer? Desligar, ligar ou cancelar?"

            return None

        except Exception:
            return None

    def _try_browser_tools(self, text: str) -> str | None:
        """Browser automation — abre navegador, navega, clica, tira screenshot."""
        import re
        msg = text.lower().strip()

        if not _check_pc_online():
            return None

        # Abrir navegador
        m = re.search(r"(?:abre|abra|abra o|abrir|open)\s+(?:navegador|browser|chrome|firefox)\s*(?:em|no|na)?\s*(.+)?", msg)
        if m:
            url = m.group(1) or "https://www.google.com"
            url = url.strip()
            if not url.startswith("http"):
                url = "https://" + url
            result = _send_pc_command({"command": "browser_open", "url": url})
            if result and result.get("ok"):
                return f"Navegador aberto em **{url}**. Titulo: {result.get('title', 'N/A')}"
            return f"Erro ao abrir navegador: {result.get('error', 'desconhecido')}"

        # Navegar para URL
        m = re.search(r"(?:navegue|va para|acesse|goto|navigate|abre)\s+(https?://.+)", msg)
        if m:
            url = m.group(1).strip()
            result = _send_pc_command({"command": "browser_navigate", "url": url})
            if result and result.get("ok"):
                return f"Naveguei para **{url}**. Titulo: {result.get('title', 'N/A')}"
            return f"Erro ao navegar: {result.get('error', 'desconhecido')}"

        # Screenshot
        if re.search(r"(?:screenshot|captura|print|foto da tela|tela)", msg):
            result = _send_pc_command({"command": "browser_screenshot"})
            if result and result.get("ok"):
                return f"Screenshot capturada ({result.get('size', 0)} bytes)."
            return f"Erro ao capturar screenshot: {result.get('error', 'desconhecido')}"

        # Snapshot da pagina
        if re.search(r"(?:snapshot|conteudo da pagina|texto da pagina|o que tem na pagina)", msg):
            result = _send_pc_command({"command": "browser_snapshot"})
            if result and result.get("ok"):
                text_content = result.get("text", "")[:2000]
                return f"Pagina: **{result.get('title', 'N/A')}**\n\n{text_content}"
            return f"Erro ao obter snapshot: {result.get('error', 'desconhecido')}"

        # Clicar em elemento
        m = re.search(r"(?:clique|click|aperte)\s+(?:em|no|na)?\s*(.+)", msg)
        if m:
            selector = m.group(1).strip()
            result = _send_pc_command({"command": "browser_click", "selector": selector})
            if result and result.get("ok"):
                return f"Cliquei em **{selector}**."
            return f"Erro ao clicar: {result.get('error', 'desconhecido')}"

        # Digitar em campo
        m = re.search(r"(?:digite|type|escreva|preencha)\s+(.+?)(?:\s+em|no|na|into)\s+(.+)", msg)
        if m:
            text_to_type = m.group(1).strip()
            selector = m.group(2).strip()
            result = _send_pc_command({"command": "browser_type", "selector": selector, "text": text_to_type})
            if result and result.get("ok"):
                return f"Digitei **{text_to_type}** em **{selector}**."
            return f"Erro ao digitar: {result.get('error', 'desconhecido')}"

        # Fechar navegador
        if re.search(r"(?:feche|close|fecha)\s+(?:navegador|browser|aba)", msg):
            result = _send_pc_command({"command": "browser_close"})
            if result and result.get("ok"):
                return "Navegador fechado."
            return f"Erro ao fechar: {result.get('error', 'desconhecido')}"

        return None

    def _try_web_intel(self, text: str) -> str | None:
        """Pesquisa web autonoma — busca, le e resume."""
        try:
            from core.nlu import IntentType, NLUEngine

            nlu = NLUEngine()
            result = nlu.detect(text)

            # So busca se NLU tem confianca suficiente
            if result.confidence < 0.35:
                return None

            # SEARCH — busca simples
            if result.intent == IntentType.SEARCH:
                query = result.params.get("query", text)
                if not query or len(query) < 3:
                    return None

                try:
                    from core.web_intel import quick_answer
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                        future = ex.submit(quick_answer, query)
                        answer = future.result(timeout=12)
                    if answer and answer.get("ok"):
                        resp = answer["answer"]
                        sources = answer.get("sources", [])
                        if sources:
                            resp += "\n\nFontes: " + ", ".join(sources[:3])
                        return resp
                except Exception:
                    pass

            # LATEST — noticias recentes
            if result.intent == IntentType.LATEST:
                topic = result.params.get("topic", text)
                if not topic or len(topic) < 3:
                    return None

                try:
                    from core.web_intel import web_search
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                        future = ex.submit(web_search, f"{topic} noticias recentes 2026", 5)
                        search = future.result(timeout=12)
                    if search and search.get("ok") and search.get("results"):
                        resp = f"**Noticias recentes sobre {topic}:**\n\n"
                        for r in search["results"][:5]:
                            title = r.get("title", "")
                            snippet = r.get("snippet", "")
                            url = r.get("url", "")
                            if title:
                                resp += f"- **{title}**\n  {snippet}\n  {url}\n\n"
                        return resp
                except Exception:
                    pass

            return None

        except Exception:
            return None

    def _check_rate_limit(self) -> bool:
        """Verifica rate limit (100 req/min por padrao)."""
        now = time.time()
        if now - self._request_window_start > 60:
            self._request_count = 0
            self._request_window_start = now

        if self._request_count >= self._config.edge_rate_limit:
            return False

        self._request_count += 1
        return True

    def _search_memories(self, query: str) -> list[dict]:
        """Busca memorias relevantes no SQLite local."""
        if not self._memory_db:
            return []
        try:
            cursor = self._memory_db.execute(
                "SELECT content, category, importance FROM memories "
                "WHERE content LIKE ? ORDER BY importance DESC LIMIT 5",
                (f"%{query[:50]}%",),
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            return []

    def _save_memory(self, user_text: str, response: str) -> None:
        """Salva interacao na memoria local e knowledge graph."""
        if not self._memory_db:
            return
        try:
            mem_id = str(uuid.uuid4())[:8]
            now = datetime.now(UTC).isoformat()
            self._memory_db.execute(
                "INSERT INTO memories (id, content, category, importance, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (mem_id, f"User: {user_text}\nA.R.I.S.: {response}", "conversation", 5, now),
            )
            self._memory_db.commit()
        except Exception:
            pass

        # Salvar no knowledge graph
        try:
            from core.knowledge_graph import get_knowledge_graph
            kg = get_knowledge_graph()
            kg.store(
                content=f"User asked: {user_text[:200]} | A.R.I.S. answered: {response[:200]}",
                node_type="conversation",
                tags=["edge", "auto"],
            )
        except Exception:
            pass

    def get_pending_sync(self) -> list[dict]:
        """Retorna memorias que ainda nao foram sincronizadas com o PC."""
        if not self._memory_db:
            return []
        try:
            cursor = self._memory_db.execute(
                "SELECT id, content, category, importance, created_at "
                "FROM memories WHERE synced_to_pc = 0"
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            return []

    def mark_synced(self, ids: list[str]) -> None:
        """Marca memorias como sincronizadas."""
        if not self._memory_db or not ids:
            return
        try:
            placeholders = ",".join("?" * len(ids))
            self._memory_db.execute(
                f"UPDATE memories SET synced_to_pc = 1 WHERE id IN ({placeholders})",
                ids,
            )
            self._memory_db.commit()
        except Exception:
            pass

    def import_from_pc(self, records: list[dict]) -> int:
        """Importa memorias vindas do PC (sync)."""
        if not self._memory_db or not records:
            return 0

        imported = 0
        for rec in records:
            try:
                self._memory_db.execute(
                    "INSERT OR IGNORE INTO memories "
                    "(id, content, category, importance, created_at, synced_to_pc) "
                    "VALUES (?, ?, ?, ?, ?, 1)",
                    (
                        rec.get("id", str(uuid.uuid4())[:8]),
                        rec.get("content", ""),
                        rec.get("category", "general"),
                        rec.get("importance", 5),
                        rec.get("created_at", datetime.now(UTC).isoformat()),
                    ),
                )
                imported += 1
            except Exception:
                continue

        self._memory_db.commit()
        return imported
