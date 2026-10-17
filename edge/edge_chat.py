"""Edge Chat — instancia A.R.I.S. para modo edge (PC offline).

Conversa via Groq com chave separada, usa personalidade sincronizada,
e informa quando algo esta fora do escopo (requer PC).
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from urllib.request import Request, urlopen

from edge.edge_config import EdgeConfig

try:
    from core.neural.capabilities import get_capability_registry
    from core.neural.mode import ARISMode, get_mode_manager
except ImportError:
    get_mode_manager = None
    get_capability_registry = None
    ARISMode = None


def _detect_pc_ip() -> str | None:
    """Detecta IP do PC automaticamente na rede local."""
    import os
    import socket
    import time

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

    # Localhost primeiro: HUD/gateway rodam no próprio PC
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        if s.connect_ex(("127.0.0.1", 8770)) == 0:
            s.close()
            return "127.0.0.1"
        s.close()
    except Exception:
        pass

    # Detectar IP local e escanear subrede (com timeout total de 3s)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        base = ".".join(local_ip.split(".")[:3]) + "."
    except Exception:
        base = "192.168.1."

    # Escanear IPs comuns - timeout total 3s, por IP 0.05s
    scan_start = time.time()
    max_scan_time = 3.0
    per_ip_timeout = 0.05
    for i in range(1, 255):
        if time.time() - scan_start > max_scan_time:
            break
        ip = f"{base}{i}"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(per_ip_timeout)
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


def _send_pc_command(command: str, **params) -> dict:
    """Envia uma ação da lista fixa ao PC listener HTTP.

    ``command`` deve estar em ``agent.pc_actions.ALLOWED_COMMANDS`` —
    o bridge recusa qualquer coisa fora da lista.
    """
    import os
    host = _get_pc_ip()
    port = int(os.getenv("PC_LISTENER_PORT", "8770"))
    url = f"http://{host}:{port}"
    try:
        payload = {"command": command}
        payload.update({k: v for k, v in params.items() if v is not None})
        data = json.dumps(payload).encode()
        req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

DISCORD_MAX_LENGTH = 2000

# Parte 8: ponte do agente no perfil edge (desligada por padrão).
# Cacheia a construção (inclusive a falha) para não remontar a cada mensagem.
_AGENTE_EDGE: dict[str, object] = {"ponte": None, "tentou": False}


def _agente_edge(texto: str) -> str | None:
    """Tenta tratar `texto` com o agente no perfil edge (só web + memória).

    Só roda com ARIS_AGENT_ENABLED=true (padrão: fora => zero mudança no
    comportamento atual). Confirmação sem canal de voz nega por timeout.
    Qualquer falha devolve None e o fluxo atual do edge segue intacto.
    """
    if os.environ.get("ARIS_AGENT_ENABLED", "").strip().lower() not in (
        "true",
        "1",
        "yes",
        "on",
    ):
        return None
    if not _AGENTE_EDGE["tentou"]:
        _AGENTE_EDGE["tentou"] = True
        try:
            from aris_agent.bridge import build_bridge

            _AGENTE_EDGE["ponte"] = build_bridge(
                falar=lambda _texto, *, sync=False: None,
                ouvir=lambda _timeout_s: None,
                perfil="edge",
            )
        except Exception:
            _AGENTE_EDGE["ponte"] = None
    ponte = _AGENTE_EDGE["ponte"]
    if ponte is None:
        return None
    try:
        return ponte.processar(texto)
    except Exception:
        return None


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
            # Privacidade estrutural (idempotente pra DBs já existentes)
            try:
                self._memory_db.execute(
                    "ALTER TABLE memories ADD COLUMN scope TEXT NOT NULL DEFAULT 'shared'"
                )
            except Exception:
                pass
            try:
                self._memory_db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope)"
                )
            except Exception:
                pass
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
            origin_info: Metadados de origem (pode conter 'history' para histórico do canal Discord).

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

        # Parte 8: agente edge (desligado por padrão; ver _agente_edge)
        resposta_agente = _agente_edge(text)
        if resposta_agente is not None:
            return resposta_agente

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

        # Privacidade estrutural: scope vem do canal (guild_spaces), com
        # fallback DM (dono lê shared+próprio private; demais, só shared).
        mem_scope = "shared"
        mem_allowed: list[str] | None = None
        if origin_info:
            mem_scope = str(origin_info.get("memory_scope", "shared") or "shared")
            mem_allowed = origin_info.get("allowed_scopes")
            if mem_allowed is None and origin_info.get("source") == "discord":
                try:
                    from modules.guild_spaces import allowed_scopes as _allowed
                    mem_allowed = _allowed(
                        str(origin_info.get("guild_category") or ""),
                        str(origin_info.get("user_id") or ""),
                    )
                except Exception:
                    mem_allowed = ["shared"]
        memories = self._search_memories(text, allowed_scopes=mem_allowed)

        prompt = self._build_prompt(text, memories)

        # Use conversation history from origin_info (Discord channel history) if available,
        # otherwise fall back to internal _history. Sempre copiar para não mutar lista do bot
        # (antes o edge fazia append na mesma lista do DiscordBot, duplicando user/assistant).
        conversation_history = []
        if origin_info and "history" in origin_info:
            conversation_history = list(origin_info["history"])
        else:
            conversation_history = list(self._history)

        conversation_history.append({"role": "user", "content": text})

        try:
            messages = [{"role": "system", "content": prompt}]
            messages.extend(conversation_history[-10:])

            # Rota LLM: Ollama local (se disponível) → PC listener (Groq) → erro
            response = self._call_ollama(messages)
            if response is not None:
                conversation_history.append({"role": "assistant", "content": response})
                # Update internal history if not using external history
                if not (origin_info and "history" in origin_info):
                    self._history = conversation_history
                self._save_memory(text, response, scope=mem_scope)
                try:
                    from core.personality import get_personality
                    personality = get_personality()
                    personality.record_interaction(text, response)
                except Exception:
                    pass
                return response

            # Fallback: Groq via PC listener
            response = self._call_llm_via_pc(messages)
            if response is not None:
                conversation_history.append({"role": "assistant", "content": response})
                if not (origin_info and "history" in origin_info):
                    self._history = conversation_history
                self._save_memory(text, response, scope=mem_scope)
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
        import random
        import re
        # Extras20 primeiro (reusa fast-path; sem LLM, sem nova conexão)
        try:
            from modules.extras20 import handle as _extras_handle
            r = _extras_handle(text)
            if r:
                return r
        except Exception:
            pass
        # Casa (qualquer canal; sem hardware = recusa explícita, sem mock)
        try:
            from modules.home_control import handle as _home_handle
            r = _home_handle(text)
            if r:
                return r
        except Exception:
            pass
        msg = text.lower().strip()

        # Check if this is just an attention call ("aris" at start or alone)
        is_attention_call = bool(re.match(r"^(?:aris\s*[,.]?\s*)?$", msg))

        if re.match(r"^(?:eai|oi|ola|fala|bom dia|boa tarde|boa noite|hey|hello|hi)\b", msg):
            from datetime import datetime
            hour = datetime.now().hour
            if hour < 12:
                base_greeting = "Bom dia"
            elif hour < 18:
                base_greeting = "Boa tarde"
            else:
                base_greeting = "Boa noite"

            # Variations for greetings
            if is_attention_call:
                # Just "aris" alone - shorter response
                variations = [
                    "Oi! Em que posso ajudar?",
                    "Oi! Tudo bem?",
                    "Fala!",
                    "Oi! To aqui.",
                ]
                return random.choice(variations)
            else:
                variations = [
                    f"{base_greeting}! Como posso ajudar?",
                    f"{base_greeting}! Tudo bem?",
                    f"{base_greeting}! Em que posso ser útil?",
                    f"{base_greeting}! Fala aí.",
                ]
                return random.choice(variations)

        if re.match(r"^(?:aris\s+)?(?:obrigad[oa]|valeu|thanks|vlw|brigad)", msg):
            variations = [
                "De nada! Sempre que precisar, é só chamar.",
                "Imagina! Tô aqui pra isso.",
                "De nada! Qualquer coisa é só falar.",
            ]
            return random.choice(variations)

        if re.match(r"^(?:aris\s+)?(?:ta\s+)?(?:consegu(?:e|indo)|pode|sabe|esta)\s+.+", msg):
            variations = [
                "Sim, tô aqui e funcionando! Pode pedir o que precisar.",
                "Tô funcionando sim! O que você precisa?",
                "Sim, tudo certo por aqui. Manda!",
            ]
            return random.choice(variations)

        if re.match(r"^(?:eai|oi|ola|fala)\s+(?:aris|man|amigo|bro)", msg):
            variations = [
                "Fala! Tô no ar, pode mandar.",
                "Oi! Tô aqui. O que você precisa?",
                "Fala aí!",
            ]
            return random.choice(variations)

        if re.match(r"^(?:como\s+(?:vc|voce|ta|esta|vai)|tudo\s+(?:bem|certa|ok|beleza))", msg):
            variations = [
                "Tudo bem! Aqui é a A.R.I.S., no ar e pronta pra ajudar.",
                "Tudo certo! Como posso ajudar hoje?",
                "Tudo bem por aqui. E com você?",
            ]
            return random.choice(variations)

        if re.match(r"^(?:aris\s+)?(?:atualiz(?:[aao]|ai|ou)|upgrade|new\s*version)", msg):
            variations = [
                "Minha última atualização foi a versão mais recente do código. Quer que eu verifique algo específico?",
                "Tô na versão mais recente. Precisa de algo?",
                "Código atualizado. Quer que eu cheque algo?",
            ]
            return random.choice(variations)

        if re.match(r"^(?:aris\s+)?(?:vc|voce)\s+(?:e|eh|é)\s+(?:uma?|o)\s+.+", msg):
            variations = [
                "Sou a A.R.I.S., sua assistente virtual! Posso ajudar com muitas coisas.",
                "Sou a A.R.I.S.! Criada pelo Vinicius. Em que posso ajudar?",
            ]
            return random.choice(variations)

        # Status do PC — fast path sem LLM
        if msg in ("status", "status do pc", "pc status", "pc ta ligado", "pc ligado", "pc online"):
            import socket
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.5)
                result = s.connect_ex(("192.168.0.109", 8770))
                s.close()
                if result == 0:
                    return "O PC está **online**. Posso executar comandos nele."
                else:
                    return "O PC está **offline**. Posso operar no modo edge com funções básicas."
            except Exception:
                return "Não consegui verificar o PC."

        # Comandos de PC — fast path sem LLM
        if msg in ("desligar", "desliga", "shutdown", "desligar pc") or ("deslig" in msg and ("pc" in msg or "computador" in msg or "tudo" in msg)):
            return "Confirmar desligamento? Responda 'sim' pra confirmar."

        if msg in ("reiniciar", "reinicia", "restart", "reboot") or ("reinici" in msg and ("pc" in msg or "computador" in msg)):
            return "Confirmar reinício? Responda 'sim' pra confirmar."

        if msg in ("travar", "trava", "lock", "bloquear") or ("trav" in msg and ("pc" in msg or "computador" in msg)):
            return "Confirmar travamento? Responda 'sim' pra confirmar."

        if msg in ("hora", "que horas sao", "horas", "relogio"):
            from datetime import datetime
            now = datetime.now()
            return f"São **{now.strftime('%H:%M')}**."

        if msg in ("data", "que dia e hoje", "hoje"):
            from datetime import datetime
            now = datetime.now()
            return f"Hoje é **{now.strftime('%d/%m/%Y')}**."

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
        import os
        import urllib.request

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
            # Ignorar perguntas simples, matematica, cumprimentos
            import re
            msg = text.lower().strip()
            # Perguntas que NÃO são ações
            skip_patterns = [
                r"^\d+[\+\-\*\/]\d+",  # matematica: 1+1, 2*3
                r"^(quanto|qual|onde|como|por que|porque|quem|quando|o que|que)\b",  # perguntas
                r"^(oi|ola|eai|fala|bom dia|boa tarde|boa noite|obrigad|valeu)",  # cumprimentos
                r"^(status|hora|data|ajuda|help)",  # comandos simples
                r"^\d+\s*[\+\-\*\/]\s*\d+",  # expressoes matematicas
                # Reflexivo/conversacional - não é ação
                r"^(eu to|eu estou|tava|to) (pensando|achando|vendo|sentindo|lembrando|decidindo|na duvida|em duvida)",  # reflexivo
                r"^(acho que|sera que|talvez|provavelmente|pode ser|nao sei)",  # incerteza
                r"(amanha|hoje|ontem) (e|é) (meu|minha|nosso|nossa) (aniversario|niver)",  # datas pessoais
            ]
            for pat in skip_patterns:
                if re.match(pat, msg):
                    return None

            from core.planner import PlanStatus, create_planner

            planner = create_planner(pc_listener_url=self._pc_url)

            # Verificar se a mensagem parece ter múltiplas ações
            # (pelo menos 2 conectivos ou 2 verbos de ação)
            action_verbs = [
                "desliga", "liga", "abre", "pesquisa", "reinicia",
                "trava", "dorme", "cancela", "entra", "executa",
            ]
            verb_count = sum(1 for v in action_verbs if v in msg)
            connectors = [" e ", " depois ", " então ", " quando ", " tambem ", " ai "]
            conn_count = sum(1 for c in connectors if c in msg)

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

        except Exception:
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
            # Deixar para _try_web_intel fazer a busca real (quick_answer/web_search)
            # NLU só detecta a intenção, não executa a busca
            if result.intent in (IntentType.SEARCH, IntentType.RESEARCH, IntentType.EXPLAIN):
                return None

            # Abrir/Executar
            if result.intent == IntentType.OPEN:
                params = result.params or {}
                target = params.get("target", "") or ""
                pc_online = _check_pc_online()
                if not pc_online:
                    return f"O PC esta offline. Nao consigo executar '{target}'."
                r = _send_pc_command("open_app", target=target) or {}
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
                r = _send_pc_command("open_url", url=url)
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
            # Deixar para _try_web_intel fazer a busca real de notícias
            if result.intent == IntentType.LATEST:
                return None

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
                        _send_pc_command("schedule_cancel")
                        return "Desligamento cancelado."
                    return "Nao ha agendamentos para cancelar."

                if action == "query":
                    pc_online = _check_pc_online()
                    if pc_online:
                        _send_pc_command("schedule_query")
                        return "Verificando agendamentos..."
                    return "Nao consigo verificar agendamentos com PC offline."

                if action == "shutdown" and time_str:
                    pc_online = _check_pc_online()
                    if not pc_online:
                        return "O PC esta offline. Nao posso agendar desligamento."
                    r = _send_pc_command("schedule_shutdown", at=time_str)
                    if r.get("ok"):
                        return f"Desligamento agendado para {time_str}."
                    return f"Erro ao agendar: {r.get('error', 'desconhecido')}"

                if action == "wake" and time_str:
                    pc_online = _check_pc_online()
                    if not pc_online:
                        return "O PC esta offline. Nao posso agendar ligamento."
                    r = _send_pc_command("schedule_wake", at=time_str)
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
            result = _send_pc_command("browser_open", url=url)
            if result and result.get("ok"):
                return f"Navegador aberto em **{url}**. Titulo: {result.get('title', 'N/A')}"
            return f"Erro ao abrir navegador: {result.get('error', 'desconhecido')}"

        # Navegar para URL
        m = re.search(r"(?:navegue|va para|acesse|goto|navigate|abre)\s+(https?://.+)", msg)
        if m:
            url = m.group(1).strip()
            result = _send_pc_command("browser_navigate", url=url)
            if result and result.get("ok"):
                return f"Naveguei para **{url}**. Titulo: {result.get('title', 'N/A')}"
            return f"Erro ao navegar: {result.get('error', 'desconhecido')}"

        # Screenshot
        if re.search(r"(?:screenshot|captura|print|foto da tela|tela)", msg):
            result = _send_pc_command("browser_screenshot")
            if result and result.get("ok"):
                return f"Screenshot capturada ({result.get('size', 0)} bytes)."
            return f"Erro ao capturar screenshot: {result.get('error', 'desconhecido')}"

        # Snapshot da pagina
        if re.search(r"(?:snapshot|conteudo da pagina|texto da pagina|o que tem na pagina)", msg):
            result = _send_pc_command("browser_snapshot")
            if result and result.get("ok"):
                text_content = result.get("text", "")[:2000]
                return f"Pagina: **{result.get('title', 'N/A')}**\n\n{text_content}"
            return f"Erro ao obter snapshot: {result.get('error', 'desconhecido')}"

        # Clicar em elemento
        m = re.search(r"(?:clique|click|aperte)\s+(?:em|no|na)?\s*(.+)", msg)
        if m:
            selector = m.group(1).strip()
            result = _send_pc_command("browser_click", selector=selector)
            if result and result.get("ok"):
                return f"Cliquei em **{selector}**."
            return f"Erro ao clicar: {result.get('error', 'desconhecido')}"

        # Digitar em campo
        m = re.search(r"(?:digite|type|escreva|preencha)\s+(.+?)(?:\s+em|no|na|into)\s+(.+)", msg)
        if m:
            text_to_type = m.group(1).strip()
            selector = m.group(2).strip()
            result = _send_pc_command("browser_type", selector=selector, text=text_to_type)
            if result and result.get("ok"):
                return f"Digitei **{text_to_type}** em **{selector}**."
            return f"Erro ao digitar: {result.get('error', 'desconhecido')}"

        # Fechar navegador
        if re.search(r"(?:feche|close|fecha)\s+(?:navegador|browser|aba)", msg):
            result = _send_pc_command("browser_close")
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
                    import concurrent.futures

                    from core.web_intel import quick_answer
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
                    import concurrent.futures

                    from core.web_intel import web_search
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

    def _search_memories(
        self, query: str, allowed_scopes: list[str] | None = None
    ) -> list[dict]:
        """Busca memorias relevantes no SQLite local, com filtro de scope.

        allowed_scopes=None = sem filtro (legado). O caminho de conversa do
        Discord sempre informa a lista (guild_spaces.allowed_scopes) — o
        isolamento é filtro de query, nunca instrução de prompt.
        """
        if not self._memory_db:
            return []
        try:
            if allowed_scopes is not None:
                if not allowed_scopes:
                    return []
                placeholders = ",".join("?" * len(allowed_scopes))
                cursor = self._memory_db.execute(
                    "SELECT content, category, importance, scope FROM memories "
                    f"WHERE content LIKE ? AND scope IN ({placeholders}) "
                    "ORDER BY importance DESC LIMIT 5",
                    (f"%{query[:50]}%", *[str(s) for s in allowed_scopes]),
                )
            else:
                cursor = self._memory_db.execute(
                    "SELECT content, category, importance FROM memories "
                    "WHERE content LIKE ? ORDER BY importance DESC LIMIT 5",
                    (f"%{query[:50]}%",),
                )
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            return []

    def _save_memory(
        self, user_text: str, response: str, scope: str = "shared"
    ) -> None:
        """Salva interacao na memoria local e knowledge graph."""
        if not self._memory_db:
            return
        scope = str(scope or "shared")
        try:
            mem_id = str(uuid.uuid4())[:8]
            now = datetime.now(UTC).isoformat()
            try:
                self._memory_db.execute(
                    "INSERT INTO memories (id, content, category, importance, created_at, scope) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (mem_id, f"User: {user_text}\nA.R.I.S.: {response}", "conversation", 5, now, scope),
                )
            except Exception:
                # DB antigo sem coluna scope (migração falhou): fallback legado
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
