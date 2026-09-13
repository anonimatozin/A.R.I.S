"""A.R.I.S. — Assistente de Raciocínio e Integração de Sistemas

Ponto de entrada principal do projeto.
Executa o assistente virtual em interface de terminal.
"""

import msvcrt
import os
import sys
import tempfile
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

from core.aris import Aris  # noqa: E402  (depende do sys.path acima)

_LOCK_PATH = Path(tempfile.gettempdir()) / "aris_instance.lock"
_lock_fd = None


def _acquire_instance_lock() -> bool:
    """Garante uma única instância do A.R.I.S. por máquina."""
    global _lock_fd
    try:
        _lock_fd = os.open(str(_LOCK_PATH), os.O_CREAT | os.O_RDWR)
        msvcrt.locking(_lock_fd, msvcrt.LK_NBLCK, 1)
        os.write(_lock_fd, b"A")
        return True
    except OSError:
        if _lock_fd is not None:
            os.close(_lock_fd)
            _lock_fd = None
        return False


def _release_instance_lock() -> None:
    global _lock_fd
    if _lock_fd is not None:
        try:
            os.close(_lock_fd)
        except OSError:
            pass
        _lock_fd = None


def main() -> None:
    """Função principal de inicialização."""
    if not _acquire_instance_lock():
        print("A.R.I.S. já está em execução nesta máquina. Abra a janela existente.")
        sys.exit(0)
    try:
        aris = Aris()
        aris.start()
    except KeyboardInterrupt:
        print("\nEncerrado pelo usuário.")
        sys.exit(0)
    except Exception as e:
        print(f"Erro fatal: {e}")
        sys.exit(1)
    finally:
        _release_instance_lock()


if __name__ == "__main__":
    main()
