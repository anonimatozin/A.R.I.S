#!/usr/bin/env python3
"""Verifica estrutura de servicos - versao compacta."""

import os


def main():
    prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
    service_dir = os.path.join(prefix, "var", "service")
    
    print(f"DIR: {service_dir}")
    
    if not os.path.exists(service_dir):
        print("NAO EXISTE")
        return
    
    for item in sorted(os.listdir(service_dir)):
        item_path = os.path.join(service_dir, item)
        if os.path.isdir(item_path):
            print(f"SVC: {item}")
            run_file = os.path.join(item_path, "run")
            if os.path.exists(run_file):
                with open(run_file, "r") as f:
                    content = f.read().strip()
                print(f"RUN: {content[:200]}")
            else:
                print("RUN: MISSING")


if __name__ == "__main__":
    main()
