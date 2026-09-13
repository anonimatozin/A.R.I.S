"""Memory Consolidator: decide o que merece memória de longo prazo.

Analisa o buffer de conversas recentes com regras determinísticas:
- fatos estáveis (usuario declara uma informação) -> memória SEMÂNTICA
- eventos importantes (configurou, instalou, pediu, tentou...) -> EPISÓDICA
- repetição de assunto -> aumenta importância / promoção
- correção ("na verdade agora uso Y") -> trata contradição (não duplica)

O LLM pode futuramente refinar (resumir/extrair), mas o armazenamento
e a decisão continuam sob controle do sistema.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from .associations import detect_contradiction
from .db import MemoryDatabase
from .models import MemoryKind, StorageClass
from .texting import extract_entities, is_contradiction, is_fact_statement

_EVENT_WORDS = [
    "configurei", "configurando", "instalei", "instalar", "tentei",
    "tentando", "pedi", "ajudei", "montei", "criei", "fiz", "testei",
    "aprendi", "descobri", "solucionei", "quebrou", "comprei",
    "instalando", "rodando", "iniciei", "finalizei",
]


@dataclass
class ConsolidationResult:
    created: int = 0
    reinforced: int = 0
    contradicted: int = 0
    episode: int = 0
    dropped: int = 0


def consolidate(db: MemoryDatabase) -> ConsolidationResult:
    """Processa conversas não consolidadas e promove o que importa."""
    result = ConsolidationResult()
    rows = db.unprocessed_conversations(limit=50)
    if not rows:
        return result

    entity_freq: dict[str, int] = {}
    for row in rows:
        for ent in set(_load_list(row.get("entities"))):
            entity_freq[ent] = entity_freq.get(ent, 0) + 1

    for row in rows:
        text = (row.get("user_text") or "").strip()
        conv_id = row["id"]
        if len(text.split()) < 3:
            db.mark_conversation_processed(conv_id)
            result.dropped += 1
            continue

        entities = extract_entities(text, limit=10)
        repeats = [e for e in entities if entity_freq.get(e, 0) >= 2]

        if is_contradiction(text):
            _handle_contradiction(db, text, entities)
            result.contradicted += 1
        elif is_fact_statement(text):
            if _upsert_semantic(db, text, entities, repeats):
                result.created += 1
            else:
                result.reinforced += 1
        elif any(w in text.lower() for w in _EVENT_WORDS):
            _create_episode(db, text, entities, repeats)
            result.episode += 1
        else:
            db.mark_conversation_processed(conv_id)
            result.dropped += 1
            continue

        db.mark_conversation_processed(conv_id)

    return result


def _upsert_semantic(db: MemoryDatabase, text: str, entities: list[str],
                     repeats: list[str]) -> bool:
    """Cria SEMÂNTICA se não existe; senão reforça/atualiza (sem duplicar)."""
    existing = _find_semantic_by_entities(db, entities)
    importance = 6.0 + min(2.0, len(repeats) * 1.0)
    if existing:
        old = db.get_memory(existing)
        if old:
            db.update_memory(existing, {
                "content": text,
                "summary": _summarize(text),
                "importance": max(float(old.get("importance", 5.0)), importance),
                "updated_at": _now(),
            })
        return False

    _insert(db, MemoryKind.SEMANTIC, text, _summarize(text),
            StorageClass.IMPORTANT if repeats else StorageClass.NORMAL,
            importance, entities)
    return True


def _find_semantic_by_entities(db: MemoryDatabase, entities: list[str]) -> str | None:
    ent_set = set(entities)
    if not ent_set:
        return None
    best_id = None
    best_match = 0
    for row in db.query_memories(memory_type="semantic", limit=500):
        row_ent = set(_load_list(row.get("entities")))
        match = len(ent_set & row_ent)
        if match >= 2 and match > best_match:
            best_match = match
            best_id = row["id"]
    return best_id


def _handle_contradiction(db: MemoryDatabase, text: str, entities: list[str]) -> None:
    mid = _insert(db, MemoryKind.SEMANTIC, text, _summarize(text),
                  StorageClass.IMPORTANT, 7.0, entities)
    for other_id in detect_contradiction(db, text, "semantic"):
        db.add_association(mid, other_id, "contradicts", 0.9, text)
        db.update_memory(other_id, {"confidence": 0.4, "updated_at": _now()})


def _create_episode(db: MemoryDatabase, text: str, entities: list[str],
                    repeats: list[str]) -> None:
    _insert(db, MemoryKind.EPISODIC, text, _summarize(text),
            StorageClass.TEMPORARY, 5.0 + min(2.0, len(repeats)), entities)


def _insert(db: MemoryDatabase, kind: MemoryKind, content: str, summary: str,
            storage: StorageClass, importance: float, entities: list[str]) -> str:
    now = _now()
    mid = uuid.uuid4().hex[:8]
    db.insert_memory((
        mid, kind.value, storage.value, content, summary,
        now, now, now, importance, 0.7, "consolidator",
        json.dumps([], ensure_ascii=False), json.dumps(entities, ensure_ascii=False),
        0, 0, None,
    ))
    return mid


def _summarize(text: str, limit: int = 140) -> str:
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _load_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def _now() -> str:
    return datetime.now().astimezone().isoformat()
