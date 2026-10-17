"""Esquema do SQLite da memória: tabelas, índices, migrações e FTS5.

Migrações simples: cada passo é uma tupla de ``CREATE ... IF NOT EXISTS``
identificada pela versão nova; a versão fica em ``meta``. Se o banco tiver uma
versão mais nova que o código, ``apply_schema`` recusa em vez de quebrar dados.
"""

from __future__ import annotations

import logging
import sqlite3

log = logging.getLogger("aris.agent.memory.schema")

#: Versão do esquema que este código sabe escrever.
SCHEMA_VERSION = 1

#: Passo de migração: versão final -> DDL aplicado (idempotente, ``IF NOT EXISTS``).
_MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        """
        CREATE TABLE IF NOT EXISTS items (
            id            TEXT PRIMARY KEY,
            text          TEXT NOT NULL,
            norm          TEXT NOT NULL,
            kind          TEXT NOT NULL,
            tags          TEXT NOT NULL DEFAULT '[]',
            created_at    REAL NOT NULL,
            updated_at    REAL NOT NULL,
            last_used_at  REAL NOT NULL,
            use_count     INTEGER NOT NULL DEFAULT 0,
            importance    REAL NOT NULL DEFAULT 0.5,
            emb           BLOB
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_items_norm ON items(norm)",
        "CREATE INDEX IF NOT EXISTS idx_items_kind ON items(kind)",
        "CREATE INDEX IF NOT EXISTS idx_items_updated ON items(updated_at)",
        """
        CREATE TABLE IF NOT EXISTS turns (
            seq        INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role       TEXT NOT NULL,
            content    TEXT NOT NULL,
            ts         REAL NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, seq)",
    ),
}

_FTS_DDL = (
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
        text, item_id UNINDEXED, tokenize='unicode61 remove_diacritics 2'
    )
    """,
    # remove_diacritics 2: "configuração" casa com "configuracao".
    """
    CREATE TRIGGER IF NOT EXISTS items_fts_ai AFTER INSERT ON items BEGIN
        INSERT INTO items_fts(rowid, text, item_id) VALUES (new.rowid, new.text, new.id);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS items_fts_ad AFTER DELETE ON items BEGIN
        DELETE FROM items_fts WHERE item_id = old.id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS items_fts_au AFTER UPDATE ON items BEGIN
        DELETE FROM items_fts WHERE item_id = old.id;
        INSERT INTO items_fts(rowid, text, item_id) VALUES (new.rowid, new.text, new.id);
    END
    """,
)


def _get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return str(row[0]) if row else None


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def stored_version(conn: sqlite3.Connection) -> int | None:
    """Versão gravada no banco ou ``None`` se o banco ainda não existe."""
    try:
        raw = _get_meta(conn, "schema_version")
    except sqlite3.OperationalError:
        return None
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        log.warning("schema_version inválida no meta: %r", raw)
        return None


def apply_schema(conn: sqlite3.Connection) -> int:
    """Cria/atualiza as tabelas da memória; devolve a versão final do esquema."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    current = stored_version(conn)
    if current is not None and current > SCHEMA_VERSION:
        raise RuntimeError(
            f"banco de memória com esquema v{current}, mas este código só sabe até "
            f"v{SCHEMA_VERSION}; atualize o código ou apague o arquivo"
        )
    pending = range((current or 0) + 1, SCHEMA_VERSION + 1)
    for version in pending:
        for statement in _MIGRATIONS.get(version, ()):
            conn.execute(statement)
        log.debug("esquema da memória migrado para v%s", version)
    _set_meta(conn, "schema_version", str(SCHEMA_VERSION))
    return SCHEMA_VERSION


def enable_fts(conn: sqlite3.Connection) -> bool:
    """Cria a tabela FTS5 + gatilhos e faz backfill; ``False`` se não houver FTS5.

    Sem FTS5 o chamador cai para busca por ``LIKE`` (com aviso em log).
    """
    try:
        for statement in _FTS_DDL:
            conn.execute(statement)
    except sqlite3.OperationalError as exc:
        log.warning(
            "FTS5 indisponível neste SQLite (%s); busca da memória usará LIKE (mais lenta)",
            exc,
        )
        try:
            conn.execute("DROP TABLE IF EXISTS items_fts")
        except sqlite3.Error:  # pragma: no cover - defensivo
            pass
        return False
    try:
        n_items = conn.execute("SELECT count(*) FROM items").fetchone()[0]
        n_fts = conn.execute("SELECT count(*) FROM items_fts").fetchone()[0]
        if n_items and not n_fts:
            conn.execute(
                "INSERT INTO items_fts(rowid, text, item_id) "
                "SELECT rowid, text, id FROM items"
            )
            log.debug("backfill do FTS5 com %s itens", n_items)
    except sqlite3.Error as exc:
        log.warning("não consegui popular o índice FTS5 (%s); usando LIKE", exc)
        return False
    return True


__all__ = ["SCHEMA_VERSION", "apply_schema", "enable_fts", "stored_version"]
