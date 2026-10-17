#!/usr/bin/env bash
# Atalho para iniciar/controlar os olhos da ARIS de qualquer pasta (usa o venv do projeto).
#   ./aris-eyes.sh                 inicia (tela cheia)
#   ./aris-eyes.sh --mini          inicia na miniatura
#   ./aris-eyes.sh --send toggle   comanda a instancia que ja esta rodando (use nos atalhos do desktop)
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PY="$DIR/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
cd "$DIR" && exec "$PY" -m aris_eyes "$@"
