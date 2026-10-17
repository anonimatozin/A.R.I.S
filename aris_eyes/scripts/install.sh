#!/usr/bin/env bash
# Cria o ambiente virtual do projeto e instala o PySide6. NAO usa sudo e NAO altera o sistema.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -c "import PySide6; print('PySide6', PySide6.__version__, 'instalado')"
chmod +x aris-eyes.sh
echo
echo "Pronto. Inicie com:  ./aris-eyes.sh"
echo "Se der erro 'Could not load the Qt platform plugin xcb', veja 'Dependencias do sistema' no README.md"
