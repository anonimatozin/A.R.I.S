"""``SqliteMemory``: memória de longo prazo em SQLite (implementa o protocolo ``Memory``).

Leve para um PC modesto: só ``sqlite3`` da biblioteca padrão. Busca por FTS5/BM25
com normalização de acentos (``configuração`` acha ``configuracao``), com queda
para ``LIKE`` quando o SQLite não tem FTS5. Escritas são atômicas (``BEGIN
IMMEDIATE``) e seguras para várias threads (conexão por thread + lock de escrita;
banco ``:memory:`` usa uma conexão única com lock).
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import AgentConfig, load_config
from ..contract.protocols import LLMClient
from ..contract.types import ChatMessage, MemoryItem
from ..contract.utils import redact_secrets, truncate_text
from .embedder import Embedder, cosine, pack_vector, unpack_vector
from .schema import apply_schema, enable_fts
from .textutil import clean_tags, escape_like, normalize, similar, tokenize

log = logging.getLogger("aris.agent.memory.sqlite")

#: Tipos de item aceitos pelo contrato (``MemoryItem.kind``).
VALID_KINDS: tuple[str, ...] = ("fact", "preference", "lesson", "episode")

#: Papéis de conversa aceitos em ``add_turn`` (mesmos do ``ChatMessage``).
VALID_ROLES: tuple[str, ...] = ("system", "user", "assistant", "tool")

#: Token exigido por ``wipe_all`` para apagar tudo.
WIPE_CONFIRM_TOKEN = "APAGAR TUDO"

DEFAULT_MAX_TEXT_CHARS = 2000
DEFAULT_MAX_TURN_CHARS = 4000
DEFAULT_DEDUP_THRESHOLD = 0.92
DEFAULT_IMPORTANCE = 0.5

# Pesos da pontuação de recall: relevância + recência + importância + frequência de uso.
_W_RELEVANCE = 0.5
_W_RECENCY = 0.2
_W_IMPORTANCE = 0.2
_W_USE = 0.1
_RECENCY_HALF_LIFE_DAYS = 180.0
_USE_LOG_DIVISOR = 6.0
_BM25_EPSILON = 1e-6
_CANDIDATE_LIMIT = 300
_MAX_QUERY_TERMS = 16
_EMBED_BLEND = 0.5

_ITEM_COLUMNS = (
    "id",
    "text",
    "norm",
    "kind",
    "tags",
    "created_at",
    "updated_at",
    "last_used_at",
    "use_count",
    "importance",
    "emb",
)


def _columns(prefix: str = "") -> str:
    """Lista as colunas de ``items`` com prefixo opcional (ex.: ``i.``)."""
    return ", ".join(prefix + name for name in _ITEM_COLUMNS)


def _as_bool(value: Any, default: bool) -> bool:
    """Interpreta bool vindo do JSON de configuração (aceita "true"/"sim"/1)."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str | int | float):
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "sim"}
        return bool(value)
    return default


