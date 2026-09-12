"""A.R.I.S. - Just A Rather Very Intelligent System

Ponto de entrada principal do projeto.
Executa o assistente virtual em interface de terminal.
"""

import sys
from pathlib import Path

# Garante suporte a caracteres unicode (ex: →) mesmo fora de um terminal interativo
if sys.stdout and not sys.stdout.isatty():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and not sys.stderr.isatty():
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Adiciona o diretório raiz ao path para imports absolutos
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.aris import Aris


def main() -> None:
    """Função principal de inicialização."""
    try:
        aris = Aris()
        aris.start()
    except KeyboardInterrupt:
        print("\nEncerrado pelo usuário.")
        sys.exit(0)
    except Exception as e:
        print(f"Erro fatal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
