"""Advanced Interpreter - Interpretador Multi-Comando do A.R.I.S.

Interpreta qualquer frase em linguagem natural e extrai múltiplos comandos.
Suporta contexto, referências, condicionais e sequências.
"""

import json
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Intent:
    """Uma intenção extraída da mensagem."""
    module: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    order: int = 0
    conditional: dict | None = None
    context: str | None = None


@dataclass
class ConversationContext:
    """Contexto da conversa para resolução de referências."""
    last_topic: str = ""
    last_action: str = ""
    last_entity: str = ""
    last_music: str = ""
    last_app: str = ""
    pending_actions: list[str] = field(default_factory=list)
    user_preferences: dict[str, Any] = field(default_factory=dict)
    session_goals: list[str] = field(default_factory=list)


class AdvancedInterpreter:
    """Interpretador avançado de linguagem natural.

    Transforma qualquer frase em uma lista estruturada de comandos.
    Usa IA para interpretação profunda com contexto.
    Agora inclui NLU local para deteccao rapida de intencoes.
    """

    def __init__(self, memory_service=None, context_engine=None):
        self._modules: dict[str, dict] = {}
        self._context = ConversationContext()
        self._context_history: deque = deque(maxlen=20)
        self._memory_service = memory_service
        self._context_engine = context_engine
        self._nlu = None  # Lazy load
        self._register_defaults()

    @property
    def nlu(self):
        """Lazy load do NLU engine."""
        if self._nlu is None:
            from core.nlu import NLUEngine
            self._nlu = NLUEngine()
        return self._nlu

    def _register_defaults(self) -> None:
        """Registra todos os módulos disponíveis."""
        modules = {
            "weather": {
                "description": "Previsão do tempo e clima",
                "actions": ["clima", "tempo", "temperatura", "chuva", "previsão"],
                "params": ["city", "action"],
            },
            "websearch": {
                "description": "Pesquisa na web",
                "actions": ["pesquisar", "buscar", "procurar", "google"],
                "params": ["query"],
            },
            "sys": {
                "description": "Análise do sistema (CPU, RAM, disco)",
                "actions": ["sistema", "cpu", "ram", "memória", "diagnóstico"],
                "params": [],
            },
            "desktop": {
                "description": "Controle do desktop: abrir/fechar programas, mouse, teclado, mídia, volume, clipboard, screenshots",
                "actions": ["abrir", "fechar", "mouse", "teclado", "volume", "mídia",
                           "play", "pause", "próxima", "anterior", "screenshot",
                           "clipboard", "minimizar", "maximizar", "focar"],
                "params": ["action", "app", "process", "text", "keys", "x", "y"],
            },
            "scheduler": {
                "description": "Agendamentos, lembretes, pomodoro, timer",
                "actions": ["lembrete", "agendar", "pomodoro", "timer", "cronômetro"],
                "params": ["action", "title", "when", "minutes"],
            },
            "notify": {
                "description": "Notificações Windows",
                "actions": ["notificação", "aviso", "alerta", "toast"],
                "params": ["title", "message"],
            },
            "context": {
                "description": "Detectar contexto/atividade atual do usuário",
                "actions": ["contexto", "atividade", "o que estou fazendo"],
                "params": [],
            },
            "safety": {
                "description": "Segurança e permissões",
                "actions": ["segurança", "permissões"],
                "params": [],
            },
            "entertainment": {
                "description": "Entretenimento: piadas, curiosidades, jogos, música",
                "actions": ["piada", "piadas", "curiosidade", "dado", "moeda",
                           "bola 8", "jogo", "música", "tocar", "reproduzir"],
                "params": ["action", "genre", "query"],
            },
            "turbo": {
                "description": "Análise profunda de arquivos e código",
                "actions": ["analisar", "code review", "turbo", "revisão"],
                "params": ["action", "path"],
            },
            "knowledge": {
                "description": "Grafo de conhecimento: entidades, fatos, relacionamentos",
                "actions": ["entidade", "fato", "relacionamento", "grafo"],
                "params": ["action", "name", "type", "content", "query"],
            },
            "awareness": {
                "description": "Desktop awareness: captura de tela, análise da tela, OCR, monitoramento",
                "actions": ["tela", "captura", "ocr", "screenshot", "analisar", "monitorar"],
                "params": ["action", "query", "interval"],
            },
            "vision": {
                "description": "Vision Engine: visão computacional — analisa a tela (OCR via Tesseract + modelo de visão Ollama/Gemini), encontra texto na tela, detecta erros, descreve a imagem",
                "actions": ["veja a tela", "analise a tela", "leia a tela", "descreva a tela", "encontre erro na tela", "procure por", "o que está aparecendo", "câmera disponível"],
                "params": ["action", "query", "question"],
            },
            "matrix": {
                "description": (
                    "Matriz de LED 8x8 (ESP32 + MAX7219): mostra texto rolante, "
                    "número ou estado facial. Estados aceitos: idle, listen, think, "
                    "speak, happy (não invente outros)."
                ),
                "actions": ["mostrar", "exibir", "estado", "texto", "número"],
                "params": ["action", "content", "state", "text", "number"],
            },
            "browser": {
                "description": "Automação de navegador web",
                "actions": ["navegar", "browser", "site", "página"],
                "params": ["action", "url", "query"],
            },
            "agents": {
                "description": "Multi-agente e delegação de tarefas",
                "actions": ["delegar", "agente", "orquestrar"],
                "params": ["action", "description"],
            },
            "skills": {
                "description": "Sistema de skills e habilidades",
                "actions": ["skill", "habilidade"],
                "params": ["action", "query", "name"],
            },
            "dictation": {
                "description": "Modo dictação: falar e digitar",
                "actions": ["dictação", "ditado", "transcrever"],
                "params": ["action", "key", "lang"],
            },
            "redact": {
                "description": "Auto-redação de dados sensíveis",
                "actions": ["redigir", "privacidade"],
                "params": ["action", "text"],
            },
            "digest": {
                "description": "Briefing diário automatizado",
                "actions": ["briefing", "bom dia", "resumo"],
                "params": ["action"],
            },
            "gmail": {
                "description": (
                    "Gmail: ler, listar, buscar e-mails. "
                    "Ações: list (listar não lidos), read (ler msg específica), search (buscar), "
                    "mark_read (marcar como lido), mark_unread (marcar como não lido), "
                    "trash (mover pra lixeira — REQUER message_id, NUNCA use 'all'), "
                    "untrash (restaurar da lixeira)"
                ),
                "actions": [
                    "list", "read", "search",
                    "mark_read", "mark_unread",
                    "trash", "untrash",
                ],
                "params": ["action", "query", "message_id", "max_results"],
            },
            "remember": {
                "description": "Salvar informação na memória",
                "actions": ["lembrar", "salvar", "anotar", "memorizar"],
                "params": ["text"],
            },
            "search": {
                "description": "Buscar memória salva",
                "actions": ["buscar memória", "procurar memória", "o que eu disse"],
                "params": ["query"],
            },
            "config": {
                "description": "Configurações do sistema",
                "actions": ["configurar", "configurações", "settings"],
                "params": [],
            },
        }
        self._modules = modules

    def get_modules_for_prompt(self) -> str:
        """Gera descrição dos módulos para o prompt da IA."""
        lines = []
        for name, info in self._modules.items():
            actions = ", ".join(info["actions"][:6])
            lines.append(f"- {name}: {info['description']} | ações: {actions}")
        return "\n".join(lines)

    def update_context(self, user_message: str, response: str = "", intents: list = None) -> None:
        """Atualiza o contexto da conversa."""
        msg_lower = user_message.lower()

        # Detectar tópico
        if any(w in msg_lower for w in ["música", "música", "tocar", "spotify", "youtube music"]):
            self._context.last_topic = "musica"
        elif any(w in msg_lower for w in ["jogo", "jogar", "minecraft", "steam"]):
            self._context.last_topic = "jogo"
        elif any(w in msg_lower for w in ["código", "programar", "projeto", "editor"]):
            self._context.last_topic = "codigo"
        elif any(w in msg_lower for w in ["luz", "luzes", "iluminação"]):
            self._context.last_topic = "luzes"
        elif any(w in msg_lower for w in ["discord", "chat", "conversa"]):
            self._context.last_topic = "comunicacao"
        elif any(w in msg_lower for w in [
            "atualizar", "evoluir", "melhorar", "capacidade", "funcionalidade",
            "ideias", "sugestão", "plano", "próximo", "futuro",
            "o que você faz", "o que voce faz", "quem é", "quem voce",
        ]):
            self._context.last_topic = "projeto_evolution"
        elif any(w in msg_lower for w in ["e-mail", "email", "gmail", "inbox", "mensagem"]):
            self._context.last_topic = "email"
        elif any(w in msg_lower for w in ["tela", "visão", "vision", "ocr", "camera"]):
            self._context.last_topic = "visao"

        # Detectar app mencionado
        apps = ["discord", "spotify", "youtube", "navegador", "chrome", "firefox",
                "vscode", "editor", "terminal", "explorer", "notepad"]
        for app in apps:
            if app in msg_lower:
                self._context.last_app = app
                break

        # Salvar no histórico
        self._context_history.append({
            "timestamp": datetime.now().isoformat(),
            "message": user_message,
            "response": response[:200],
            "context": {
                "topic": self._context.last_topic,
                "app": self._context.last_app,
            }
        })

    def resolve_references(self, text: str) -> str:
        """Resolve referências como 'essa', 'aquilo', 'o mesmo'."""
        result = text

        # Referências a música
        if self._context.last_music:
            result = result.replace("essa música", f"a música {self._context.last_music}")
            result = result.replace("a mesma", f"a música {self._context.last_music}")

        # Referências a app
        if self._context.last_app:
            result = result.replace("ele", f"{self._context.last_app}")
            result = result.replace("ela", f"{self._context.last_app}")

        return result

    @staticmethod
    def _sanitize_prompt_input(text: str) -> str:
        """Sanitiza input do usuário para prevenir prompt injection.

        Remove/escapa sequências que podem quebrar o formato do prompt
        ou injetar instruções adversariais.
        """
        # Remover tentativas de fechar/reabrir blocos de formato
        text = text.replace("```json", "``` json")
        text = text.replace("```python", "``` python")
        # Escapar aspas que podem quebrar o delimitador do prompt
        text = text.replace('"', '\\"')
        # Remover quebras de linha suspeitas (injeção de seção)
        text = text.replace("\n## ", "\n##\\ ")
        # Limitar tamanho para prevenir abuso
        if len(text) > 2000:
            text = text[:2000] + "...[truncado]"
        return text

    def build_interpretation_prompt(self, user_message: str) -> str:
        """Constrói o prompt para interpretação avançada."""
        modules_desc = self.get_modules_for_prompt()
        context = self._get_context_string(user_message)
        resolved = self.resolve_references(user_message)

        # Sanitizar input do usuário para prevenir prompt injection
        sanitized = self._sanitize_prompt_input(resolved)

        return f"""Analise a mensagem do operador e retorne resposta natural + comandos.

## Contexto
{context}

## Módulos
{modules_desc}

## Mensagem do operador
"{sanitized}"

## O que fazer

1. Interprete a mensagem
2. Extraia TODAS as intenções (podem ser várias)
3. Identifique: conversa vs comando
4. Resolva referências ("essa", "aquilo")
5. Responda naturalmente ao operador

## Formato

### Resposta natural ao operador
(resposta curta e direta, em português)

### Comandos
```json
[
  {{
    "module": "nome",
    "action": "acao",
    "params": {{"parametro": "valor"}},
    "confidence": 0.95,
    "order": 1
  }}
]
```

Se não houver comando, gere só a resposta natural (sem JSON).

## Regras

- MÚLTIPLOS COMANDOS: Uma frase pode ter vários. Extraia TODOS.
- CONVERSA vs COMANDO: "tô indo jogar" é contexto, "abre o discord" é comando.
- REFERÊNCIAS: "essa" = última música. "ele" = último app.
- SEQUÊNCIA: "primeiro X, depois Y" → respeite a ordem.
- CONTEXTO: Use o contexto da conversa anterior.
- NÃO INVENTE: Se não tem certeza, não crie comando.
- CONFIDÊNCIA: 0.0 a 1.0.
- NUNCA crie comandos para módulos que não existem.
- Seja PRECISO nos parâmetros (nome do app, cidade, etc).
- Responda SEMPRE em português.
- NUNCA comece com "Claro!", "Certamente!" ou "Como posso ajudar?".
- NUNCA repita saudações (ex: "Oi! Oi! Oi!" — apenas UMA saudação).
- Se for conversa cumprimento ("oi", "bom dia", "eai"), responda casual.
- Se for pergunta, responda com conteúdo real.
- Se for comando, responda curto e execute."""

    def _get_context_string(self, user_message: str = "") -> str:
        """Gera string de contexto com memórias de longo prazo.

        Usa ContextEngine.build() quando disponível (única fonte de
        memória), senão cai no memory_service direto.
        """
        recent = list(self._context_history)[-3:]

        parts = []
        if self._context.last_topic:
            parts.append(f"Tópico atual: {self._context.last_topic}")
        if self._context.last_app:
            parts.append(f"Último app mencionado: {self._context.last_app}")
        if self._context.last_music:
            parts.append(f"Última música: {self._context.last_music}")
        if self._context.session_goals:
            parts.append(f"Objetivos da sessão: {', '.join(self._context.session_goals[-3:])}")

        if recent:
            parts.append("\nÚltimas interações:")
            for h in recent:
                parts.append(f"  - Operador: \"{h['message'][:80]}\"")
                if h.get("response"):
                    parts.append(f"    A.R.I.S.: \"{h['response'][:150]}\"")

        # Memórias de longo prazo + estado NeuralCore via ContextEngine
        memories = []
        neural_state_parts = []
        if self._context_engine and user_message:
            try:
                bundle = self._context_engine.build(user_input=user_message)
                memories = bundle.long_term_memories
                if bundle.current_goal:
                    neural_state_parts.append(f"Objetivo NeuralCore: {bundle.current_goal}")
                if bundle.current_mode:
                    neural_state_parts.append(f"Modo: {bundle.current_mode}")
                if bundle.current_task and bundle.current_task.get("intent"):
                    neural_state_parts.append(f"Intenção em curso: {bundle.current_task['intent']}")
                if bundle.notes:
                    notes_str = ", ".join(f"{k}={v}" for k, v in bundle.notes.items() if v)
                    if notes_str:
                        neural_state_parts.append(f"Notas: {notes_str}")
            except Exception:
                memories = []
        elif self._memory_service and user_message:
            try:
                memories = self._memory_service.retrieve(user_message, limit=5)
            except Exception:
                memories = []

        if neural_state_parts:
            parts.append("\nEstado NeuralCore:")
            for p in neural_state_parts:
                parts.append(f"  {p}")

        if memories:
            parts.append("\nMemórias relevantes:")
            for m in memories[:5]:
                title = m.get("title", "")
                content = str(m.get("content", ""))[:160]
                parts.append(f"  - {title}: {content}")

        if not parts:
            return "Nenhum contexto anterior ainda (primeira interação)."
        return "\n".join(parts)

    def parse_ai_response(self, response: str) -> tuple[str, list[Intent]]:
        """Analisa a resposta da IA e extrai comandos.

        Suporta dois formatos:
        1. <<<ACTION>>>...<<<END>>> (legado)
        2. ```json [...] ``` (novo formato avançado)
        """
        intents: list[Intent] = []
        clean_response = response

        # ── Formato novo: ```json [...] ``` ─────────────────
        json_block_pattern = r'```json\s*\n?(.*?)\n?\s*```'
        json_matches = re.findall(json_block_pattern, response, re.DOTALL)

        for match in json_matches:
            try:
                data = json.loads(match.strip())
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "module" in item:
                            intent = Intent(
                                module=item.get("module", ""),
                                action=item.get("action", "execute"),
                                params=item.get("params", {}),
                                confidence=item.get("confidence", 0.8),
                                order=item.get("order", 0),
                                conditional=item.get("conditional"),
                                context=item.get("context"),
                            )
                            intents.append(intent)
            except json.JSONDecodeError:
                continue

        # Remover blocos json da resposta
        clean_response = re.sub(json_block_pattern, "", response, flags=re.DOTALL).strip()

        # ── Formato legado: <<<ACTION>>>...<<<END>>> ───────
        action_pattern = r"<<<ACTION>>>(.*?)<<<END>>>"
        legacy_matches = re.findall(action_pattern, clean_response, re.DOTALL)

        for match in legacy_matches:
            try:
                action_data = json.loads(match.strip())
                intent = Intent(
                    module=action_data.get("module", ""),
                    action=action_data.get("action", "execute"),
                    params=action_data.get("params", {}),
                    confidence=action_data.get("confidence", 1.0),
                    order=len(intents) + 1,
                )
                intents.append(intent)
            except json.JSONDecodeError:
                continue

        clean_response = re.sub(action_pattern, "", clean_response, flags=re.DOTALL).strip()

        # ── Limpar marcadores de seção ─────────────────────
        clean_response = re.sub(r'###\s*Resposta natural ao operador\s*', '', clean_response)
        clean_response = re.sub(r'###\s*Comandos\s*', '', clean_response)
        clean_response = re.sub(r'```json\s*', '', clean_response)
        clean_response = re.sub(r'```\s*', '', clean_response)

        # Remover blocos JSON soltos (sem ```)
        json_block_pattern_standalone = r'\{\s*"module"\s*:.*?\}'
        clean_response = re.sub(json_block_pattern_standalone, '', clean_response, flags=re.DOTALL)

        clean_response = clean_response.strip()

        # Ordenar por order
        intents.sort(key=lambda i: i.order)

        # Atualizar contexto
        self.update_context(
            user_message="",
            intents=intents,
        )

        return clean_response, intents

    def get_context(self) -> ConversationContext:
        """Retorna o contexto atual."""
        return self._context

    def set_context_value(self, key: str, value: Any) -> None:
        """Define um valor no contexto."""
        if hasattr(self._context, key):
            setattr(self._context, key, value)

    def get_stats(self) -> dict:
        """Retorna estatísticas do interpretador."""
        return {
            "modules": len(self._modules),
            "context_topic": self._context.last_topic,
            "context_app": self._context.last_app,
            "interactions": len(self._context_history),
        }

    def try_nlu_fast_path(self, user_message: str) -> tuple[str, list[Intent]] | None:
        """Tenta resolver via NLU local antes de chamar LLM.

        Returns:
            (response_text, intents) se confidence >= threshold.
            None se precisa de LLM.
        """
        from core.nlu import IntentType, _QUESTION_PATTERNS
        import re

        # Primeiro: verificar se é conversa casual/pergunta (não ação)
        # Se for, NÃO roteia para ação — retorna resposta conversacional direta
        is_question = False
        for pattern in _QUESTION_PATTERNS:
            if re.search(pattern, user_message, re.IGNORECASE):
                is_question = True
                break

        if is_question:
            # É pergunta/conversa casual — não criar intenção de ação
            # Retornar resposta conversacional simples
            return self._generate_conversational_response(user_message), []

        result = self.nlu.detect(user_message)

        if self.nlu.should_use_llm(result):
            return None

        # Mapear IntentType pra modulo/acao do sistema
        intent_map = {
            IntentType.SEARCH: ("websearch", "search"),
            IntentType.RESEARCH: ("intel_research", "execute"),
            IntentType.VERIFY: ("intel_verify", "execute"),
            IntentType.COMPARE: ("intel_compare", "execute"),
            IntentType.LATEST: ("intel_latest", "execute"),
            IntentType.WEATHER: ("weather", "execute"),
            IntentType.EMAIL: ("gmail", "list"),
            IntentType.SYSTEM: ("sys", "status"),
            IntentType.EXPLAIN: ("websearch", "search"),
            IntentType.SUMMARIZE: ("websearch", "search"),
            IntentType.CALC: ("sys", "calc"),
            IntentType.TRANSLATE: ("websearch", "search"),
        }

        mapping = intent_map.get(result.intent)
        if mapping is None:
            return None

        module, action = mapping
        params = dict(result.params)

        # Adaptar params pro formato esperado
        if result.intent == IntentType.SEARCH and "query" in params:
            params["query"] = params["query"]
        elif result.intent == IntentType.WEATHER and "city" in params:
            params["city"] = params["city"]
        elif result.intent == IntentType.COMPARE and "items" in params:
            items = params.pop("items")
            if len(items) >= 2:
                params["item_a"] = items[0]
                params["item_b"] = items[1]

        intent = Intent(
            module=module,
            action=action,
            params=params,
            confidence=result.confidence,
            order=1,
        )

        response = self._generate_nlu_response(result)
        return response, [intent]

    def _generate_conversational_response(self, user_message: str) -> str:
        """Gera resposta conversacional para perguntas/saudacoes casuais."""
        msg = user_message.lower().strip()

        import re
        # Saudações
        if re.match(r"^(?:oi|ola|eai|fala|bom\s*dia|boa\s*tarde|boa\s*noite|hey|hello|hi|salve)\b", msg):
            from datetime import datetime
            hour = datetime.now().hour
            if hour < 12:
                return "Bom dia! Como posso ajudar?"
            elif hour < 18:
                return "Boa tarde! Em que posso ser útil?"
            return "Boa noite! Tudo bem?"

        # Agradecimentos
        if re.match(r"^(?:obrigad[oa]|valeu|thanks|vlw|brigad)", msg):
            return "De nada! Sempre que precisar, é só chamar."

        # Perguntas sobre status/funcionamento
        if re.match(r"^(?:como\s+(?:vc|voce|ta|esta|vai)|tudo\s+(?:bem|certa|ok|beleza))", msg):
            return "Tudo bem por aqui! A ARIS está no ar e pronta pra ajudar."

        # Perguntas sobre identidade
        if re.match(r"^(?:vc|voce)\s+(?:e|eh|é)\s+(?:uma?|o)\s+.+", msg):
            return "Sou a A.R.I.S., sua assistente virtual! Posso ajudar com muitas coisas."

        # Perguntas gericas
        if re.match(r"^(?:quanto|qual|onde|como|por\s*que|porque|quem|quando|o\s*que|que)\b", msg):
            return "Essa é uma boa pergunta. Quer que eu pesquise pra você?"

        # Resposta padrão para conversa casual
        return "Entendi. Em que mais posso ajudar?"

    def _generate_nlu_response(self, result) -> str:
        """Gera resposta curta pra NLU fast path."""
        from core.nlu import IntentType
        responses = {
            IntentType.SEARCH: "Vou pesquisar isso pra voce.",
            IntentType.RESEARCH: "Vou fazer uma pesquisa aprofundada.",
            IntentType.VERIFY: "Vou verificar essa informacao.",
            IntentType.COMPARE: "Vou comparar pra voce.",
            IntentType.LATEST: "Vou buscar as ultimas noticias.",
            IntentType.WEATHER: "Vou consultar o tempo.",
            IntentType.EMAIL: "Vou checar seus emails.",
            IntentType.SYSTEM: "Vou verificar o sistema.",
            IntentType.EXPLAIN: "Vou explicar isso.",
            IntentType.SUMMARIZE: "Vou resumir pra voce.",
            IntentType.CALC: "Vou calcular isso.",
            IntentType.TRANSLATE: "Vou traduzir isso.",
        }
        return responses.get(result.intent, "Entendi, vou processar.")

    def handle_pc_status_feedback(self, user_message: str) -> tuple[str, list[Intent]] | None:
        """Processa feedback do usuario sobre status do PC.
        
        Detecta frases como "o PC está ligado", "o PC está desligado", etc.
        e aplica override no ModeManager.
        """
        import re
        msg = user_message.lower().strip()
        
        # Detectar afirmação explícita sobre estado do PC
        pc_online_patterns = [
            r"(?:o\s+)?pc\s+(?:ta|esta|eh|e)\s+ligado",
            r"(?:o\s+)?pc\s+(?:ta|esta|eh|e)\s+online",
            r"(?:o\s+)?computador\s+(?:ta|esta|eh|e)\s+ligado",
            r"(?:o\s+)?computador\s+(?:ta|esta|eh|e)\s+online",
            r"o\s+pc\s+esta\s+ligado",
            r"pc\s+ligado",
        ]
        
        pc_offline_patterns = [
            r"(?:o\s+)?pc\s+(?:ta|esta|eh|e)\s+desligado",
            r"(?:o\s+)?pc\s+(?:ta|esta|eh|e)\s+offline",
            r"(?:o\s+)?computador\s+(?:ta|esta|eh|e)\s+desligado",
            r"(?:o\s+)?computador\s+(?:ta|esta|eh|e)\s+offline",
            r"o\s+pc\s+esta\s+desligado",
            r"pc\s+desligado",
        ]
        
        for pattern in pc_online_patterns:
            if re.search(pattern, msg):
                return ("Entendido — vou atualizar o modo para PRIMARY (PC online).", [])
        
        for pattern in pc_offline_patterns:
            if re.search(pattern, msg):
                return ("Entendido — vou atualizar o modo para EDGE (PC offline).", [])
        
        return None
