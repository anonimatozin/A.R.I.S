#!/usr/bin/env python3
"""Encontra o diretorio ARIS no CLL1."""

import os
import glob


def main():
    print("Procurando diretorio ARIS...")
    print()
    
    # Verificar locais comuns
    locations = [
        os.path.expanduser("~/aris"),
        os.path.expanduser("~/cll1"),
        os.path.expanduser("~"),
        "/data/data/com.termux/files/home/aris",
        "/data/data/com.termux/files/home/cll1",
        "/data/data/com.termux/files/home",
    ]
    
    for loc in locations:
        if os.path.exists(loc):
            print(f"  {loc}: EXISTS")
            # Verificar se tem cll1/main.py
            main_file = os.path.join(loc, "cll1", "main.py")
            if os.path.exists(main_file):
                print(f"    -> cll1/main.py: EXISTS")
            # Verificar se tem gateway.py
            gw_file = os.path.join(loc, "gateway.py")
            if os.path.exists(gw_file):
                print(f"    -> gateway.py: EXISTS")
        else:
            print(f"  {loc}: NOT FOUND")
    
    print()
    print("Procurando arquivos Python...")
    
    # Procurar por arquivos Python
    for pattern in ["**/cll1/main.py", "**/gateway.py"]:
        matches = glob.glob(pattern, recursive=True)
        for match in matches:
            print(f"  {os.path.abspath(match)}")
    
    print()
    print("Conteudo do diretorio home:")
    home = os.path.expanduser("~")
    for item in sorted(os.listdir(home)):
        item_path = os.path.join(home, item)
        if os.path.isdir(item_path):
            print(f"  {item}/")
        else:
            print(f"  {item}")


if __name__ == "__main__":
    main()
