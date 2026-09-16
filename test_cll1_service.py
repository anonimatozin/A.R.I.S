#!/usr/bin/env python3
"""Testa o servico cll1-main."""

import os
import sys


def main():
    # Obter PREFIX
    prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
    service_dir = os.path.join(prefix, "var", "service", "cll1-main")
    
    print(f"Verificando servico: {service_dir}")
    
    # Verificar se existe
    if not os.path.exists(service_dir):
        print("ERRO: Diretorio do servico nao existe")
        sys.exit(1)
    
    # Verificar run
    run_file = os.path.join(service_dir, "run")
    if not os.path.exists(run_file):
        print("ERRO: Run script nao existe")
        sys.exit(1)
    
    # Verificar permissao
    if not os.access(run_file, os.X_OK):
        print("ERRO: Run script nao e executavel")
        sys.exit(1)
    
    print("Servico configurado corretamente!")
    print()
    print("Para habilitar e iniciar, execute no Termux:")
    print("  sv-enable cll1-main")
    print("  sv start cll1-main")
    print()
    print("Para verificar status:")
    print("  sv status cll1-main")
    print()
    
    # Verificar se o diretorio aris existe
    aris_dir = os.path.expanduser("~/aris")
    if os.path.exists(aris_dir):
        print(f"Diretorio ARIS: {aris_dir} (EXISTS)")
    else:
        print(f"Diretorio ARIS: {aris_dir} (NOT FOUND)")
        print("AVISO: O diretorio ~/aris nao existe!")
    
    # Verificar se o modulo cll1.main existe
    main_file = os.path.join(aris_dir, "cll1", "main.py")
    if os.path.exists(main_file):
        print(f"Modulo cll1.main: {main_file} (EXISTS)")
    else:
        print(f"Modulo cll1.main: {main_file} (NOT FOUND)")
        print("AVISO: O modulo cll1.main nao existe!")


if __name__ == "__main__":
    main()
