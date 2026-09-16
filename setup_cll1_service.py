#!/usr/bin/env python3
"""Configura o servico cll1-main no Termux."""

import os
import sys


def main():
    # Obter PREFIX
    prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
    service_dir = os.path.join(prefix, "var", "service", "cll1-main")
    
    print(f"Criando servico em: {service_dir}")
    
    # Criar diretorio
    os.makedirs(service_dir, exist_ok=True)
    print("Diretorio criado")
    
    # Conteudo do script run
    run_content = """#!/data/data/com.termux/files/usr/bin/sh
cd "$HOME/aris" || exit 1
export PYTHONPATH="$HOME/aris"
exec python -m cll1.main
"""
    
    # Escrever run
    run_file = os.path.join(service_dir, "run")
    with open(run_file, "w", encoding="utf-8") as f:
        f.write(run_content)
    print(f"Run script criado: {run_file}")
    
    # Tornar executavel
    os.chmod(run_file, 0o700)
    print("Permissao executavel definida")
    
    # Verificar
    if os.path.exists(run_file):
        with open(run_file, "r") as f:
            print(f"\nConteudo do run:\n{f.read()}")
        print("Servico cl1-main configurado com sucesso!")
    else:
        print("ERRO: Run script nao foi criado")
        sys.exit(1)


if __name__ == "__main__":
    main()
