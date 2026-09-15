"""Edge Chat — instancia A.R.I.S. para modo edge (PC offline).

Conversa via Groq com chave separada, usa personalidade sincronizada,
e informa quando algo esta fora do escopo (requer PC).
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from edge.edge_config import EdgeConfig, FALLBACK_PERSONALITY

try:
    from openai import OpenAI

    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

DISCORD_MAX_LENGTH = 2000

WOЛЬ_RESPONSE = (
    "Ainda nao tenho essa capacidade habilitada. "
    "Wake-on-LAN sera implementado em uma etapa futura."
)


class EdgeChat:
    """Chat da instancia edge (CLL1/PC offline).

    Args:
        config: Configuracao do edge.
    """

    def __init__(self, config: EdgeConfig | None = None) -> None:
        self._config = config or EdgeConfig.from_env()
        self._client: Any = None
        self._personality = self._config.load_personality()
        self._history: list[dict[str, str]] = []
        self._memory_db: sqlite3.Connection | None = None
        self._request_count = 0
        self._request_window_start = time.time()

        if HAS_OPENAI and self._config.edge_groq_api_key:
            self._client = OpenAI(
                api_key=self._config.edge_groq_api_key,
                base_url="https://api.groq.com/openai/v1",
            )

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
        return self._client is not None

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

        text_lower = text.strip().lower()

        if any(
            kw in text_lower
            for kw in ["liga o pc", "wake on lan", "wol", "ligar o pc"]
        ):
            return WOЛЬ_RESPONSE

        if any(
            kw in text_lower
            for kw in ["pc status", "pc ligado", "pc desligado", "status do pc"]
        ):
            return (
                "O PC esta offline no momento. "
                "Estou operando no modo edge (CLL1)."
            )

        memories = self._search_memories(text)

        prompt = self._build_prompt(text, memories)

        self._history.append({"role": "user", "content": text})

        try:
            messages = [{"role": "system", "content": prompt}]
            messages.extend(self._history[-10:])

            reply = self._client.chat.completions.create(
                model=self._config.edge_model,
                messages=messages,
                temperature=0.7,
                max_tokens=2048,
            )

            response = reply.choices[0].message.content or ""
            self._history.append({"role": "assistant", "content": response})

            self._save_memory(text, response)

            return response

        except Exception as e:
            return (
                f"Erro no modo edge: {e}. "
                "Tente novamente ou espere o PC ficar online."
            )

    def _build_prompt(self, text: str, memories: list[dict]) -> str:
        """Construi prompt com personalidade e contexto edge."""
        parts = [self._personality]

        parts.append("\n## Modo atual: EDGE (PC offline)")
        parts.append(
            "Voce e a instancia remota da A.R.I.S. (CLL1). "
            "Capacidades disponiveis: conversa, memoria, pesquisa basica."
        )
        parts.append(
            "Capacidades indisponiveis (requerem PC): "
            "automacao, visao, hardware, ferramentas pesadas."
        )
        parts.append(
            "Se o usuario pedir algo que voce nao consegue fazer no modo edge, "
            "explique naturalmente e sugira ligar o PC."
        )
        parts.append(
            "NUNCA execute Wake-on-LAN. "
            "Se pedido, responda: 'Ainda nao tenho essa capacidade habilitada.'"
        )

        if memories:
            parts.append("\n## Memorias relevantes:")
            for m in memories[:5]:
                parts.append(f"- {m.get('content', '')[:160]}")

        return "\n".join(parts)

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
        """Salva interacao na memoria local."""
        if not self._memory_db:
            return
        try:
            mem_id = str(uuid.uuid4())[:8]
            now = time.time().isoformat()
            self._memory_db.execute(
                "INSERT INTO memories (id, content, category, importance, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (mem_id, f"User: {user_text}\nA.R.I.S.: {response}", "conversation", 5, now),
            )
            self._memory_db.commit()
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
                        rec.get("created_at", time.time().isoformat()),
                    ),
                )
                imported += 1
            except Exception:
                continue

        self._memory_db.commit()
        return imported
