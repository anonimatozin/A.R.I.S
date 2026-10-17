#!/usr/bin/env python3
"""Inventário somente-leitura de uma pasta (skill organizar-arquivos).

Uso:
    python inventariar.py [pasta] [--profundidade N] [--top N]

Mostra subpastas, quantidade de arquivos e tamanho por subpasta. Não move,
não renomeia e não apaga nada.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

LIMITE_ARQUIVOS = 50_000


def formatar_tamanho(total: int) -> str:
    """Converte bytes em texto legível (KB/MB/GB)."""
    valor = float(total)
    for unidade in ("B", "KB", "MB", "GB", "TB"):
        if valor < 1024 or unidade == "TB":
            return f"{valor:.0f} {unidade}" if unidade == "B" else f"{valor:.1f} {unidade}"
        valor /= 1024
    return f"{valor:.1f} TB"


def coletar(raiz: Path, profundidade: int) -> list[tuple[Path, int, int]]:
    """Devolve lista de (pasta, arquivos, bytes) até a profundidade pedida."""
    linhas: list[tuple[Path, int, int]] = []
    contagem = 0
    for pasta, subpastas, arquivos in raiz.walk():
        rel = pasta.relative_to(raiz)
        if len(rel.parts) > profundidade:
            subpastas[:] = []
            continue
        bytes_total = 0
        for nome in arquivos:
            contagem += 1
            if contagem > LIMITE_ARQUIVOS:
                print(f"aviso: mais de {LIMITE_ARQUIVOS} arquivos; lista truncada", file=sys.stderr)
                return linhas
            try:
                bytes_total += (pasta / nome).stat().st_size
            except OSError:
                pass
        linhas.append((rel, len(arquivos), bytes_total))
        subpastas.sort()
    return linhas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventário somente-leitura de uma pasta")
    parser.add_argument("pasta", nargs="?", default=".", help="pasta a inventariar (padrão: atual)")
    parser.add_argument("--profundidade", type=int, default=2, help="profundidade máxima (padrão 2)")
    parser.add_argument("--top", type=int, default=15, help="máximo de linhas (padrão 15)")
    args = parser.parse_args(argv)

    raiz = Path(args.pasta).expanduser()
    if not raiz.is_dir():
        print(f"pasta não encontrada: {raiz}", file=sys.stderr)
        return 2

    linhas = coletar(raiz, max(0, args.profundidade))
    print(f"inventário de {raiz}  ({len(linhas)} pastas)")
    for rel, arquivos, bytes_total in linhas[: max(1, args.top)]:
        nome = "." if str(rel) == "." else str(rel)
        print(f"{nome:<50} {arquivos:>6} arq  {formatar_tamanho(bytes_total):>10}")
    if len(linhas) > args.top:
        print(f"... {len(linhas) - args.top} pastas omitidas (use --top)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
