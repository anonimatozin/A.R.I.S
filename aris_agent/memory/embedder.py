"""Interface opcional de embeddings para a memória (desligada por padrão).

Nenhum modelo vem junto: a CPU do usuário é fraca. Quem quiser busca semântica
no futuro injeta um objeto que implemente :class:`Embedder` em
``SqliteMemory(path, embedder=...)``; sem isso a busca é só por texto (FTS5/LIKE).
"""

from __future__ import annotations

import math
import struct
from typing import Protocol, runtime_checkable

_HEADER = struct.Struct("<I")  # dimensão (uint32) seguida dos floats32


@runtime_checkable
class Embedder(Protocol):
    """Converte texto em vetor denso. Implementado fora do contrato (Parte 8/futuro)."""

    def embed(self, text: str) -> list[float]: ...


def pack_vector(vector: list[float] | tuple[float, ...]) -> bytes:
    """Empacota um vetor como ``uint32 dim`` + floats32 (formato próprio da coluna ``emb``)."""
    values = [float(v) for v in vector]
    if not values or len(values) > 4096:
        raise ValueError("vetor de embedding vazio ou grande demais")
    if any(not math.isfinite(v) for v in values):
        raise ValueError("vetor de embedding contém valor não finito")
    return _HEADER.pack(len(values)) + struct.pack(f"<{len(values)}f", *values)


def unpack_vector(blob: bytes | None) -> list[float] | None:
    """Lê o que :func:`pack_vector` gravou; devolve ``None`` se inválido."""
    if not blob or len(blob) < _HEADER.size:
        return None
    (dim,) = _HEADER.unpack_from(blob)
    expected = _HEADER.size + dim * 4
    if dim == 0 or len(blob) != expected:
        return None
    try:
        values = struct.unpack(f"<{dim}f", blob[_HEADER.size :])
    except struct.error:  # pragma: no cover - defensivo
        return None
    return list(values)


def cosine(a: list[float], b: list[float]) -> float:
    """Cosseno entre dois vetores; ``0.0`` se as dimensões diferem ou são nulas."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


__all__ = ["Embedder", "cosine", "pack_vector", "unpack_vector"]