class SqliteMemory:
    """Memória de longo prazo + histórico da conversa persistida em SQLite."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_text_chars: int = DEFAULT_MAX_TEXT_CHARS,
        max_turn_chars: int = DEFAULT_MAX_TURN_CHARS,
        dedup_threshold: float = DEFAULT_DEDUP_THRESHOLD,
        dedup_scan_limit: int = 2000,
        fts: bool = True,
        embedder: Embedder | None = None,
    ) -> None:
        self._shared_db = str(path) == ":memory:"
        self._path: str | Path = ":memory:" if self._shared_db else Path(path).expanduser()
        self.max_text_chars = max(1, int(max_text_chars))
        self.max_turn_chars = max(1, int(max_turn_chars))
        self.dedup_threshold = min(0.99, max(0.5, float(dedup_threshold)))
        self._dedup_scan_limit = max(1, int(dedup_scan_limit))
        self._embedder = embedder
        self._lock = threading.RLock()
        self._local = threading.local()
        self._connections: list[sqlite3.Connection] = []
        self._closed = False
        self._fts_enabled = False
        self._shared_conn: sqlite3.Connection | None = None

        if not self._shared_db:
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        if self._shared_db:
            self._shared_conn = self._connect()
            self._connections.append(self._shared_conn)

        conn = self._conn()
        self.schema_version = apply_schema(conn)
        if fts:
            self._fts_enabled = enable_fts(conn)
        else:
            log.warning("FTS5 desativado; a busca da memória usará LIKE (mais lenta)")
        log.info(
            "memória aberta em %s (esquema v%s, fts=%s)",
            self._path,
            self.schema_version,
            self._fts_enabled,
        )

    # ------------------------------------------------------------------ infra

    @property
    def path(self) -> str | Path:
        """Arquivo do banco (ou ``":memory:"``)."""
        return self._path

    @property
    def fts_enabled(self) -> bool:
        """``True`` quando a busca usa FTS5/BM25; ``False`` = fallback LIKE."""
        return self._fts_enabled

    @property
    def embedder(self) -> Embedder | None:
        """Embedder injetado (``None`` = desligado, o padrão)."""
        return self._embedder

    def _connect(self) -> sqlite3.Connection:
        """Abre uma conexão nova (autocommit; pragmas de segurança/lentidão)."""
        if self._shared_db:
            conn = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
        else:
            conn = sqlite3.connect(str(self._path), isolation_level=None, timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error as exc:  # pragma: no cover - depende do sistema de arquivos
            log.debug("não consegui aplicar pragmas em %s: %s", self._path, exc)
        return conn

    def _conn(self) -> sqlite3.Connection:
        """Conexão da thread atual (arquivo) ou a conexão compartilhada (``:memory:``)."""
        if self._closed:
            raise RuntimeError("memória fechada")
        if self._shared_db:
            if self._shared_conn is None:  # pragma: no cover - defensivo
                raise RuntimeError("conexão da memória não inicializada")
            return self._shared_conn
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
            with self._lock:
                self._connections.append(conn)
        return conn

    @contextmanager
    def _guard(self, write: bool) -> Iterator[sqlite3.Connection]:
        """Fornece a conexão; serializa escritas (e tudo, no banco ``:memory:``)."""
        if write or self._shared_db:
            with self._lock:
                yield self._conn()
        else:
            yield self._conn()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """Transação atômica (``BEGIN IMMEDIATE``) com rollback em qualquer erro."""
        with self._guard(write=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    def close(self) -> None:
        """Fecha todas as conexões abertas por esta instância (idempotente)."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            connections, self._connections = self._connections, []
        for conn in connections:
            try:
                conn.close()
            except sqlite3.Error:  # pragma: no cover - defensivo
                log.debug("erro ao fechar conexão da memória", exc_info=True)

    def __enter__(self) -> SqliteMemory:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self.close()
        return False

    # ------------------------------------------------------------ validações

    @staticmethod
    def _clamp(value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return DEFAULT_IMPORTANCE
        if not math.isfinite(number):
            return DEFAULT_IMPORTANCE
        return max(0.0, min(1.0, number))

    @staticmethod
    def _parse_tags(raw: Any) -> tuple[str, ...]:
        """Lê a coluna ``tags`` (JSON) de volta para tupla."""
        if not raw:
            return ()
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return ()
        if not isinstance(value, list):
            return ()
        return tuple(str(item) for item in value)

    def _prepare_text(self, text: Any) -> str:
        """Redige segredos e valida o texto antes de qualquer gravação."""
        if text is None or not str(text).strip():
            raise ValueError("texto vazio: nada a guardar na memória")
        prepared = redact_secrets(str(text)).strip()
        if not prepared:
            raise ValueError("texto vazio após redação de segredos")
        if len(prepared) > self.max_text_chars:
            raise ValueError(
                f"texto muito longo ({len(prepared)} > {self.max_text_chars} caracteres); "
                "use summarize_old_turns ou divida o conteúdo"
            )
        return prepared

    @staticmethod
    def _check_kind(kind: Any) -> str:
        value = str(kind or "fact").strip().lower()
        if value not in VALID_KINDS:
            raise ValueError(f"kind inválido: {kind!r}; use um de {VALID_KINDS}")
        return value

    @staticmethod
    def _check_session(session_id: Any) -> str:
        value = str(session_id or "").strip()
        if not value:
            raise ValueError("session_id vazio")
        return value

    # ------------------------------------------------------------ embeddings

    def _embed_raw(self, text: str) -> list[float] | None:
        if self._embedder is None:
            return None
        try:
            vector = self._embedder.embed(text)
        except Exception as exc:  # noqa: BLE001 - embedder é código de terceiros
            log.warning("embedder falhou (%s); seguindo sem vetor", exc)
            return None
        return [float(v) for v in vector] if vector else None

    def _embed(self, text: str) -> bytes | None:
        vector = self._embed_raw(text)
        if vector is None:
            return None
        try:
            return pack_vector(vector)
        except ValueError as exc:
            log.warning("vetor de embedding inválido (%s); item guardado sem vetor", exc)
            return None

    # -------------------------------------------------------- CRUD de itens

    def remember(
        self,
        text: str,
        *,
        kind: str = "fact",
        tags: tuple = (),
        importance: float | None = None,
    ) -> str:
        """Guarda um item (deduplicando) e devolve o id.

        Levanta ``ValueError`` para texto vazio, longo demais ou ``kind`` inválido.
        """
        prepared = self._prepare_text(text)
        norm = normalize(prepared)
        checked_kind = self._check_kind(kind)
        tag_tuple = clean_tags(tags)
        weight = DEFAULT_IMPORTANCE if importance is None else self._clamp(importance)
        emb = self._embed(prepared)
        now = time.time()
        with self._tx() as conn:
            duplicate = self._find_duplicate(conn, norm)
            if duplicate is not None:
                item_id = self._merge_duplicate(conn, duplicate, tag_tuple, weight, emb, now)
            else:
                item_id = self._insert_item(
                    conn,
                    text=prepared,
                    norm=norm,
                    kind=checked_kind,
                    tags=tag_tuple,
                    created_at=now,
                    importance=weight,
                    emb=emb,
                )
        log.debug("remember(%s) -> %s", checked_kind, item_id)
        return item_id

    def _find_duplicate(self, conn: sqlite3.Connection, norm: str) -> sqlite3.Row | None:
        """Item com texto normalizado igual (ou quase igual) ao informado."""
        row = conn.execute(
            f"SELECT {_columns()} FROM items WHERE norm = ? LIMIT 1", (norm,)
        ).fetchone()
        if row is not None:
            return row
        candidates = conn.execute(
            f"SELECT {_columns()} FROM items ORDER BY updated_at DESC LIMIT ?",
            (self._dedup_scan_limit,),
        ).fetchall()
        for candidate in candidates:
            if similar(norm, str(candidate["norm"]), self.dedup_threshold):
                return candidate
        return None

    def _merge_duplicate(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        tags: tuple[str, ...],
        importance: float,
        emb: bytes | None,
        now: float,
    ) -> str:
        """Atualza o item existente em vez de criar outro (deduplicação)."""
        merged = tuple(dict.fromkeys(self._parse_tags(row["tags"]) + tags))
        new_importance = max(float(row["importance"]), importance)
        conn.execute(
            "UPDATE items SET tags = ?, updated_at = ?, importance = ?, emb = COALESCE(?, emb) "
            "WHERE id = ?",
            (
                json.dumps(list(merged), ensure_ascii=False),
                now,
                new_importance,
                emb,
                row["id"],
            ),
        )
        log.debug("deduplicação: item %s atualizado", row["id"])
        return str(row["id"])

    def _insert_item(
        self,
        conn: sqlite3.Connection,
        *,
        text: str,
        norm: str,
        kind: str,
        tags: tuple[str, ...],
        created_at: float,
        importance: float,
        emb: bytes | None,
        item_id: str | None = None,
    ) -> str:
        """Grava um item novo (com retry raro de colisão de id)."""
        for attempt in range(3):
            candidate = item_id or uuid.uuid4().hex[:16]
            try:
                conn.execute(
                    "INSERT INTO items (id, text, norm, kind, tags, created_at, updated_at,"
                    " last_used_at, use_count, importance, emb)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                    (
                        candidate,
                        text,
                        norm,
                        kind,
                        json.dumps(list(tags), ensure_ascii=False),
                        created_at,
                        created_at,
                        created_at,
                        importance,
                        emb,
                    ),
                )
            except sqlite3.IntegrityError:
                if attempt == 2:
                    raise
                item_id = None
                continue
            return candidate
        raise sqlite3.IntegrityError("não consegui gerar um id único")  # pragma: no cover

    def forget(self, item_id: str) -> bool:
        """Apaga um item pelo id; devolve ``False`` se não existir."""
        if not item_id:
            return False
        with self._tx() as conn:
            cursor = conn.execute("DELETE FROM items WHERE id = ?", (str(item_id),))
            removed = cursor.rowcount > 0
        if not removed:
            log.debug("forget: item %s não encontrado", item_id)
        return removed

    def get(self, item_id: str) -> MemoryItem | None:
        """Item pelo id (leitura pura; ``None`` se não existir)."""
        if not item_id:
            return None
        with self._guard(write=False) as conn:
            row = conn.execute(
                f"SELECT {_columns()} FROM items WHERE id = ?", (str(item_id),)
            ).fetchone()
        return self._to_item(row) if row is not None else None

    def count(self) -> int:
        """Quantidade de itens na memória."""
        with self._guard(write=False) as conn:
            row = conn.execute("SELECT count(*) FROM items").fetchone()
        return int(row[0]) if row else 0

    # -------------------------------------------------------------- recall

    def recall(self, query: str, k: int = 5, kinds: tuple | None = None) -> list[MemoryItem]:
        """Os ``k`` itens mais relevantes para ``query`` (BM25 + recência + importância).

        Consulta vazia devolve os itens mais importantes. O texto é normalizado:
        "configuração" encontra "configuracao". Itens devolvidos têm ``use_count``
        incrementado (frequência de uso sobe um pouco na próxima pontuação).
        """
        try:
            limit = int(k)
        except (TypeError, ValueError):
            limit = 5
        if limit <= 0:
            return []
        kind_tuple: tuple[str, ...] = ()
        if kinds is not None:
            if isinstance(kinds, str | bytes):
                kind_tuple = (str(kinds),)
            else:
                try:
                    kind_tuple = tuple(str(item) for item in kinds)
                except TypeError:
                    kind_tuple = ()
            if not kind_tuple:
                return []

        terms = tokenize(query or "")
        query_norm = normalize(query or "")
        now = time.time()

        candidates: list[tuple[sqlite3.Row, float]] = []
        if not terms:
            candidates = [(row, 0.0) for row in self._top_rows(kind_tuple, limit)]
        else:
            if self._fts_enabled:
                candidates = self._fts_rows(terms, kind_tuple)
            if not candidates:
                candidates = self._like_rows(terms, query_norm, kind_tuple)

        query_vec = self._embed_raw(str(query or "")) if terms else None
        scored = self._score(candidates, now, query_vec)
        top = scored[:limit]
        if not top:
            return []

        item_ids = [str(row["id"]) for row, _ in top]
        self._bump_usage(item_ids)
        return [self._to_item(row, score) for row, score in top]

    def _top_rows(self, kinds: tuple[str, ...], limit: int) -> list[sqlite3.Row]:
        """Sem consulta: os itens de maior importância (mais recentes empatando)."""
        sql = f"SELECT {_columns()} FROM items"
        params: list[Any] = []
        if kinds:
            sql += " WHERE kind IN (" + ",".join("?" for _ in kinds) + ")"
            params.extend(kinds)
        sql += " ORDER BY importance DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        with self._guard(write=False) as conn:
            return list(conn.execute(sql, params).fetchall())

    def _fts_rows(
        self, terms: list[str], kinds: tuple[str, ...]
    ) -> list[tuple[sqlite3.Row, float]]:
        """Busca FTS5; relevância = BM25 normalizado (min-max) entre os candidatos."""
        match = " ".join(f'"{term}"*' for term in terms[:_MAX_QUERY_TERMS])
        sql = (
            f"SELECT {_columns('i.')}, bm25(items_fts) AS bm "
            "FROM items_fts JOIN items i ON i.id = items_fts.item_id "
            "WHERE items_fts MATCH ?"
        )
        params: list[Any] = [match]
        if kinds:
            sql += " AND i.kind IN (" + ",".join("?" for _ in kinds) + ")"
            params.extend(kinds)
        sql += " ORDER BY bm LIMIT ?"
        params.append(_CANDIDATE_LIMIT)
        with self._guard(write=False) as conn:
            rows = list(conn.execute(sql, params).fetchall())
        if not rows:
            return []
        values = [float(row["bm"]) for row in rows]
        best, worst = min(values), max(values)
        if worst - best < _BM25_EPSILON:
            return [(row, 1.0) for row in rows]
        return [(row, (worst - float(row["bm"])) / (worst - best)) for row in rows]

    def _like_rows(
        self, terms: list[str], query_norm: str, kinds: tuple[str, ...]
    ) -> list[tuple[sqlite3.Row, float]]:
        """Fallback sem FTS5: ``LIKE`` sobre o texto normalizado, pontuação simples."""
        clauses = ["norm LIKE ? ESCAPE '\\'"] * len(terms)
        params: list[Any] = [f"%{escape_like(term)}%" for term in terms]
        sql = f"SELECT {_columns()} FROM items WHERE " + " AND ".join(clauses)
        if kinds:
            sql += " AND kind IN (" + ",".join("?" for _ in kinds) + ")"
            params.extend(kinds)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(_CANDIDATE_LIMIT)
        with self._guard(write=False) as conn:
            rows = list(conn.execute(sql, params).fetchall())
        scored: list[tuple[sqlite3.Row, float]] = []
        for row in rows:
            norm = str(row["norm"])
            occurrences = sum(norm.count(term) for term in terms)
            relevance = min(1.0, 0.4 + 0.2 * occurrences)
            if query_norm and query_norm in norm:
                relevance = 1.0
            scored.append((row, relevance))
        return scored

    def _score(
        self,
        candidates: list[tuple[sqlite3.Row, float]],
        now: float,
        query_vec: list[float] | None,
    ) -> list[tuple[sqlite3.Row, float]]:
        """Combina relevância, recência, importância e frequência de uso."""
        scored: list[tuple[sqlite3.Row, float]] = []
        for row, relevance in candidates:
            rel = relevance
            if query_vec is not None:
                vector = unpack_vector(row["emb"])
                if vector:
                    rel = (1 - _EMBED_BLEND) * rel + _EMBED_BLEND * max(
                        0.0, cosine(query_vec, vector)
                    )
            age_days = max(0.0, now - float(row["updated_at"])) / 86400.0
            recency = 0.5 ** (age_days / _RECENCY_HALF_LIFE_DAYS)
            importance = self._clamp(row["importance"])
            uses = min(
                1.0, math.log2(1.0 + max(0, int(row["use_count"]))) / _USE_LOG_DIVISOR
            )
            score = (
                _W_RELEVANCE * rel
                + _W_RECENCY * recency
                + _W_IMPORTANCE * importance
                + _W_USE * uses
            )
            scored.append((row, score))
        scored.sort(
            key=lambda pair: (pair[1], float(pair[0]["created_at"]), str(pair[0]["id"])),
            reverse=True,
        )
        return scored

    def _bump_usage(self, item_ids: list[str]) -> None:
        """Registra que os itens foram usados (sobe um pouco no ranking futuro)."""
        if not item_ids:
            return
        now = time.time()
        with self._tx() as conn:
            conn.executemany(
                "UPDATE items SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
                [(now, item_id) for item_id in item_ids],
            )

    @staticmethod
    def _to_item(row: sqlite3.Row, score: float = 0.0) -> MemoryItem:
        return MemoryItem(
            id=str(row["id"]),
            text=str(row["text"]),
            kind=str(row["kind"]),
            score=float(score),
            created_at=float(row["created_at"]),
            tags=SqliteMemory._parse_tags(row["tags"]),
        )

    # ------------------------------------------------------------ conversa

    def add_turn(self, session_id: str, role: str, content: str) -> None:
        """Grava um turno da conversa (secrets redigidos; vazio é ignorado)."""
        session = self._check_session(session_id)
        checked_role = str(role or "").strip().lower()
        if checked_role not in VALID_ROLES:
            raise ValueError(f"papel inválido: {role!r}; use um de {VALID_ROLES}")
        text = redact_secrets(str(content or ""))
        text = truncate_text(text, self.max_turn_chars)
        if not text.strip():
            log.debug("add_turn ignorando conteúdo vazio (%s/%s)", session, checked_role)
            return
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO turns (session_id, role, content, ts) VALUES (?, ?, ?, ?)",
                (session, checked_role, text, time.time()),
            )

    def recent_turns(self, session_id: str, n: int = 10) -> list[ChatMessage]:
        """Últimos ``n`` turnos da sessão, em ordem cronológica (mais antigo primeiro)."""
        try:
            limit = int(n)
        except (TypeError, ValueError):
            limit = 10
        if limit <= 0:
            return []
        session = str(session_id or "")
        if not session:
            return []
        with self._guard(write=False) as conn:
            rows = list(
                conn.execute(
                    "SELECT role, content FROM turns WHERE session_id = ? "
                    "ORDER BY seq DESC LIMIT ?",
                    (session, limit),
                ).fetchall()
            )
        return [
            ChatMessage(role=str(row["role"]), content=str(row["content"]))
            for row in reversed(rows)
        ]

    def summarize_old_turns(
        self, session_id: str, llm: LLMClient, keep_last: int = 10
    ) -> str | None:
        """Resume turnos antigos em um item ``episode`` e os remove.

        Chama o LLM só quando a conversa passa de ``keep_last`` turnos. Em falha
        do LLM devolve ``None`` e mantém os turnos (nada se perde).
        """
        if llm is None:
            raise ValueError("llm obrigatório para resumir turnos")
        try:
            keep = max(0, int(keep_last))
        except (TypeError, ValueError):
            keep = 10
        session = self._check_session(session_id)

        with self._guard(write=False) as conn:
            rows = list(
                conn.execute(
                    "SELECT seq, role, content FROM turns WHERE session_id = ? ORDER BY seq",
                    (session,),
                ).fetchall()
            )
        if len(rows) <= keep:
            return None
        old_turns = rows[: len(rows) - keep]
        keep_from_seq = rows[len(rows) - keep]["seq"] if keep > 0 else None

        transcript = "\n".join(
            f"[{row['role']}] {row['content']}" for row in old_turns
        )
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "Você é o módulo de memória da A.R.I.S. Resuma os turnos antigos da "
                    "conversa em um episódio curto (2 a 4 frases), em português do Brasil, "
                    "mantendo fatos, decisões, preferências e lições aprendidas. "
                    "Responda apenas com o resumo."
                ),
            ),
            ChatMessage(role="user", content=truncate_text(transcript, 6000)),
        ]
        try:
            response = llm.chat(messages, difficulty="easy", max_tokens=400, temperature=0.3)
        except Exception as exc:  # noqa: BLE001 - falha de LLM não pode perder turnos
            log.warning("falha ao resumir turnos de %s: %s", session, exc)
            return None
        summary = redact_secrets(str(response.message.content or "")).strip()
        if not summary:
            log.warning("LLM devolveu resumo vazio; turnos de %s mantidos", session)
            return None
        summary = truncate_text(summary, self.max_text_chars)

        now = time.time()
        with self._tx() as conn:
            item_id = self._insert_item(
                conn,
                text=summary,
                norm=normalize(summary),
                kind="episode",
                tags=clean_tags(("resumo", session)),
                created_at=now,
                importance=DEFAULT_IMPORTANCE,
                emb=self._embed(summary),
            )
            if keep_from_seq is None:
                conn.execute("DELETE FROM turns WHERE session_id = ?", (session,))
            else:
                conn.execute(
                    "DELETE FROM turns WHERE session_id = ? AND seq < ?",
                    (session, keep_from_seq),
                )
        log.debug(
            "summarize_old_turns(%s): %s turnos -> episode %s", session, len(old_turns), item_id
        )
        return item_id

    # ------------------------------------------------------- importar/exportar

    @staticmethod
    def _parse_ts(value: Any) -> float | None:
        """Aceita epoch numérico ou string ISO 8601; devolve ``None`` se não der."""
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int | float):
            number = float(value)
            return number if math.isfinite(number) and number > 0 else None
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            try:
                number = float(raw)
            except ValueError:
                number = None
            if number is not None and math.isfinite(number) and number > 0:
                return number
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return None
            try:
                return parsed.timestamp()
            except (ValueError, OSError, OverflowError):  # pragma: no cover - defensivo
                return None
        return None

    def import_records(self, records: Iterable[dict]) -> dict[str, int]:
        """Importa registros da memória antiga (Parte 8); idempotente.

        Cada registro: ``text`` (obrigatório) e opcionalmente ``kind``, ``tags``,
        ``created_at`` e ``importance``. Rodar duas vezes não duplica (dedup exato
        por texto normalizado; sem semelhança aproximada aqui, para não fundir
        registros diferentes). Devolve contagens ``created``/``updated``/``skipped``.
        """
        stats = {"created": 0, "updated": 0, "skipped": 0}
        if records is None:
            return stats
        now = time.time()
        pending: list[tuple[str, str, str, tuple[str, ...], float, float]] = []
        for record in records:
            if not isinstance(record, dict):
                stats["skipped"] += 1
                continue
            raw_text = record.get("text")
            if not isinstance(raw_text, str) or not raw_text.strip():
                stats["skipped"] += 1
                continue
            text = redact_secrets(raw_text).strip()
            if not text:
                stats["skipped"] += 1
                continue
            if len(text) > self.max_text_chars:
                text = truncate_text(text, self.max_text_chars)
            kind = str(record.get("kind") or "fact").strip().lower()
            if kind not in VALID_KINDS:
                log.debug("import_records: kind desconhecido %r; usando fact", kind)
                kind = "fact"
            created_at = self._parse_ts(record.get("created_at")) or now
            importance = self._clamp(record.get("importance", DEFAULT_IMPORTANCE))
            pending.append(
                (text, normalize(text), kind, clean_tags(record.get("tags")), created_at, importance)
            )

        if not pending:
            return stats

        with self._tx() as conn:
            for text, norm, kind, tags, created_at, importance in pending:
                row = conn.execute(
                    "SELECT id, tags, importance, updated_at FROM items WHERE norm = ? LIMIT 1",
                    (norm,),
                ).fetchone()
                if row is not None:
                    merged = tuple(dict.fromkeys(self._parse_tags(row["tags"]) + tags))
                    conn.execute(
                        "UPDATE items SET tags = ?, importance = ?, updated_at = ? WHERE id = ?",
                        (
                            json.dumps(list(merged), ensure_ascii=False),
                            max(float(row["importance"]), importance),
                            max(float(row["updated_at"]), created_at),
                            row["id"],
                        ),
                    )
                    stats["updated"] += 1
                    continue
                self._insert_item(
                    conn,
                    text=text,
                    norm=norm,
                    kind=kind,
                    tags=tags,
                    created_at=created_at,
                    importance=importance,
                    emb=None,
                )
                stats["created"] += 1
        log.info(
            "import_records: %s criados, %s atualizados, %s pulados",
            stats["created"],
            stats["updated"],
            stats["skipped"],
        )
        return stats

    def export_all(self, *, include_turns: bool = True) -> str:
        """Exporta tudo como JSON (itens + turnos, sem vetores de embedding)."""
        with self._guard(write=False) as conn:
            item_rows = list(
                conn.execute(
                    "SELECT id, text, kind, tags, created_at, updated_at, last_used_at,"
                    " use_count, importance FROM items ORDER BY created_at"
                ).fetchall()
            )
            items = [
                {
                    "id": str(row["id"]),
                    "text": str(row["text"]),
                    "kind": str(row["kind"]),
                    "tags": list(self._parse_tags(row["tags"])),
                    "created_at": float(row["created_at"]),
                    "updated_at": float(row["updated_at"]),
                    "last_used_at": float(row["last_used_at"]),
                    "use_count": int(row["use_count"]),
                    "importance": float(row["importance"]),
                }
                for row in item_rows
            ]
            turns: list[dict] = []
            if include_turns:
                turn_rows = list(
                    conn.execute(
                        "SELECT session_id, role, content, ts FROM turns ORDER BY seq"
                    ).fetchall()
                )
                turns = [
                    {
                        "session_id": str(row["session_id"]),
                        "role": str(row["role"]),
                        "content": str(row["content"]),
                        "ts": float(row["ts"]),
                    }
                    for row in turn_rows
                ]
        payload = {
            "formato": "aris_agent.memoria.v1",
            "schema_version": self.schema_version,
            "exportado_em": time.time(),
            "itens": items,
            "turnos": turns,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)

    def wipe_all(self, confirm_token: str) -> int:
        """Apaga itens e turnos; exige o token ``WIPE_CONFIRM_TOKEN``. Devolve o nº de itens."""
        if confirm_token != WIPE_CONFIRM_TOKEN:
            raise ValueError(
                f"wipe_all exige o token de confirmação {WIPE_CONFIRM_TOKEN!r} "
                "(isso apaga toda a memória)"
            )
        with self._tx() as conn:
            row = conn.execute("SELECT count(*) FROM items").fetchone()
            total = int(row[0]) if row else 0
            conn.execute("DELETE FROM items")
            conn.execute("DELETE FROM turns")
        log.warning("wipe_all: memória apagada (%s itens)", total)
        return total


