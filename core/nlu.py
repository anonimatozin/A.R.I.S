"""NLU Engine — deteccao local de intencao sem LLM.

Analisa linguagem natural informal e detecta intencao com confidence.
Se confidence < threshold, delega pro LLM.

Suporta:
- Portugues informal: "mn pesquisa ai", "verifica isso", "compara com"
- Typos via fuzzy matching
- Contexto da conversa
- Multi-intencao em uma frase
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class IntentType(StrEnum):
    """Tipos de intencao detectaveis localmente."""
    SEARCH = "search"
    RESEARCH = "research"
    VERIFY = "verify"
    COMPARE = "compare"
    LATEST = "latest"
    VISIT = "visit"
    OPEN = "open"
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    WEATHER = "weather"
    EMAIL = "email"
    SYSTEM = "system"
    MEMORY = "memory"
    REMIND = "remind"
    CALC = "calc"
    TRANSLATE = "translate"
    EXPLAIN = "explain"
    SUMMARIZE = "summarize"
    PC_CONTROL = "pc_control"
    SCHEDULE = "schedule"
    CONVERSATION = "conversation"
    UNKNOWN = "unknown"


@dataclass
class IntentResult:
    """Resultado da deteccao de intencao."""
    intent: IntentType
    confidence: float
    params: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    alternatives: list[IntentType] = field(default_factory=list)


# ── Padroes de linguagem informal ────────────────────────────

# Padrões que indicam PERGUNTA PURA (não ação de busca) — devem ter prioridade menor
# Apenas para casos que NÃO requerem busca externa
_QUESTION_PATTERNS = [
    r"^quanto\s+(?:e|eh|é|dá|dao)\s+\d",           # "quanto é 1 mais 1", "quanto dá 2+2" -> CALC
    r"^(?:verdade|falso|certo|errado)\s*\??$",     # "verdade?" "falso?" -> VERIFY
    r"^isso\s*(?:e|eh|é)\s*(?:verdadeiro|falso|certo|errado)\s*\??$", # "isso é verdade?"
    r"^ta\s*(?:certo|errado|correto)\s*\??$",      # "ta certo?"
    r"^(?:oi|ola|eai|bom\s*(?:dia|tarde|noite)|fala|hey|hello|hi|salve|e\s*ai)$", # cumprimentos puros
    r"^(?:obrigad[oa]|valeu|thanks|thx|brigad)$",   # agradecimentos
    r"^(?:tchau|bye|flw|falou|até\s*(?:mais|logo))$", # despedidas
    r"^(?:como\s*(?:voce|vc)\s*(?:ta|está|esta|e|eh))\s*\??$", # "como vc tá?"
    r"^(?:sim|não|nao|ok|beleza|blz)$",             # respostas simples
]

# Padrões que indicam AÇÃO de busca explícita — prioridade maior
_SEARCH_PATTERNS = [
    r"(?:pesquisa|pesquisar|busca|buscar|procura|procurar)\s*(?:ai|pf|por favor|aqui)?",
    r"(?:search|find|look\s*(?:up|for))",
    r"(?:o\s*que\s*(?:e|eh|é|são)\s+(?!aris|vc|voce)\w+)",   # "o que é python" -> busca
    r"(?:quem\s*(?:e|eh|é|são)\s*\w+)",                      # "quem é alan" -> busca
    r"(?:onde\s+(?:fica|e|eh|é|está|ta|fica)\s*\w+)",        # "onde fica torre" -> busca
    r"(?:me\s*(?:dá|da|mostra))\s+(?!fala).+",
    r"(?:sabe\s*(?:dizer|falar|informar))",
    r"(?:info(?:rmação|fo)?\s*(?:sobre|de|do|da|dos|das))",
]

_RESEARCH_PATTERNS = [
    r"(?:pesquisa\s*(?:aprofundada|fundamental|completa|detalhada))",
    r"(?:estuda\s*(?:isso|este|esta|o\s*que))",
    r"(?:aprofunda(?:r)?\s*(?:isso|o\s*tema))",
    r"(?:quero\s*(?:saber\s*(?:mais|tudo)|entender)\s*(?:sobre|de)?)",
    r"(?:me\s*(?:conta|explica)\s*(?:tudo|mais)\s*(?:sobre|de)?)",
    r"(?:research|deep\s*(?:dive|search))",
]

_VERIFY_PATTERNS = [
    r"(?:verifica(?:r)?|confirma(?:r)?|checa(?:r)?)\s*(?:isso|isto|se|pra|pra\s*mim)?",
    r"(?:e\s*(?:verdade|true|correto|certo|real)|é\s*(?:verdade|true|correto|certo|real))\s*\??",
    r"(?:isso\s*(?:e|eh|é)\s*(?:verdadeiro|falso|certo|errado))",
    r"(?:ta\s*(?:certo|errado|correto))\s*\??",
    r"(?:confirm(?:a|e|ar))\s*(?:isso|pra\s*mim)?",
    r"(?:verify|confirm|check|fact\s*check)",
    r"(?:cheque|valide)",
]

_COMPARE_PATTERNS = [
    r"(?:compara(?:r)?|comparação|comparar?)\s*(?:com|entre)?",
    r"(?:qual\s*(?:e|eh|é)\s*melhor)",
    r"(?:diferença\s*(?:entre|de|do|da))",
    r"(?:versus|vs\.?|x)\s",
    r"(?:lado\s*a\s*lado)",
    r"(?:compare|versus|vs\.?|difference\s*between)",
    r"(?:um\s*eh?\s*melhor\s*(?:que|do\s*que)\s*outro)",
]

_LATEST_PATTERNS = [
    r"(?:última|ultima|mais\s*recente|nova|novo)\s*(?:noticia|notícia|informação|info|atualização)",
    r"(?:o\s*que\s*(?:tem|tem\s*de\s*novo|aconteceu|rolou))",
    r"(?:atualiza(?:r)?|novo\s*(?:em|de|sobre))",
    r"(?:latest|recent|news|update|what(?:'s|\s+is)\s*new)",
    r"(?:tem\s*algo\s*novo)",
]

_VISIT_PATTERNS = [
    r"(?:abre(?:r)?|visita(?:r)?|acessa(?:r)?)\s*(?:o|a|os|as)?\s*(?:site|link|url|página|pagina|site)",
    r"(?:vai\s*(?:pro|pra|no|na)\s*(?:site|link|url|página))",
    r"(?:abre\s*(?:o\s*)?(?:chrome|firefox|edge|browser|navegador))",
    r"(?:visit|open\s*(?:url|link|site|page))",
]

_OPEN_PATTERNS = [
    r"(?:abre(?:r)?|inicia(?:r)?|executa(?:r)?)\s+(?:o|a|os|as)?\s*(.+)",
    r"(?:start|launch|open|run)\s+(.+)",
]

_PC_CONTROL_PATTERNS = [
    r"(?:desliga(?:r)?|desligue|shutdown|off)\s+(?:o|a|o\s*computador|o\s*pc|pc|computador)",
    r"(?:reinicia(?:r)?|reinicie|restart|reboot)\s+(?:o|a|o\s*computador|o\s*pc|pc|computador)",
    r"(?:trava(?:r)?|trave|lock)\s+(?:o|a|o\s*computador|o\s*pc|pc|computador)",
    r"(?:dorme|dormir|sleep|suspen(?:der|der))\s+(?:o|a|o\s*computador|o\s*pc|pc|computador)",
    r"(?:pc|computador)\s+(?:desliga|reinicia|trava|dorme|sleep|shutdown|restart|lock)",
    r"(?:wake\s*on\s*lan|wol|liga(?:r)?\s+(?:o|a)?\s*(?:pc|computador|maquina))",
    r"(?:status\s+do\s+pc|pc\s+(?:ta|esta|eh|e)\s+(?:ligado|desligado|online|offline))",
    r"(?:o\s+pc\s+(?:ta|esta|eh|e)\s+(?:ligado|desligado|online|offline))",
    r"(?:pc\s+(?:ta|esta|eh|e)\s+(?:ligado|desligado|online|offline))",
]

_SCHEDULE_PATTERNS = [
    r"(?:desliga(?:r)?)\s+(?:o\s*pc|o\s*computador|pc|computador)?\s*(?:as|aas|@\s*)\s*\d{1,2}\s*(?:h|[:\s]\s*\d{2}|da\s*noite|de\s*manha|pm|am)",
    r"(?:desliga(?:r)?)\s+(?:o\s*pc|o\s*computador|pc|computador)?\s*(?:daqui|em)\s+\d+\s*(?:hora|horas|minuto|minutos)",
    r"(?:daqui|em)\s+\d+\s*(?:hora|horas|minuto|minutos).*?(?:desliga|shutdown)",
    r"(?:programa(?:r)?|agenda(?:r)?)\s+(?:o\s*)?(?:desligamento|desligar|shutdown)",
    r"(?:liga(?:r)?)\s+(?:o\s*pc|o\s*computador|pc|computador)?\s*(?:as|aas|@\s*)\s*\d{1,2}\s*(?:h|[:\s]\s*\d{2}|da\s*noite|de\s*manha|pm|am)",
    r"(?:amanha|amanha)\s+(?:de\s*manha|as)\s+\d{1,2}",
    r"(?:cancela(?:r)?)\s+(?:o\s*)?(?:desligamento|ligamento|agendamento)",
    r"(?:qual|quais)\s+(?:desligamento|ligamento|agendamento)\s+(?:esta|estao)\s+programado",
]

_SYSTEM_PATTERNS = [
    r"(?:status|estado|situação|situacao)\s*(?:do\s*sistema|geral|completo)?",
    r"(?:como\s*(?:ta|está|esta)\s*(?:o|a|tudo)?)",
    r"\b(?:disk|disco|cpu|memória|memoria|ram|processador)\b",
    r"(?:desligar|reiniciar|lock|travar|dormir|sleep)",
    r"\b(?:system|disk|cpu|memory|ram|shutdown|restart|lock|sleep)\b",
]

_EMAIL_PATTERNS = [
    r"(?:email|e-?mail|caixa\s*de\s*entrada|inbox)",
    r"(?:tem\s*(?:email|mensagem|e-?mail))",
    r"(?:le(?:r)?\s*(?:email|e-?mail|mensagem))",
    r"(?:envia(?:r)?\s*(?:email|e-?mail))",
    r"(?:email|mail|inbox)",
]

_WEATHER_PATTERNS = [
    r"(?:tempo|clima|temperatura|previsão|previsao)",
    r"(?:vai\s*chover|vai\s*fazer\s*(?:calor|frio))",
    r"(?:how(?:'s|\s+is)\s+the\s+weather|temperature|forecast)",
    r"(?:tempo\s*(?:em|de|no|na)\s*.+)",
]

_MEMORY_PATTERNS = [
    r"(?:lembra|lembre|memoriza|guarda|salva(?:r)?)\s*(?:isso|isto|que)?",
    r"(?:esqueci|nao\s*lembro|não\s*lembro)",
    r"(?:o\s*que\s*(?:eu\s*)?(?:falei|disse|pedi)\s*(?:ante(?:s|rior)?|antes|ontem|ha\s*pouco))",
    r"(?:remember|memorize|save|recall)",
]

_CALC_PATTERNS = [
    r"(?:calcula(?:r)?|quanto\s*(?:e|eh|dá|dao|da)\s*)",
    r"(?:\d+\s*[+\-*/÷×^]\s*\d+)",
    r"(?:math|calc|compute|quanto\s*é)",
]

_TRANSLATE_PATTERNS = [
    r"(?:traduz(?:ir)?|tradução|traducao)",
    r"(?:em\s*(?:inglês|ingles|portugues|espanhol|frances))",
    r"(?:translate|translation)",
]

_EXPLAIN_PATTERNS = [
    r"(?:explica(?:r)?|me\s*(?:conta|fala))\s+(?:isso|isto|o\s*que|como|por\s*que|porquê)",
    r"(?:por\s*(?:que|quê)\s*(?:e|eh|acontece|funciona))",
    r"(?:what\s*(?:is|are|does|do)\s*.+\s*(?:mean|do))",
    r"(?:o\s*que\s*(?:significa|quer\s*dizer))",
]

_SUMMARIZE_PATTERNS = [
    r"(?:resumi(?:r)?|resumo|digest|sintetiza(?:r)?)",
    r"(?:me\s*(?:dá|da)\s*um\s*resumo)",
    r"(?:summarize|summary|tldr|tl;dr)",
]

_CONVERSATION_PATTERNS = [
    r"^(?:oi|ola|eai|bom\s*(?:dia|tarde|noite)|fala|hey|hello|hi|salve|e\s*ai)$",
    r"^(?:obrigad[oa]|valeu|thanks|thx|brigad)$",
    r"(?:^(?:tchau|bye|flw|falou)|até\s*(?:mais|logo))",
    r"^(?:como\s*(?:voce|vc)\s*(?:ta|está|esta|e|eh))\s*\??$",
    r"^(?:sim|não|nao|ok|beleza|blz)$",
]


def _parse_time(text: str) -> str | None:
    """Parse tempo natural em texto.

    Suporta:
    - "as 23h", "as 23:00", "as 23:30", "@ 11pm"
    - "daqui 2 horas", "em 30 minutos"
    - "amanha as 7"
    - "hoje as 15"
    """
    text = text.lower().strip()

    # "as HH:MM" (com minutos)
    m = re.search(r'(?:as|@)\s*(\d{1,2})\s*:\s*(\d{2})\s*(?:da\s*noite|pm)?', text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        if "noite" in text or "pm" in text:
            if hour < 12:
                hour += 12
        if hour > 23:
            hour = 23
        if minute > 59:
            minute = 59
        return f"{hour:02d}:{minute:02d}"

    # "as HHh" ou "as HH"
    m = re.search(r'(?:as|@)\s*(\d{1,2})\s*h?\s*(?:da\s*noite|pm)?', text)
    if m:
        hour = int(m.group(1))
        if "noite" in text or "pm" in text:
            if hour < 12:
                hour += 12
        if hour > 23:
            hour = 23
        return f"{hour:02d}:00"

    # "daqui X horas" / "em X horas"
    m = re.search(r'(?:daqui|em)\s+(\d+)\s*(?:hora|horas)', text)
    if m:
        hours = int(m.group(1))
        from datetime import datetime, timedelta
        target = datetime.now() + timedelta(hours=hours)
        return target.strftime("%H:%M")

    # "daqui X minutos" / "em X minutos"
    m = re.search(r'(?:daqui|em)\s+(\d+)\s*(?:minuto|minutos|min|mins)', text)
    if m:
        minutes = int(m.group(1))
        from datetime import datetime, timedelta
        target = datetime.now() + timedelta(minutes=minutes)
        return target.strftime("%H:%M")

    # "amanha as HH"
    m = re.search(r'(?:amanha|amanha)\s+(?:de\s*manha\s+)?(?:as\s+)?(\d{1,2})', text)
    if m:
        hour = int(m.group(1))
        return f"amanha {hour:02d}:00"

    return None


@dataclass
class _PatternGroup:
    intent: IntentType
    patterns: list[str]
    weight: float = 1.0


class NLUEngine:
    """Engine de deteccao local de intencao.

    Analisa texto e retorna intencao com confidence sem chamar LLM.
    """

    CONFIDENCE_THRESHOLD = 0.5
    MIN_CONFIDENCE = 0.3

    def __init__(self, threshold: float = CONFIDENCE_THRESHOLD) -> None:
        self._threshold = threshold
        self._groups = self._build_groups()
        self._context_history: list[str] = []

    def _build_groups(self) -> list[_PatternGroup]:
        """Constroi grupo de padroes."""
        return [
            _PatternGroup(IntentType.SEARCH, _SEARCH_PATTERNS, 1.0),
            _PatternGroup(IntentType.RESEARCH, _RESEARCH_PATTERNS, 1.3),
            _PatternGroup(IntentType.VERIFY, _VERIFY_PATTERNS, 1.0),
            _PatternGroup(IntentType.COMPARE, _COMPARE_PATTERNS, 1.0),
            _PatternGroup(IntentType.LATEST, _LATEST_PATTERNS, 1.0),
            _PatternGroup(IntentType.VISIT, _VISIT_PATTERNS, 1.0),
            _PatternGroup(IntentType.OPEN, _OPEN_PATTERNS, 1.0),
            _PatternGroup(IntentType.PC_CONTROL, _PC_CONTROL_PATTERNS, 1.5),
            _PatternGroup(IntentType.SCHEDULE, _SCHEDULE_PATTERNS, 1.6),
            _PatternGroup(IntentType.SYSTEM, _SYSTEM_PATTERNS, 1.0),
            _PatternGroup(IntentType.EMAIL, _EMAIL_PATTERNS, 1.0),
            _PatternGroup(IntentType.WEATHER, _WEATHER_PATTERNS, 1.0),
            _PatternGroup(IntentType.MEMORY, _MEMORY_PATTERNS, 1.0),
            _PatternGroup(IntentType.CALC, _CALC_PATTERNS, 1.0),
            _PatternGroup(IntentType.TRANSLATE, _TRANSLATE_PATTERNS, 1.0),
            _PatternGroup(IntentType.EXPLAIN, _EXPLAIN_PATTERNS, 1.5),
            _PatternGroup(IntentType.SUMMARIZE, _SUMMARIZE_PATTERNS, 1.0),
            _PatternGroup(IntentType.CONVERSATION, _CONVERSATION_PATTERNS, 0.8),
        ]

    def detect(self, text: str) -> IntentResult:
        """Detecta intencao no texto.

        Returns:
            IntentResult com intent, confidence, params.
        """
        normalized = self._normalize(text)
        
        # Primeiro: verificar se é uma pergunta/informação (não ação)
        # Se matches _QUESTION_PATTERNS, reduzir drasticamente score de ações
        is_question = False
        for pattern in _QUESTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                is_question = True
                break
        
        scores: dict[IntentType, float] = {}
        params: dict[str, Any] = {}

        for group in self._groups:
            score = self._match_patterns(normalized, group.patterns)
            if score > 0:
                # Se é pergunta e a intenção é de ação, reduzir score drasticamente
                if is_question and group.intent in (IntentType.SEARCH, IntentType.RESEARCH, IntentType.VERIFY, IntentType.COMPARE, IntentType.LATEST, IntentType.VISIT, IntentType.OPEN, IntentType.PC_CONTROL, IntentType.SCHEDULE, IntentType.SYSTEM, IntentType.EXECUTE):
                    score *= 0.1  # Penaliza ações quando detecta pergunta
                scores[group.intent] = score * group.weight

        if not scores:
            return IntentResult(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                raw_text=text,
            )

        # Ordenar por score
        sorted_intents = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        best_intent, best_score = sorted_intents[0]

        # Confidence: 1 match = 0.7, 2 matches = 0.85, 3+ = 1.0
        if best_score >= 3.0:
            confidence = 1.0
        elif best_score >= 2.0:
            confidence = 0.85
        elif best_score >= 1.0:
            confidence = 0.7
        else:
            confidence = self.MIN_CONFIDENCE

        # Se tem intents concorrentes com score similar, reduz confidence
        runner_up = sorted_intents[1][1] if len(sorted_intents) > 1 else 0
        if runner_up >= best_score * 0.7:
            confidence *= 0.8

        # Alternativas
        alternatives = [i for i, s in sorted_intents[1:3] if s > 0.5]

        # Extrair params
        params = self._extract_params(normalized, best_intent, text)

        # Atualizar historico
        self._context_history.append(text)
        if len(self._context_history) > 20:
            self._context_history = self._context_history[-20:]

        return IntentResult(
            intent=best_intent,
            confidence=confidence,
            params=params,
            raw_text=text,
            alternatives=alternatives,
        )

    def should_use_llm(self, result: IntentResult) -> bool:
        """Verifica se deve delegar pro LLM."""
        return result.confidence < self._threshold

    def _normalize(self, text: str) -> str:
        """Normaliza texto pra matching."""
        t = text.lower().strip()
        # Remover pontuacao mas manter caracteres acentuados
        t = re.sub(r'[^\w\s]', ' ', t, flags=re.UNICODE)
        # Remover espacos extras
        t = re.sub(r'\s+', ' ', t).strip()
        return t

    def _match_patterns(self, text: str, patterns: list[str]) -> float:
        """Retorna score de matching (0 = none, >0 = match)."""
        score = 0.0
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                score += 1.0
        return score

    def _extract_params(self, text: str, intent: IntentType, raw_text: str = "") -> dict[str, Any]:
        """Extrai parametros relevantes do texto."""
        params: dict[str, Any] = {}

        if intent in (IntentType.SEARCH, IntentType.RESEARCH, IntentType.LATEST):
            # Extrair query (remover verbos de acao)
            query = text
            for verb in ["pesquisa", "pesquisar", "busca", "buscar", "procura",
                         "procurar", "search", "find", "look up"]:
                query = query.replace(verb, "")
            params["query"] = query.strip()

        elif intent == IntentType.COMPARE:
            # Tentar extrair dois items pra comparar
            parts = re.split(r'\s+(?:com|vs|x|versus|entre)\s+', text)
            if len(parts) >= 2:
                params["items"] = [p.strip() for p in parts[:2]]

        elif intent == IntentType.OPEN:
            # Extrair nome do app/arquivo
            match = re.search(r'(?:abre|open|run|launch|inicia|executa)\s+(.+)', text)
            if match:
                params["target"] = match.group(1).strip()

        elif intent == IntentType.WEATHER:
            # Extrair cidade
            match = re.search(r'(?:tempo|clima|previsão)\s*(?:em|de|no|na)\s+(.+)', text)
            if match:
                params["city"] = match.group(1).strip()

        elif intent == IntentType.EXPLAIN:
            match = re.search(r'(?:explica|me conta|o que (?:significa|quer dizer))\s*(.+)', text)
            if match:
                params["topic"] = match.group(1).strip()

        elif intent == IntentType.PC_CONTROL:
            # Detectar acao especifica
            if re.search(r'desliga|shutdown|off', text):
                params["action"] = "shutdown"
            elif re.search(r'reinicia|restart|reboot', text):
                params["action"] = "restart"
            elif re.search(r'trava|lock', text):
                params["action"] = "lock"
            elif re.search(r'dorme|sleep|suspen', text):
                params["action"] = "sleep"
            elif re.search(r'wake|wol|liga', text):
                params["action"] = "wake"
            elif re.search(r'status|ligado|desligado|online|offline', text):
                params["action"] = "status"
            time_info = _parse_time(raw_text)
            if time_info:
                params["time"] = time_info

        elif intent == IntentType.SCHEDULE:
            time_info = _parse_time(raw_text)
            if time_info:
                params["time"] = time_info
            if re.search(r'cancela', raw_text):
                params["action"] = "cancel"
            elif re.search(r'desliga|shutdown', raw_text):
                params["action"] = "shutdown"
            elif re.search(r'liga|wake|ligar', raw_text):
                params["action"] = "wake"
            elif re.search(r'qual|quais|status', raw_text):
                params["action"] = "query"

        elif intent == IntentType.CALC:
            # Use raw_text to preserve operators
            match = re.search(r'(\d+[\s]*[+\-*/÷×^][\s]*\d+(?:[\s]*[+\-*/÷×^][\s]*\d+)*)', text)
            if match:
                params["expression"] = match.group(1).strip()
            else:
                # Fallback: look in raw_text
                match = re.search(r'(\d+[\s]*[+\-*/÷×^][\s]*\d+)', raw_text)
                if match:
                    params["expression"] = match.group(1).strip()

        return params
