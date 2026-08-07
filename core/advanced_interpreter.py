"""Advanced Interpreter - Interpretador Multi-Comando do J.A.R.V.I.S.

Interpreta qualquer frase em linguagem natural e extrai múltiplos comandos.
Suporta contexto, referências, condicionais e sequências.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional
from collections import deque
from datetime import datetime


@dataclass
class Intent:
    """Uma intenção extraída da mensagem."""
    module: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    order: int = 0
    conditional: Optional[dict] = None
    context: Optional[str] = None


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
    """

    def __init__(self):
        self._modules: dict[str, dict] = {}
        self._context = ConversationContext()
        self._context_history: deque = deque(maxlen=20)
        self._register_defaults()

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
                "description": "Desktop awareness: captura de tela, OCR, monitoramento",
                "actions": ["tela", "captura", "ocr", "screenshot", "monitorar"],
                "params": ["action", "query", "interval"],
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

    def build_interpretation_prompt(self, user_message: str) -> str:
        """Constrói o prompt para interpretação avançada."""
        modules_desc = self.get_modules_for_prompt()
        context = self._get_context_string()
        resolved = self.resolve_references(user_message)

        return f"""Você é o cérebro do J.A.R.V.I.S., um assistente avançado.

SUA MISSÃO: Interpretar QUALQUER frase do operador e transformar em comandos estruturados.

## CONTEXTO DA CONVERSA ATUAL
{context}

## MÓDULOS DISPONÍVEIS
{modules_desc}

## MENSAGEM DO OPERADOR
"{resolved}"

## SUA TAREFA

1. **Interprete** a mensagem como um humano inteligente faria
2. **Extraia TODAS** as intenções (podem ser várias)
3. **Identifique** conversa vs comandos
4. **Resolva** referências ("essa", "aquilo", "o mesmo")
5. **Detecte** condicionais ("se... então...")
6. **Ordene** na sequência lógica (primeiro X, depois Y)
7. **Responda** naturalmente ao operador

## FORMATO DE SAÍDA

Responda SEMPRE neste formato exato:

### Resposta natural ao operador
(Responda em português, como o J.A.R.V.I.S. falaria)

### Comandos
```json
[
  {{
    "module": "nome_do_modulo",
    "action": "acao",
    "params": {{"parametro": "valor"}},
    "confidence": 0.95,
    "order": 1
  }}
]
```

## REGRAS CRÍTICAS

- **MÚLTIPLOS COMANDOS**: Uma frase pode ter 1, 2, 5, 10 comandos. Extraia TODOS.
- **CONVERSA vs COMANDO**: "tô indo jogar" é contexto, "abre o discord" é comando.
- **REFERÊNCIAS**: "essa" = última música mencionada. "ele" = último app mencionado.
- **CONDICIONAIS**: "se tiver erro, me avisa" → criar ação condicional.
- **SEQUÊNCIA**: "primeiro X, depois Y" → respeite a ordem.
- **PREFERÊNCIAS**: "música calma" → parâmetro genre=calma.
- **CONTEXTO**: Use o contexto da conversa para interpretar melhor.
- **NÃO INVENTE**: Se não tem certeza, não crie o comando.
- **CONFIDÊNCIA**: 0.0 a 1.0. Se tem certeza = 0.95. Se improvável = 0.3.

## EXEMPLOS DE INTERPRETAÇÃO

### Exemplo 1: Múltiplos comandos simples
Operador: "Abre o Discord e coloca uma música no Spotify"
```json
[
  {{"module": "desktop", "action": "open_app", "params": {{"app": "discord"}}, "confidence": 0.95, "order": 1}},
  {{"module": "entertainment", "action": "tocar_musica", "params": {{"app": "spotify"}}, "confidence": 0.90, "order": 2}}
]
```

### Exemplo 2: Comando condicional
Operador: "Se o servidor estiver desligado, inicia ele"
```json
[
  {{"module": "sys", "action": "check_server", "params": {{"condition": "if_stopped"}}, "confidence": 0.85, "order": 1, "conditional": {{"type": "if", "check": "server_stopped", "then": "start_server"}}}}
]
```

### Exemplo 3: Contexto + referência
Operador: "Essa ficou boa. Salva aí."
```json
[
  {{"module": "entertainment", "action": "salvar", "params": {{"reference": "last_music"}}, "confidence": 0.80, "order": 1}}
]
```

### Exemplo 4: Sequência longa
Operador: "Fecha o jogo, abre o código e ativa a escuta"
```json
[
  {{"module": "desktop", "action": "close_app", "params": {{"app": "last_game"}}, "confidence": 0.90, "order": 1}},
  {{"module": "desktop", "action": "open_app", "params": {{"app": "editor"}}, "confidence": 0.90, "order": 2}},
  {{"module": "dictation", "action": "start", "params": {{}}, "confidence": 0.95, "order": 3}}
]
```

### Exemplo 5: Frase natural com contexto
Operador: "Tô indo jogar, fecha essas coisas e deixa só o Discord"
```json
[
  {{"module": "desktop", "action": "close_unnecessary", "params": {{"keep": ["discord"]}}, "confidence": 0.85, "order": 1}}
]
```

### Exemplo 6: Comando dentro de outro
Operador: "Abre o navegador e pesquisa previsão do tempo"
```json
[
  {{"module": "desktop", "action": "open_app", "params": {{"app": "navegador"}}, "confidence": 0.95, "order": 1}},
  {{"module": "websearch", "action": "search", "params": {{"query": "previsão do tempo"}}, "confidence": 0.95, "order": 2}}
]
```

### Exemplo 7: Apenas conversa
Operador: "Bom dia, como vai?"
```json
[]
```

IMPORTANTE:
- Seja PRECISO nos parâmetros (nome do app, cidade, etc)
- NUNCA crie comandos para módulos que não existem
- Use a confiança para indicar incerteza
- Mantenha a ordem lógica das ações
- Responda SEMPRE em português"""

    def _get_context_string(self) -> str:
        """Gera string de contexto."""
        if not self._context.last_topic and not self._context.last_app:
            return "Nenhum contexto anterior ainda (primeira interação)."

        parts = []
        if self._context.last_topic:
            parts.append(f"Tópico atual: {self._context.last_topic}")
        if self._context.last_app:
            parts.append(f"Último app mencionado: {self._context.last_app}")
        if self._context.last_music:
            parts.append(f"Última música: {self._context.last_music}")
        if self._context.session_goals:
            parts.append(f"Objetivos da sessão: {', '.join(self._context.session_goals[-3:])}")

        # Últimas 3 interações
        recent = list(self._context_history)[-3:]
        if recent:
            parts.append("\nÚltimas interações:")
            for h in recent:
                parts.append(f"  - Operador: \"{h['message'][:80]}\"")

        return "\n".join(parts) if parts else "Nenhum contexto anterior."

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
