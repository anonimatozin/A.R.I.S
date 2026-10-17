"""Migração da memória antiga (``memory_entries``) para a ``SqliteMemory``.

Somente leitura no banco legado; o armazenamento antigo fica intacto.
Idempotente: usar ``SqliteMemory.import_records`` (dedup por texto) — rodar
duas vezes não duplica nada.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path

log = logging.getLogger("aris.agent.bridge.migracao")

LIMITE_REGISTROS = 5000


def caminho_memoria_antiga() -> Path | None:
    """Localiza ``aris_memory.db`` da memória antiga (env → D: → repositório)."""
    candidatos: list[Path] = []
    env = os.environ.get("ARIS_MEMORY_DIR")
    if env:
        candidatos.append(Path(env).expanduser())
    candidatos.append(Path("D:/ARIS_MEMORY"))
    candidatos.append(Path(__file__).resolve().parents[2] / "data" / "memory")
    for raiz in candidatos:
        db = raiz / "aris_memory.db"
        try:
            if db.is_file():
                return db
        except OSError:  # pragma: no cover - defensivo
            continue
    return None


def _para_epoch(valor: object) -> float | None:
    """``created_at`` legado é TEXT: tenta epoch numérico e depois ISO."""
    if valor is None:
        return None
    try:
        return float(valor)  # epoch em segundos/milissegundos
    except (TypeError, ValueError):
        pass
    try:
        from datetime import datetime

        texto = str(valor).replace("Z", "+00:00")
        momento = datetime.fromisoformat(texto)
        return momento.timestamp()
    except Exception:  # noqa: BLE001 - formato desconhecido: usa o "agora"
        return None


def _para_kind(categoria: object) -> str:
    """Mapeia a categoria legada para o ``kind`` novo (fact/preference/lesson)."""
    base = str(categoria or "").lower()
    if "profile" in base or "perfil" in base or "prefer" in base:
        return "preference"
    if "lesson" in base or "licao" in base or "lição" in base:
        return "lesson"
    if "episode" in base:
        return "episode"
    return "fact"


def _para_tags(bruto: object) -> tuple[str, ...]:
    if not isinstance(bruto, str) or not bruto.strip():
        return ()
    try:
        dados = json.loads(bruto)
    except (ValueError, TypeError):
        return ()
    if isinstance(dados, list):
        return tuple(str(t) for t in dados if str(t).strip())
    return ()


def _montar_texto(titulo: object, conteudo: object) -> str:
    t = str(titulo or "").strip()
    c = str(conteudo or "").strip()
    if t and c:
        return c if t.lower() in c.lower() else f"{t}: {c}"
    return c or t


def importar_memoria_antiga(
    memoria_sqlite,
    caminho: Path | str | None = None,
    *,
    limite: int = LIMITE_REGISTROS,
) -> dict[str, int] | None:
    """Importa ``memory_entries`` na ``SqliteMemory``; idempotente.

    Devolve as contagens do ``import_records`` (``created/updated/skipped``),
    ou ``None`` quando não há banco legado / algo falhou (nunca exceção).
    """
    db = Path(caminho) if caminho is not None else caminho_memoria_antiga()
    if db is None or not db.is_file():
        log.info("memória antiga não encontrada; migração pulada")
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            linhas = con.execute(
                "SELECT title, content, category, tags, created_at"
                " FROM memory_entries"
                " ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limite)),),
            ).fetchall()
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001 - schema/tabela diferente: avisa e sai
        log.warning("não consegui ler a memória antiga (%s): %s", db, exc)
        return None

    registros: list[dict] = []
    for titulo, conteudo, categoria, tags, criado in linhas:
        texto = _montar_texto(titulo, conteudo)
        if not texto:
            continue
        registro: dict = {"text": texto, "kind": _para_kind(categoria)}
        tags_novas = _para_tags(tags)
        if tags_novas:
            registro["tags"] = list(tags_novas)
        epoch = _para_epoch(criado)
        if epoch:
            registro["created_at"] = epoch if epoch < time.time() * 10_000 else epoch / 1000
        registros.append(registro)

    if not registros:
        log.info("memória antiga vazia (%s)", db)
        return {"created": 0, "updated": 0, "skipped": 0}
    try:
        stats = memoria_sqlite.import_records(registros)
    except Exception as exc:  # noqa: BLE001
        log.warning("importação da memória antiga falhou: %s", exc)
        return None
    log.info("memória antiga importada em %s: %s", db, stats)
    return dict(stats)