def _config_int(section: dict, key: str, default: int) -> int:
    if key not in section:
        return default
    try:
        return int(section[key])
    except (TypeError, ValueError):
        log.warning("seção memory: %r não é inteiro; usando %s", section[key], default)
        return default


def _config_float(section: dict, key: str, default: float) -> float:
    if key not in section:
        return default
    try:
        return float(section[key])
    except (TypeError, ValueError):
        log.warning("seção memory: %r não é número; usando %s", section[key], default)
        return default


def open_memory(cfg: AgentConfig | None = None) -> SqliteMemory:
    """Abre a memória padrão em ``<data_dir>/memory.sqlite3`` (seção ``memory`` da config).

    Chaves aceitas em ``aris_agent.json`` → ``sections.memory``: ``path``,
    ``max_text_chars``, ``max_turn_chars``, ``dedup_threshold`` e ``fts``.
    """
    config = cfg if cfg is not None else load_config()
    section = dict(config.section("memory"))
    raw_path = section.get("path")
    if raw_path:
        path: Path = Path(str(raw_path)).expanduser()
    else:
        path = Path(config.data_dir) / "memory.sqlite3"
    return SqliteMemory(
        path,
        max_text_chars=_config_int(section, "max_text_chars", DEFAULT_MAX_TEXT_CHARS),
        max_turn_chars=_config_int(section, "max_turn_chars", DEFAULT_MAX_TURN_CHARS),
        dedup_threshold=_config_float(section, "dedup_threshold", DEFAULT_DEDUP_THRESHOLD),
        fts=_as_bool(section.get("fts"), True),
    )


__all__ = [
    "DEFAULT_DEDUP_THRESHOLD",
    "DEFAULT_IMPORTANCE",
    "DEFAULT_MAX_TEXT_CHARS",
    "VALID_KINDS",
    "VALID_ROLES",
    "WIPE_CONFIRM_TOKEN",
    "SqliteMemory",
    "open_memory",
]
