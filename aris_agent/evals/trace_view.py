"""Visualizador de traces: gera um HTML único, offline e sem dependências.

Uso::

    python -m aris_agent.evals.trace_view <arquivo.jsonl|pasta> [--out traces.html]

Lê os traces JSONL gravados pelo laço (``~/.aris_agent/traces`` ou a pasta que
você passar), aplica ``redact_secrets`` em tudo e monta uma linha do tempo
buscável: mensagens, ferramentas, argumentos, decisões de segurança, tempos e
tokens. O HTML gerado não carrega nada da internet.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import sys
from pathlib import Path

from ..contract.utils import redact_secrets

log = logging.getLogger("aris.agent.evals.trace_view")

PADRAO_SAIDA = Path.cwd() / "traces.html"

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
       margin: 0; padding: 1.5rem; line-height: 1.45; }
h1 { font-size: 1.3rem; margin: 0 0 .5rem; }
.barra { display: flex; gap: .75rem; flex-wrap: wrap; align-items: center;
         margin-bottom: 1rem; }
input[type=search] { flex: 1; min-width: 240px; padding: .5rem .7rem;
                     border: 1px solid #8884; border-radius: 6px; }
select, button { padding: .45rem .7rem; border: 1px solid #8884;
                 border-radius: 6px; background: transparent; color: inherit; }
.trace { border: 1px solid #8883; border-radius: 8px; margin-bottom: 1rem;
         overflow: hidden; }
.trace > h2 { font-size: .95rem; margin: 0; padding: .6rem .8rem;
              background: #8881; cursor: pointer; }
.evento { display: grid; grid-template-columns: 78px 150px 1fr; gap: .6rem;
          padding: .45rem .8rem; border-top: 1px solid #8882; font-size: .85rem; }
.evento .ts { color: #888; font-variant-numeric: tabular-nums; }
.evento .tipo { font-weight: 600; }
.evento pre { margin: .2rem 0 0; white-space: pre-wrap; word-break: break-word;
              font-size: .78rem; opacity: .9; }
.oculto { display: none; }
.destaque { background: #ffdb4d33; }
.contador { font-size: .85rem; opacity: .75; }
"""

_JS = """
function filtrar() {
  const termo = document.getElementById('busca').value.toLowerCase();
  const tipo = document.getElementById('tipo').value;
  let visiveis = 0;
  document.querySelectorAll('.evento').forEach(function (el) {
    const casaTexto = !termo || el.dataset.busca.includes(termo);
    const casaTipo = !tipo || el.dataset.tipo === tipo;
    const mostrar = casaTexto && casaTipo;
    el.classList.toggle('oculto', !mostrar);
    el.classList.toggle('destaque', mostrar && termo.length > 2);
    if (mostrar) visiveis++;
  });
  document.getElementById('contador').textContent = visiveis + ' eventos visíveis';
  document.querySelectorAll('.trace').forEach(function (bloco) {
    const tem = bloco.querySelector('.evento:not(.oculto)');
    bloco.classList.toggle('oculto', !tem);
  });
}
function alternar(bloco) { bloco.classList.toggle('oculto'); }
"""


def _carregar_traces(alvo: Path) -> list[tuple[str, list[dict]]]:
    """Lê os arquivos JSONL (arquivo ou pasta) e devolve ``[(nome, registros)]``."""
    if alvo.is_file():
        arquivos = [alvo]
    elif alvo.is_dir():
        arquivos = sorted(alvo.glob("*.jsonl"))
    else:
        raise FileNotFoundError(f"trace não encontrado: {alvo}")
    if not arquivos:
        raise FileNotFoundError(f"nenhum .jsonl em {alvo}")

    traces: list[tuple[str, list[dict]]] = []
    for arquivo in arquivos:
        registros: list[dict] = []
        for numero, linha in enumerate(
            arquivo.read_text(encoding="utf-8").splitlines(), start=1
        ):
            linha = linha.strip()
            if not linha:
                continue
            try:
                registros.append(json.loads(linha))
            except json.JSONDecodeError:
                log.warning("%s:%d não é JSON válido; ignorando", arquivo.name, numero)
        traces.append((arquivo.name, registros))
    return traces


def _formatar_ts(ts: object) -> str:
    try:
        return f"{float(ts):.3f}"
    except (TypeError, ValueError):
        return str(ts)


def _corpoevento(registro: dict) -> str:
    """Campos do registro (sem evento/ts) como JSON redigido e quebrável."""
    campos = {k: v for k, v in registro.items() if k not in ("evento", "ts")}
    if not campos:
        return ""
    bruto = json.dumps(campos, ensure_ascii=False, indent=2, default=str)
    return f"<pre>{html.escape(redact_secrets(bruto))}</pre>"


def gerar_html(traces: list[tuple[str, list[dict]]]) -> str:
    """Monta o HTML final com a linha do tempo de todos os traces."""
    tipos: set[str] = set()
    blocos: list[str] = []

    for nome, registros in traces:
        linhas: list[str] = []
        for registro in registros:
            tipo = str(registro.get("evento", "?"))
            tipos.add(tipo)
            ts = _formatar_ts(registro.get("ts"))
            busca = redact_secrets(
                json.dumps(registro, ensure_ascii=False, default=str)
            ).lower()
            linhas.append(
                f'<div class="evento" data-tipo="{html.escape(tipo)}" '
                f'data-busca="{html.escape(busca, quote=True)}">'
                f'<span class="ts">{html.escape(ts)}</span>'
                f'<span class="tipo">{html.escape(tipo)}</span>'
                f"<div>{_corpoevento(registro)}</div></div>"
            )
        blocos.append(
            f'<section class="trace"><h2 onclick="alternar(this.parentElement)">'
            f"{html.escape(nome)} — {len(registros)} eventos</h2>"
            + "".join(linhas)
            + "</section>"
        )

    opcoes = "".join(
        f'<option value="{html.escape(t)}">{html.escape(t)}</option>'
        for t in sorted(tipos)
    )
    total = sum(len(r) for _nome, r in traces)
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>A.R.I.S. — traces do agente</title>
<style>{_CSS}</style>
</head>
<body>
<h1>A.R.I.S. — linha do tempo das tarefas</h1>
<div class="barra">
  <input id="busca" type="search" placeholder="buscar em argumentos, mensagens, decisões..."
         oninput="filtrar()">
  <select id="tipo" onchange="filtrar()">
    <option value="">todos os eventos</option>
    {opcoes}
  </select>
  <span id="contador" class="contador">{total} eventos</span>
</div>
{"".join(blocos)}
<script>{_JS}</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    """CLI: gera o HTML a partir de um arquivo ou pasta de traces."""
    parser = argparse.ArgumentParser(
        description="Gera um HTML único com a linha do tempo dos traces JSONL."
    )
    parser.add_argument("alvo", help="arquivo .jsonl ou pasta com traces")
    parser.add_argument(
        "--out", "-o", default=str(PADRAO_SAIDA), help="arquivo HTML de saída"
    )
    args = parser.parse_args(argv)

    try:
        traces = _carregar_traces(Path(args.alvo).expanduser())
    except FileNotFoundError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    destino = Path(args.out).expanduser()
    destino.write_text(gerar_html(traces), encoding="utf-8")
    print(f"HTML gravado em {destino} ({len(traces)} trace(s))")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.exit(main())
