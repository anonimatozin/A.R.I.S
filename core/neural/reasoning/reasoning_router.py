"""Reasoning Router do A.R.I.S.

Decide se uma tarefa precisa de LLM ou pode ser resolvida de forma
determinística:

    "qual uso da CPU?"              → System API (determinístico)
    "abra o navegador"              → intent (determinístico)
    "explique por que PC está lento"→ LLM + informações do sistema
    "investigue e resolva esse problema" → LLM + Planner + Ações

O LLM é usado apenas onde agrega valor. Um motor determinístico cobre
padrões conhecidos de forma confiável e barata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.advanced_interpreter import Intent
from core.neural.events import Event
from utils.logger import Logger


class ReasoningMode(StrEnum):
    DETERMINISTIC = "deterministic"
    LLM = "llm"
    HYBRID = "hybrid"
    LOCAL = "local"


@dataclass
class RoutingDecision:
    """Resultado do roteamento de raciocínio."""
    mode: ReasoningMode
    reason: str
    intents: list[Intent] = field(default_factory=list)

    @property
    def needs_llm(self) -> bool:
        return self.mode in (ReasoningMode.LLM, ReasoningMode.HYBRID)


class DeterministicEngine:
    """Motor determinístico: traduz padrões conhecidos em intenções.

    Barato, previsível e sem LLM. Cobre comandos de alta frequência.
    """

    # (padrões regex, module, action, extra)
    RULES: list[tuple[str, str, str, dict[str, Any]]] = [
        # Matriz de LED 8x8 — pedido explícito do usuário (antes das regras
        # genéricas: quem manda "mostra X na matriz" quer a matriz).
        (
            r"(?i)^\s*(?:ar[ií]s|ariz)?[,!.\s]*"
            r"(?:por\s+favor\s+|pfv\s+|me\s+|pode\s+|quer\s+)?"
            r"(?:mostra|mostre|mostrar|exibe|exiba|exibir|coloca|coloque|"
            r"põe|poe|escreve|escreva|apresenta|apresente|manda?\s+mostrar|"
            r"manda?\s+exibir)"
            r"\s+(?:o\s+|a\s+|um\s+|uma\s+)?(.+?)"
            r"\s+(?:na|no|em|para a|pra a|pro)\s+(?:a\s+)?(?:matriz|matrix|leds?)",
            "matrix", "show", {"content": ""},
        ),
        (
            r"(?i)^\s*(?:matriz|matrix|led)\s*[:=]\s*(.+)",
            "matrix", "show", {"content": ""},
        ),
        (r"(?i)(uso|carga|percentual)\s*(da|de)\s*(cpu)", "sys", "analyze", {}),
        (r"(?i)(cpu|processador)", "sys", "analyze", {}),
        (r"(?i)(ram|uso\s*de\s*memoria|memoria\s*(usada|livre|disponivel|total|em\s*uso)|memoria\s*do\s*sistema)", "sys", "analyze", {}),
        (r"(?i)^\s*(memoria|ram)\s*$", "sys", "analyze", {}),
        (r"(?i)(uso\s*de\s*disco|disco\s*rigido|hd|ssd)", "sys", "analyze", {}),
        (r"(?i)(status|situacao|diagnostico|informacoes|estado)\s*(do|da|de)?\s*(sistema|system|pc|computador|maquina|equipamento)", "sys", "analyze", {}),
        (r"(?i)(clima|previsão|previsao|tempo\s*(em|de|na|no))", "weather", "now", {"city": ""}),
        (r"(?i)temperatura", "weather", "now", {"city": ""}),
        (r"(?i)(liste\s+minhas\s+memorias|listar\s+memorias|minhas\s+memorias|buscar\s+memorias|procure\s+memorias)", "search", "search", {"query": ""}),
        (r"(?i)o\s*que\s+(voce|vc)\s+(sabe|lembra)\s+sobre", "search", "search", {"query": ""}),
        (r"(?i)\b(salve|guarde|memorize|memoriza|anota|registra|guardar)\s+(que|isso|ist.o|o|a)?.?", "remember", "save", {}),
        (r"(?i)(pesquis|busca|procura|google)", "websearch", "search", {"query": ""}),
        (r"(?i)\b(piada|piadinha|charada)\b", "entertainment", "joke", {}),
        (r"(?i)\b(curiosidade|curiosidades)\b", "entertainment", "curiosity", {}),
        (r"(?i)\b(citacao|citação|frase\s+famosa|quote)\b", "entertainment", "quote", {}),
        (r"(?i)(lembrete|lembrar|agenda|pomodoro|timer|cronômetro|cronometro)", "scheduler", "list", {}),
        (r"(?i)(abre|abra|abrir|abriria)\s+(o\s+|a\s+)?(discord|spotify|youtube|chrome|firefox|notepad|bloco\s*de\s*notas|calculadora|navegador|explorer)", "desktop", "open_app", {"app": ""}),
        (r"(?i)^contexto$|^o\s*que\s*estou\s*fazendo$", "context", "detect", {}),
        (r"(?i)^status\s*(do|da)\s*(hardware|esp32)$", "hardware", "status", {}),
        (r"(?i)(?:o\s*que|oque)\s+(?:voce|vc)\s+est[áa]\s+vendo", "vision", "analyze", {}),
        (r"(?i)\b(?:veja|ver|olhe|olha)\b\s+o\s+que\s+est[áa]\s+acontecendo", "vision", "analyze", {}),
        (r"(?i)(encontre|encontrar|acha|ache|detecta|detecte|procure|procura|procuro).{0,25}\berro", "vision", "errors", {}),
        (r"(?i)\bprocur[ae]\b\s+por\s+(.+?)(?:\s+(?:em|na|nessa)\s+tela|$)", "vision", "find", {"query": ""}),
        (r"(?i)leia\s+o\s+que\s+est[áa]\s+aparecendo", "vision", "read", {}),
        (r"(?i)(o\s*que|oque).{0,30}\b(percebendo|percebe|vendo|ouvindo|observando|notando)\b", "perception", "status", {}),
        (r"(?i)^\s*percep[çc][ãa]o\s*$", "perception", "status", {}),
        (r"(?i)(quais.{0,20}\bsensores\b|sensores\s+(ativos|dispon[ií]veis|conectados|do\s+sistema|no\s+sistema))", "perception", "sensors", {}),
        (r"(?i)(o\s*que|oque)\s+(chamou|atraiu|mereceu).{0,20}(aten[çc][ãa]o)", "perception", "attention", {}),
        (r"(?i)(c[âa]mera|camera).{0,25}(dispon[ií]vel|funcionando|ativad|ligad|conectad|est[áa])", "perception", "camera", {}),
        (r"(?i)(ative|desative|ligue|desligue|habilite|desabilite|ativa|desativa)\s+(a\s+)?(percep[çc][ãa]o|sensores)", "perception", "toggle", {}),
        (r"(?i)(analis|analiz|veja|ver\b|olha|leia|ler|descreva|examine|observ)\w*\s+(?:a\s+|minha\s+)?tela", "vision", "analyze", {}),
        (r"(?i)(?:o\s*que|oque)\s*(?:tem|aparece|est[áa]\s+(?:aberto|aparecendo|acontecendo))\w*\s+(?:na|em)\s+tela", "vision", "analyze", {}),
        (r"(?i)(captur|captar|print|screenshot|fotograf)\w*\s+(?:a\s+|da\s+|de\s+)?tela|screenshot", "awareness", "capture", {}),
        # Gmail — regras específicas ANTES da genérica
        (r"(?i)(leia|ler|read)\w*\s+(?:o\s+)?(?:e[- ]?mail|mensagem|email)", "gmail", "read", {}),
        (r"(?i)(busqu|busc|search|procur|pesquis)\w*\s+.{0,10}(e[- ]?mail|mensagem|email|gmail|do\s|da\s|de\s)", "gmail", "search", {}),
        (r"(?i)(apag|delet|remov|exclu|lixeira|trash)\w*.{0,5}(todos?|todas?|all)\w*.{0,10}(e[- ]?mail|mensagem|email|gmail)", "gmail", "trash", {"bulk": True}),
        (r"(?i)(apag|delet|remov|exclu|lixeira|trash)\w*.{0,15}(e[- ]?mail|mensagem|email|gmail)", "gmail", "trash", {}),
        (r"(?i)(restaur|untrash|recuper)\w*.{0,10}(e[- ]?mail|mensagem|email|gmail)", "gmail", "untrash", {}),
        (r"(?i)(marqu|marc|mark)\w*.{0,10}(lido|read|como lido)", "gmail", "mark_read", {}),
        (r"(?i)(marqu|marc|mark)\w*.{0,10}(não lido|nao lido|unread)", "gmail", "mark_unread", {}),
        (r"(?i)(bloque|block|imped|não receb|nao receb)\w*.{0,10}(e[- ]?mail|mensagem|remetente|email|gmail)", "gmail", "block_sender", {}),
        # Gmail — regra genérica (depois das específicas)
        (r"(?i)\b(gmail|e[- ]?mail|caixa\s*(de\s*)?entrada|inbox|mensagem|mensagens|email)\b", "gmail", "list", {}),
    ]

    # App canonicalização
    APPS = {
        "discord": "discord", "spotify": "spotify", "youtube": "youtube",
        "chrome": "chrome", "firefox": "firefox", "notepad": "notepad",
        "bloco de notas": "notepad", "bloco": "notepad",
        "calculadora": "calculator", "navegador": "chrome",
        "explorer": "windows explorer",
    }

    def __init__(self, logger: Logger | None = None) -> None:
        self._logger = logger

    def parse(self, query: str) -> list[Intent]:
        """Tenta interpretar a consulta de forma determinística."""
        for pattern, module, action, extra in self.RULES:
            match = re.search(pattern, query)
            if not match:
                continue

            params = dict(extra)
            # Completar parâmetros básicos extraídos do texto
            if action == "now" and "city" in params:
                words = query.replace(match.group(0), " ").strip()
                # Cidade = resto do texto significativo
                candidate = re.sub(r"[^\wÀ-ú ]", "", words).strip()
                if candidate and len(candidate) <= 40:
                    params["city"] = candidate
                else:
                    params.pop("city")
            elif action == "search":
                words = query.replace(match.group(0), " ").strip()
                # "sabe sobre mim/voce/eu..." -> listar tudo (query vazia)
                noise = {"mim", "voce", "vc", "eu", "de", "me", "sobre", "minha", "minhas"}
                if not words or all(w in noise for w in words.split()):
                    params["query"] = ""
                else:
                    params["query"] = words or params["query"]
            elif action == "save" and module == "remember":
                params["text"] = query.replace(match.group(0), " ").strip()
            elif action == "open_app":
                app = match.group(0).lower()
                for name, canonical in self.APPS.items():
                    if name in app:
                        params["app"] = canonical
                        break
            elif action == "toggle":
                params["target"] = (
                    "off" if re.search(r"(?i)(desative|desligue|desabilite|desativa|desliga)", query)
                    else "on"
                )
            elif action == "find" and module == "vision":
                params["query"] = (match.group(1) or "").strip() if match.groups() else ""
            elif action == "show" and module == "matrix":
                params["content"] = (match.group(1) or "").strip()

            intent = Intent(module=module, action=action, params=params, confidence=0.9)
            if self._logger:
                self._logger.debug(f"DeterministicEngine: {query!r} → {module}/{action}")
            return [intent]

        return []

    def can_handle(self, query: str) -> bool:
        """Indica se o motor determinístico cobre a consulta."""
        return bool(self.parse(query))


class ReasoningRouter:
    """Roteador de raciocínio: determinístico ou LLM."""

    def __init__(
        self,
        command_registry=None,
        logger: Logger | None = None,
        deterministic: DeterministicEngine | None = None,
    ) -> None:
        self._registry = command_registry
        self._logger = logger
        self._deterministic = deterministic or DeterministicEngine(logger=logger)

    def route(self, query: str, event: Event | None = None) -> RoutingDecision:
        """Roteia uma consulta para o motor adequado.

        Estratégia:
            1. Intento direto (comando do registry presente).
            2. Padrão determinístico conhecido.
            3. Senão, LLM.
            4. Texto conversacional curto → LOCAL (sem LLM).
        """
        q = query.strip().lower()

        # 1. Intento/ato direto
        if self._registry is not None and self._registry.has_intent(q):
            return RoutingDecision(
                mode=ReasoningMode.DETERMINISTIC,
                reason=f"comando direto '{q}'",
                intents=[Intent(module=q, action="execute", params={}, confidence=1.0)],
            )

        # 4. Conversa genérica → LOCAL (não desperdiçar LLM)
        if len(q.split()) <= 3 and not any(self._deterministic.RULES):
            pass  # continua para determinístico abaixo; fallback LLM se necessário

        # 2. Determinístico
        intents = self._deterministic.parse(query)
        if intents:
            return RoutingDecision(
                mode=ReasoningMode.DETERMINISTIC,
                reason="regra determinística correspondente",
                intents=intents,
            )

        # 3. LLM
        return RoutingDecision(
            mode=ReasoningMode.LLM,
            reason="requer interpretação semântica (fora do determinístico)",
        )

    def get_stats(self) -> dict[str, Any]:
        return {"rules": len(self._deterministic.RULES)}
