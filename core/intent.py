"""Sistema de Interpretação de Intenção do J.A.R.V.I.S. NEXUS.

Analisa a mensagem do operador e extrai intenções para executar módulos.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Intent:
    """Uma intenção extraída da mensagem."""
    module: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


class IntentAnalyzer:
    """Analisador de intenções do operador.

    Mapeia capacidades dos módulos e permite que a IA
    retorne ações estruturadas para execução.
    """

    def __init__(self) -> None:
        self._modules: dict[str, dict] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Registra módulos padrão do sistema."""
        self.register_module(
            name="weather",
            description="Previsão do tempo e clima",
            triggers=["clima", "tempo", "temperatura", "chuva", "frio", "calor",
                       "umidade", "vento", "previsão", "weather", "chover",
                       "guarda-chuva", "sol", "nublado", "ensolarado"],
            params=["city"],
        )
        self.register_module(
            name="websearch",
            description="Pesquisa na web",
            triggers=["pesquisar", "buscar", "procurar", "search", "google",
                       "pesquisa", "encontrar", "saber sobre", "o que é",
                       "como funciona", "quem é", "notícias"],
            params=["query"],
        )
        self.register_module(
            name="sys",
            description="Análise do sistema",
            triggers=["sistema", "computador", "cpu", "ram", "memória",
                       "disco", "processo", "lento", " travando",
                       "diagnóstico", "análise", "desempenho"],
            params=[],
        )
        self.register_module(
            name="hud",
            description="Painel de controle",
            triggers=["painel", "dashboard", "hud", "centro de controle",
                       "visão geral", "status geral"],
            params=[],
        )
        self.register_module(
            name="remember",
            description="Salvar informação",
            triggers=["lembrar", "salvar", "anotar", "registrar",
                       "guardar", "memorizar"],
            params=["text"],
        )
        self.register_module(
            name="search",
            description="Buscar memória",
            triggers=["buscar memória", "procurar memória", "o que eu disse",
                       "lembra que", "falei sobre"],
            params=["query"],
        )
        self.register_module(
            name="config",
            description="Configurações",
            triggers=["configurar", "configurações", "settings", "ajustes",
                       "preferências", "mudar modelo", "mudar voz"],
            params=[],
        )

    def register_module(
        self,
        name: str,
        description: str,
        triggers: list[str],
        params: list[str] | None = None,
    ) -> None:
        """Registra um módulo com suas capacidades.

        Args:
            name: Nome do módulo/comando.
            description: Descrição do que faz.
            triggers: Palavras/frases que ativam este módulo.
            params: Parâmetros que o módulo aceita.
        """
        self._modules[name] = {
            "description": description,
            "triggers": triggers,
            "params": params or [],
        }

    def get_modules_description(self) -> str:
        """Retorna descrição dos módulos para o system prompt.

        Returns:
            String com módulos disponíveis.
        """
        lines = ["Módulos disponíveis e seus gatilhos:"]
        for name, info in self._modules.items():
            triggers = ", ".join(info["triggers"][:5])
            lines.append(f"- {name}: {info['description']} (gatilhos: {triggers})")
        return "\n".join(lines)

    def parse_ai_response(self, response: str) -> tuple[str, list[Intent]]:
        """Analisa a resposta da IA e extrai ações a executar.

        Procura por blocos JSON na resposta da IA que especificam
        ações a serem executadas.

        Args:
            response: Resposta completa da IA.

        Returns:
            Tupla (resposta_limpa, lista_de_intenções).
        """
        intents: list[Intent] = []
        clean_response = response

        # Procurar por blocos de ação: <<<ACTION>>>{"module": "...", ...}<<<END>>>
        action_pattern = r"<<<ACTION>>>(.*?)<<<END>>>"
        matches = re.findall(action_pattern, response, re.DOTALL)

        for match in matches:
            try:
                action_data = json.loads(match.strip())
                intent = Intent(
                    module=action_data.get("module", ""),
                    action=action_data.get("action", "execute"),
                    params=action_data.get("params", {}),
                    confidence=action_data.get("confidence", 1.0),
                )
                intents.append(intent)
            except json.JSONDecodeError:
                continue

        # Remover blocos de ação da resposta limpa
        clean_response = re.sub(action_pattern, "", response, flags=re.DOTALL).strip()

        return clean_response, intents

    def build_intent_prompt(self, user_message: str) -> str:
        """Constrói prompt para a IA analisar a intenção.

        Args:
            user_message: Mensagem do operador.

        Returns:
            Prompt formatado.
        """
        modules_desc = self.get_modules_description()

        return f"""Analise a mensagem do operador e extraia as intenções.

Mensagem do operador: "{user_message}"

{modules_desc}

Responda SEMPRE com:
1. Sua resposta natural ao operador (em português, formato markdown)
2. SE houver ações a executar, adicione blocos de ação no final

Formato dos blocos de ação (use APENAS se precisar executar algo):
<<<ACTION>>>{{"module": "nome_do_modulo", "action": "execute", "params": {{"parametro": "valor"}}, "confidence": 0.95}}<<<END>>>

Exemplos:
- Se o operador pergunta sobre clima: responda naturalmente e adicione:
<<<ACTION>>>{{"module": "weather", "action": "execute", "params": {{"city": "cidade_detectada"}}, "confidence": 0.95}}<<<END>>>

- Se o operador quer pesquisar algo: responda naturalmente e adicione:
<<<ACTION>>>{{"module": "websearch", "action": "execute", "params": {{"query": "termo de pesquisa"}}, "confidence": 0.95}}<<<END>>>

- Se o operador quer ver o sistema: responda naturalmente e adicione:
<<<ACTION>>>{{"module": "sys", "action": "execute", "params": {{}}, "confidence": 0.95}}<<<END>>>

- Se é apenas uma conversa sem ação: responda naturalmente SEM bloco de ação.

REGRAS:
- NUNCA invente dados. Use as ferramentas quando disponíveis.
- Detecte a cidade corretamente da mensagem.
- Uma mensagem pode ter MÚLTIPLAS ações.
- Se não tem certeza da intenção, responda apenas sem bloco de ação.
- NÃO explique os blocos de ação ao operador. Apenas responda naturalmente."""
