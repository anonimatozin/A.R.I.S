"""CLI das avaliações: ``python -m aris_agent.evals.run``.

Exemplos::

    python -m aris_agent.evals.run                       # roteirizado, tudo
    python -m aris_agent.evals.run --filter categoria=seguranca
    python -m aris_agent.evals.run --live --filter categoria=seguranca --max 5
    python -m aris_agent.evals.run --intents             # só o classificador

O modo ``--live`` usa o LLM real configurado na seção ``llm`` do
``aris_agent.json`` e é limitado por ``--max`` (controle de custo).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .intents import avaliar_classificador, classificar_regras, relatorio_markdown
from .runner import SAIDA_PADRAO, run_and_report

log = logging.getLogger("aris.agent.evals.run")


def main(argv: list[str] | None = None) -> int:
    """Roda os cenários (ou o avaliador de intenções) e grava o relatório."""
    parser = argparse.ArgumentParser(description="Avaliação da ARIS-agente")
    parser.add_argument("--live", action="store_true", help="usa o LLM real (caro)")
    parser.add_argument("--filter", default="", help="filtro, ex.: categoria=seguranca")
    parser.add_argument("--max", type=int, default=None, help="máximo de cenários")
    parser.add_argument("--out", default=str(SAIDA_PADRAO), help="pasta do relatório")
    parser.add_argument(
        "--intents", action="store_true", help="só avalia o classificador de intenções"
    )
    parser.add_argument(
        "--keep-traces", action="store_true", help="mantém os traces JSONL dos cenários"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )

    if args.intents:
        resultado = avaliar_classificador(classificar_regras)
        print(relatorio_markdown(resultado))
        return 0 if resultado["acuracia"] >= 0.9 else 1

    categoria = None
    if args.filter:
        if not args.filter.startswith("categoria="):
            print("filtro no formato esperado: categoria=<nome>", file=sys.stderr)
            return 2
        categoria = args.filter.split("=", 1)[1].strip()

    modo = "live" if args.live else "scripted"
    try:
        report = run_and_report(
            modo=modo,
            categoria=categoria,
            max_tasks=args.max,
            out_dir=Path(args.out),
            keep_traces=args.keep_traces,
        )
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    resumo = report["resumo"]
    print(
        f"{modo}: {resumo['sucessos']}/{resumo['total']} cenários ok "
        f"({resumo['taxa'] * 100:.1f}%) — relatório em {args.out}"
    )
    return 0 if resumo["taxa"] >= 0.9 else 1


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.exit(main())
