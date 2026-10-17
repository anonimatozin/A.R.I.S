"""Segmentador de texto para múltiplas intenções.

Divide uma mensagem do usuário em segmentos, onde cada segmento
representa uma ação ou intenção distinta. Usa conectivos e
delimitadores como pontos de corte, mas também reconhece
fronteiras semânticas quando não há delimitadores explícitos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class TextSegment:
    """Um segmento de texto representando uma ação potencial."""

    text: str
    index: int
    connector: str = ""
    is_conditional: bool = False
    is_temporal: bool = False
    is_parallel: bool = False

    def __str__(self) -> str:
        return self.text


# Conectivos que marcam fronteiras entre ações
_CONNECTIVES = [
    "e depois",
    "e então",
    "e em seguida",
    "e logo depois",
    "e posteriormente",
    "depois disso",
    "em seguida",
    "logo depois",
    "posteriormente",
    "e depois disso",
    "e aí",
    "ai",
    "depois",
    "então",
    "em seguida",
    "e",
    "também",
    "mais",
]

# Conectivos condicionais
_CONDITIONAL_CONNECTIVES = [
    "quando ligar",
    "quando estiver ligado",
    "quando o pc ligar",
    "quando o computador ligar",
    "assim que ligar",
    "assim que estiver ligado",
    "quando abrir",
    "quando estiver pronto",
    "quando terminar",
    "quando chegar",
    "quando voltar",
    "ao ligar",
    "ao iniciar",
]

# Conectivos temporais
_TEMPORAL_CONNECTIVES = [
    "às",
    "as",
    "@",
    "amanhã",
    "amanha",
    "hoje",
    "depois de",
    "daqui",
    "em",
    "mais tarde",
]


@dataclass
class Segmenter:
    """Segmentador de texto multi-ação.

    Divide texto em segmentos usando conectivos, delimitadores
    e análise de fronteiras semânticas.
    """

    _compiled_connectives: list[re.Pattern] = field(default_factory=list, repr=False)
    _compiled_conditional: list[re.Pattern] = field(default_factory=list, repr=False)
    _compiled_temporal: list[re.Pattern] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        for c in _CONNECTIVES:
            escaped = re.escape(c)
            self._compiled_connectives.append(
                re.compile(rf"(?:^|\s)({escaped})(?:\s|$)", re.IGNORECASE)
            )
        for c in _CONDITIONAL_CONNECTIVES:
            escaped = re.escape(c)
            self._compiled_conditional.append(
                re.compile(rf"(?:^|\s)({escaped})(?:\s|$)", re.IGNORECASE)
            )
        for c in _TEMPORAL_CONNECTIVES:
            escaped = re.escape(c)
            self._compiled_temporal.append(
                re.compile(rf"(?:^|\s)({escaped})(?:\s|$)", re.IGNORECASE)
            )

    def segment(self, text: str) -> list[TextSegment]:
        """Segmenta texto em ações individuais.

        Processo:
        1. Normaliza o texto
        2. Identifica pontos de corte (conectivos, vírgulas, etc.)
        3. Divide o texto nos pontos de corte
        4. Classifica cada segmento (condicional, temporal, paralelo)
        5. Remove segmentos vazios
        """
        text = text.strip()
        if not text:
            return []

        # Remove "aris" no início
        text = re.sub(r"^aris\s+", "", text, flags=re.IGNORECASE)

        # Encontra todos os pontos de corte
        cuts = self._find_cut_points(text)

        # Divide o texto
        raw_segments = self._split_at_cuts(text, cuts)

        # Classifica e cria objetos TextSegment
        segments: list[TextSegment] = []
        for i, (seg_text, connector) in enumerate(raw_segments):
            if not seg_text.strip():
                continue
            is_cond = self._is_conditional(seg_text, connector)
            is_temp = self._is_temporal(seg_text, connector)
            is_par = not is_cond and not is_temp and self._is_parallel_candidate(seg_text)
            segments.append(
                TextSegment(
                    text=seg_text.strip(),
                    index=i,
                    connector=connector,
                    is_conditional=is_cond,
                    is_temporal=is_temp,
                    is_parallel=is_par,
                )
            )

        return segments

    def _find_cut_points(self, text: str) -> list[tuple[int, str]]:
        """Encontra pontos de corte no texto, ordenados por posição.

        Retorna lista de (posição, conectivo) ordenada por posição.
        Usa word boundary matching para evitar falsos positivos.
        """
        cuts: list[tuple[int, str]] = []

        # Busca vírgulas
        for m in re.finditer(r",\s*", text):
            cuts.append((m.start(), ","))

        # Buscar conectivos com word boundaries explícitos
        # Conectivos compostos primeiro (mais longos = mais específicos)
        compound_connectives = [
            "e depois", "e então", "e em seguida", "e logo depois",
            "e posteriormente", "depois disso", "e depois disso",
            "e aí", "logo depois",
        ]
        for conn in compound_connectives:
            pattern = re.compile(rf"\b{re.escape(conn)}\b", re.IGNORECASE)
            for m in pattern.finditer(text):
                cuts.append((m.start(), m.group().strip()))

        # Conectivos simples (com word boundary)
        simple_connectives = [
            "depois", "então", "também", "enquanto",
        ]
        for conn in simple_connectives:
            pattern = re.compile(rf"\b{re.escape(conn)}\b", re.IGNORECASE)
            for m in pattern.finditer(text):
                cuts.append((m.start(), m.group().strip()))

        # "e" como conectivo - SÓ quando precedido e seguido por espaço
        # (para evitar "desliga" -> "d" + "sliga")
        # NÃO cortar em "e" quando parece conectar itens de uma lista simples
        # Ex: "abre spotify e discord" NÃO deve cortar
        # Mas "abre spotify e depois abre chrome" DEVE cortar
        for m in re.finditer(r"(?<=\s)e(?=\s)", text, re.IGNORECASE):
            start, end = m.span()
            # Verificar contexto antes e depois do "e"
            before = text[max(0, start-20):start].strip()
            after = text[end:min(len(text), end+20)].strip()
            
            # Se antes e depois são frases curtas (nomes de apps, comandos simples),
            # provavelmente é uma lista, não separação de ações
            before_words = before.split()
            after_words = after.split()
            
            # Heurística: se ambos os lados têm <= 3 palavras e não têm verbos de ação
            # complexos, é provavelmente uma lista de itens
            action_verbs = {"abre", "abrir", "fecha", "fechar", "liga", "desliga", 
                           "reinicia", "executa", "roda", "inicia", "para", "toca",
                           "pesquisa", "busca", "abre", "visita", "navega"}
            
            before_has_verb = any(v in before.lower() for v in action_verbs)
            after_has_verb = any(v in after.lower() for v in action_verbs)
            
            # Se ambos os lados são itens simples (sem verbos, <= 3 palavras), não cortar
            if (len(before_words) <= 3 and len(after_words) <= 3 
                and not before_has_verb and not after_has_verb):
                continue  # Não adicionar este corte
            
            cuts.append((m.start(), "e"))

        # "aí" como conectivo
        for m in re.finditer(r"(?<=\s)a[ií](?=\s)", text, re.IGNORECASE):
            cuts.append((m.start(), "aí"))

        # Conectivos condicionais
        conditional_connectives = [
            "quando ligar", "quando estiver ligado", "assim que ligar",
            "quando abrir", "quando estiver pronto", "quando terminar",
            "ao ligar", "ao iniciar",
        ]
        for conn in conditional_connectives:
            pattern = re.compile(rf"\b{re.escape(conn)}\b", re.IGNORECASE)
            for m in pattern.finditer(text):
                cuts.append((m.start(), m.group().strip()))

        # Remover duplicatas e ordenar
        seen = set()
        unique_cuts = []
        for pos, conn in sorted(cuts, key=lambda x: x[0]):
            if pos not in seen:
                seen.add(pos)
                unique_cuts.append((pos, conn))

        # Filtrar: não cortar no início do texto
        return [(pos, conn) for pos, conn in unique_cuts if pos > 0]

    def _split_at_cuts(
        self, text: str, cuts: list[tuple[int, str]]
    ) -> list[tuple[str, str]]:
        """Divide o texto nos pontos de corte.

        Retorna lista de (segmento, conectivo_anterior).
        """
        if not cuts:
            return [(text, "")]

        result: list[tuple[str, str]] = []
        prev_end = 0
        for pos, connector in cuts:
            segment = text[prev_end:pos].strip()
            if segment:
                result.append((segment, connector if prev_end > 0 else ""))
            prev_end = pos + len(connector)

        # Último segmento
        remaining = text[prev_end:].strip()
        if remaining:
            result.append((remaining, cuts[-1][1] if cuts else ""))

        return result

    def _is_conditional(self, text: str, connector: str) -> bool:
        """Verifica se o segmento é condicional."""
        cond_keywords = [
            "quando", "assim que", "se", "caso", "quando ligar",
            "quando estiver", "ao ligar", "ao iniciar",
        ]
        text_lower = text.lower()
        connector_lower = connector.lower()
        return any(kw in text_lower or kw in connector_lower for kw in cond_keywords)

    def _is_temporal(self, text: str, connector: str) -> bool:
        """Verifica se o segmento contém informação temporal."""
        temp_keywords = [
            "às", "as", "amanhã", "amanha", "hoje", "daqui",
            "depois de", "mais tarde", "em",
        ]
        text_lower = text.lower()
        has_time = bool(re.search(r"\d{1,2}\s*(?:h|:|\s*(?:da\s*noite|de\s*manha|pm|am))", text_lower))
        return has_time or any(kw in text_lower for kw in temp_keywords)

    def _is_parallel_candidate(self, text: str) -> bool:
        """Verifica se o segmento pode ser executado em paralelo.

        Listas de itens (Spotify, Discord e VS Code) são candidatas
        a execução paralela.
        """
        items = re.split(r",\s*|\s+e\s+", text)
        if len(items) >= 2:
            return all(len(item.strip().split()) <= 3 for item in items)
        return False
