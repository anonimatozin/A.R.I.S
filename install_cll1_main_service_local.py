#!/usr/bin/env python3
"""Instala o servico cll1-main no CLL1."""

import os
import sys
import subprocess


def main():
    # Diretorio do servico
    service_dir = os.path.expanduser("~/usr/var/service/cll1-main")
    run_file = os.path.join(service_dir, "run")
    
    # Criar diretorio
    os.makedirs(service_dir, exist_ok=True)
    
    # Script de inicializacao
    script = """#!/data/data/com.termux/files/usr/bin/sh
cd "$HOME/aris" || exit 1
export PYTHONPATH="$HOME/aris"
exec python -m cll1.main
"""
    
    # Escrever script
    with open(run_file, "w", encoding="utf-8") as f:
        f.write(script)
    
    # Tornar executavel
    os.chmod(run_file, 0o700)
    
    print("Servico cll1-main instalado!")
    print(f"Diretorio: {service_dir}")
    print(f"Script: {run_file}")
    print()
    print("Para habilitar, execute no Termux:")
    print("  sv-enable cll1-main")
    print("  sv restart cll1-main")


if __name__ == "__main__":
    main()
