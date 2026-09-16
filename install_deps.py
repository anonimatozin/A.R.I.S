"""Script para instalar dependências no CLL1 (Termux)."""

import subprocess
import sys


def install_package(package):
    """Instala um pacote pip."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package],
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode == 0:
            print(f"✓ {package} instalado")
            return True
        else:
            print(f"✗ Falha ao instalar {package}: {result.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print(f"✗ Timeout ao instalar {package}")
        return False
    except Exception as e:
        print(f"✗ Erro ao instalar {package}: {e}")
        return False


def main():
    """Instala dependências necessárias."""
    packages = [
        "discord.py",
        "openai",
    ]

    print("Instalando dependências do CLL1...")
    print()

    success = 0
    failed = 0

    for pkg in packages:
        if install_package(pkg):
            success += 1
        else:
            failed += 1

    print()
    print(f"Resultado: {success} sucesso, {failed} falha")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
