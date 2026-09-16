"""Sistema de personalidade da A.R.I.S.

Gerencia os tracos de personalidade, estilo de comunicacao,
e evolucao gradual baseada em interacoes.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any


_BASE_PERSONALITY = {
    "formality": 0.55,
    "humor": 0.35,
    "verbosity": 0.45,
    "initiative": 0.65,
    "technical_depth": 0.75,
    "patience": 0.70,
    "warmth": 0.60,
    "directness": 0.50,
}

_SITUATION_MODIFIERS = {
    "technical_problem": {"formality": 0.3, "technical_depth": 0.9, "humor": -0.2},
    "error": {"formality": 0.4, "directness": 0.8, "humor": -0.3},
    "critical": {"formality": 0.2, "directness": 0.95, "verbosity": -0.3, "humor": -0.5},
    "casual": {"formality": -0.2, "humor": 0.3, "warmth": 0.2},
    "learning": {"patience": 0.3, "verbosity": 0.2, "technical_depth": -0.1},
}

_TRAIT_DESCRIPTIONS = {
    "formality": {
        0.0: "muito informal e descontraido",
        0.3: "informal mas educado",
        0.5: "equilibrado entre formal e casual",
        0.7: "mais formal e profissional",
        1.0: "extremamente formal",
    },
    "humor": {
        0.0: "sempre serio",
        0.3: "humor leve e esporadico",
        0.5: "humor moderado e contextual",
        0.7: "bastante humor e espirituoso",
        1.0: "sempre com humor",
    },
    "verbosity": {
        0.0: "respostas extremamente curtas",
        0.3: "respostas concisas",
        0.5: "respostas equilibradas",
        0.7: "respostas mais detalhadas",
        1.0: "respostas muito completas",
    },
    "initiative": {
        0.0: "apenas responde o que perguntam",
        0.3: "ocasionalmente sugere",
        0.5: "faz sugestoes quando relevante",
        0.7: "proativo e sugere solucoes",
        1.0: "muito proativo",
    },
    "technical_depth": {
        0.0: "explicacoes simples e diretas",
        0.3: "explicacoes com detalhes basicos",
        0.5: "explicacoes equilibradas",
        0.7: "explicacoes tecnicas detalhadas",
        1.0: "explicacoes extremamente tecnicas",
    },
    "patience": {
        0.0: "impaciente",
        0.3: "pouco paciente",
        0.5: "paciente",
        0.7: "muito paciente",
        1.0: "extremamente paciente",
    },
    "warmth": {
        0.0: "frio e distante",
        0.3: "neutro",
        0.5: "amigavel",
        0.7: "caloroso e acolhedor",
        1.0: "extremamente afetuoso",
    },
    "directness": {
        0.0: "muito indireto",
        0.3: "gentilmente direto",
        0.5: "direto quando necessario",
        0.7: "sempre direto",
        1.0: "extremamente direto",
    },
}


@dataclass
class PersonalityState:
    """Estado atual da personalidade da A.R.I.S."""

    traits: dict[str, float] = field(default_factory=lambda: _BASE_PERSONALITY.copy())
    interaction_count: int = 0
    last_updated: float = field(default_factory=time.time)
    learned_preferences: list[dict[str, Any]] = field(default_factory=list)
    rejected_behaviors: list[str] = field(default_factory=list)
    reinforced_behaviors: list[str] = field(default_factory=list)
    situation_history: list[dict[str, Any]] = field(default_factory=list)

    def get_trait(self, name: str) -> float:
        """Retorna o valor de um traco (0.0 a 1.0)."""
        return self.traits.get(name, 0.5)

    def get_style_description(self) -> str:
        """Retorna descricao do estilo atual."""
        parts = []
        for trait, value in self.traits.items():
            descriptions = _TRAIT_DESCRIPTIONS.get(trait, {})
            best_match = min(descriptions.keys(), key=lambda k: abs(k - value))
            parts.append(descriptions[best_match])
        return ", ".join(parts[:4])

    def to_dict(self) -> dict[str, Any]:
        return {
            "traits": self.traits.copy(),
            "interaction_count": self.interaction_count,
            "last_updated": self.last_updated,
            "learned_preferences": self.learned_preferences[-20:],
            "rejected_behaviors": self.rejected_behaviors[-20:],
            "reinforced_behaviors": self.reinforced_behaviors[-20:],
            "style_description": self.get_style_description(),
        }


class PersonalitySystem:
    """Sistema de personalidade evolutiva da A.R.I.S.

    Gera o system prompt de personalidade, adapta comportamento
    baseado em interacoes, e mantem estado entre sessoes.
    """

    def __init__(self, state_path: str = ""):
        self._state_path = state_path or os.path.join(
            os.path.dirname(__file__), "..", "data", "personality_state.json"
        )
        self._state = self._load_state()

    def _load_state(self) -> PersonalityState:
        """Carrega estado da personalidade do disco."""
        try:
            if os.path.exists(self._state_path):
                with open(self._state_path, encoding="utf-8") as f:
                    data = json.load(f)
                state = PersonalityState()
                state.traits = data.get("traits", _BASE_PERSONALITY.copy())
                state.interaction_count = data.get("interaction_count", 0)
                state.last_updated = data.get("last_updated", time.time())
                state.learned_preferences = data.get("learned_preferences", [])
                state.rejected_behaviors = data.get("rejected_behaviors", [])
                state.reinforced_behaviors = data.get("reinforced_behaviors", [])
                return state
        except Exception:
            pass
        return PersonalityState()

    def _save_state(self) -> None:
        """Salva estado da personalidade no disco."""
        try:
            os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
            with open(self._state_path, "w", encoding="utf-8") as f:
                json.dump(self._state.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_state(self) -> PersonalityState:
        """Retorna o estado atual."""
        return self._state

    def generate_prompt(self, situation: str = "normal") -> str:
        """Gera prompt de personalidade para o system message.

        Args:
            situation: Situacao atual (normal, technical_problem, error, critical, casual, learning)
        """
        traits = self._state.traits.copy()

        modifiers = _SITUATION_MODIFIERS.get(situation, {})
        for trait, modifier in modifiers.items():
            if trait in traits:
                traits[trait] = max(0.0, min(1.0, traits[trait] + modifier))

        formality = traits["formality"]
        humor = traits["humor"]
        verbosity = traits["verbosity"]
        initiative = traits["initiative"]
        technical = traits["technical_depth"]
        patience = traits["patience"]
        warmth = traits["warmth"]
        directness = traits["directness"]

        lines = [
            "Voce e a A.R.I.S. — Assistente de Raciocínio e Integracao de Sistemas.",
            "",
            "## Como falar",
        ]

        if formality < 0.3:
            lines.append("Fale de forma bem informal e descontraida. Pode usar gírias e abreviacoes.")
        elif formality < 0.5:
            lines.append("Fale de forma informal mas educada. Natural, como conversaria com um amigo.")
        elif formality < 0.7:
            lines.append("Fale de forma equilibrada, nem muito formal nem muito casual.")
        else:
            lines.append("Fale de forma mais formal e profissional. Seja educado e preciso.")

        if humor > 0.6:
            lines.append("Pode usar humor com frequencia. Sarcasmo leve, comentarios espirituosos.")
        elif humor > 0.3:
            lines.append("Use humor ocasionalmente quando a situacao permitir. Seja sutil.")
        else:
            lines.append("Mantenha tom mais serio. Humor apenas se muito apropriado.")

        if verbosity > 0.6:
            lines.append("Detalhe bem suas respostas. Explique o contexto e as opcoes.")
        elif verbosity > 0.3:
            lines.append("Seja equilibrado no tamanho das respostas. Detalhe quando necessario.")
        else:
            lines.append("Seja conciso. V direto ao ponto, sem floreios.")

        if directness > 0.6:
            lines.append("Seja direto e objetivo. Nao rodeie.")
        elif directness > 0.3:
            lines.append("Seja direto quando necessario, mas gentil quando apropriado.")

        if initiative > 0.6:
            lines.append("Seja proativo. Sugira solucoes, alerte sobre problemas, ofereca alternativas.")
        elif initiative > 0.3:
            lines.append("Faca sugestoes ocasionais quando relevante.")

        if technical > 0.6:
            lines.append("Detalhe tecnicamente quando o assunto for tecnico. Use termos precisos.")
        elif technical > 0.3:
            lines.append("Explique com nivel tecnico moderado, adaptando ao usuario.")

        if patience > 0.6:
            lines.append("Seja paciente. Explique com calma, especialmente se o usuario estiver aprendendo.")

        if warmth > 0.6:
            lines.append("Seja caloroso e acolhedor. Mostre interesse genuino.")

        lines.extend([
            "",
            "## Regras",
            "- Responda em portugues brasileiro natural",
            "- Nao seja robotica. Evite frases como 'Comando recebido' ou 'Processando'",
            "- Adapte o tamanho da resposta a situacao",
            "- Se nao souber algo, diga honestamente",
            "- Mantenha continuidade na conversa",
            "- Nao invente sentimentos ou experiencias humanas",
            "- Honesto e mais importante que parecer inteligente",
        ])

        if self._state.reinforced_behaviors:
            lines.append("")
            lines.append("## Preferencias aprendidas")
            for pref in self._state.reinforced_behaviors[-5:]:
                lines.append(f"- {pref}")

        if self._state.rejected_behaviors:
            lines.append("")
            lines.append("## Evitar")
            for rej in self._state.rejected_behaviors[-5:]:
                lines.append(f"- {rej}")

        return "\n".join(lines)

    def record_interaction(
        self,
        user_message: str,
        response: str,
        feedback: str | None = None,
    ) -> None:
        """Registra interacao para evolucao da personalidade.

        Args:
            user_message: Mensagem do usuario
            response: Resposta da ARIS
            feedback: Feedback do usuario (positive, negative, None)
        """
        self._state.interaction_count += 1
        self._state.last_updated = time.time()

        msg_lower = user_message.lower()

        if feedback == "negative":
            if any(kw in msg_lower for kw in ["fala mais direto", "seja direto", "mais curto"]):
                self._adjust_trait("directness", 0.05)
                self._adjust_trait("verbosity", -0.05)
                self._state.reinforced_behaviors.append("Ser mais direto")
            elif any(kw in msg_lower for kw in ["fala mais serio", "nao tenho paciencia"]):
                self._adjust_trait("humor", -0.05)
                self._state.rejected_behaviors.append("Humor em contexto serio")
            elif any(kw in msg_lower for kw in ["explica melhor", "mais detalhe"]):
                self._adjust_trait("verbosity", 0.05)
                self._adjust_trait("technical_depth", 0.05)

        if feedback == "positive":
            if any(kw in msg_lower for kw in ["obrigad", "boa", "perfeito", "otimo"]):
                self._state.reinforced_behaviors.append("Manter estilo atual")

        if self._state.interaction_count % 50 == 0:
            self._analyze_patterns()

        self._save_state()

    def _adjust_trait(self, trait: str, delta: float) -> None:
        """Ajusta um traco gradualmente."""
        if trait in self._state.traits:
            current = self._state.traits[trait]
            self._state.traits[trait] = max(0.0, min(1.0, current + delta))

    def _analyze_patterns(self) -> None:
        """Analisa padroes nas interacoes recentes."""
        pass

    def detect_situation(self, message: str) -> str:
        """Detecta a situacao baseado na mensagem."""
        msg = message.lower()

        if any(kw in msg for kw in ["erro", "falhou", "bug", "problem", "travou", "nao funciona"]):
            return "error"
        if any(kw in msg for kw in ["critico", "urgente", "seguranca", "falha de seguranca"]):
            return "critical"
        if any(kw in msg for kw in ["explica", "como funciona", "o que e", "por que"]):
            return "learning"
        if any(kw in msg for kw in ["opa", "eai", "fala", "oi", "bom dia", "boa noite"]):
            return "casual"
        if any(kw in msg for kw in ["pc", "computador", "sistema", "cpu", "memoria", "disco"]):
            return "technical_problem"

        return "normal"


_personality_instance: PersonalitySystem | None = None


def get_personality() -> PersonalitySystem:
    """Retorna instancia singleton do sistema de personalidade."""
    global _personality_instance
    if _personality_instance is None:
        _personality_instance = PersonalitySystem()
    return _personality_instance
