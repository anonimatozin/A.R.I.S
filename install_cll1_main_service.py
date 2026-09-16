#!/usr/bin/env python3
"""Instala o servico cll1-main no CLL1 via gateway."""

import json
import os
import socket
import sys
import base64


def get_token():
    token = os.getenv("CLL1_TOKEN")
    if token:
        return token
    return None


def send_request(request, token):
    request["token"] = token
    data = json.dumps(request, ensure_ascii=False).encode("utf-8")
    
    with socket.create_connection(("192.168.0.106", 8765), timeout=30) as sock:
        sock.sendall(len(data).to_bytes(8, "big"))
        sock.sendall(data)
        
        size_data = sock.recv(8)
        if len(size_data) != 8:
            raise RuntimeError("Resposta invalida")
        
        size = int.from_bytes(size_data, "big")
        response = b""
        
        while len(response) < size:
            chunk = sock.recv(min(65536, size - len(response)))
            if not chunk:
                break
            response += chunk
        
        return json.loads(response.decode("utf-8"))


def main():
    token = get_token()
    if not token:
        print("ERRO: CLL1_TOKEN nao definido")
        sys.exit(1)
    
    # Script de servico cll1-main
    service_script = """#!/data/data/com.termux/files/usr/bin/sh
cd "$HOME/aris" || exit 1
export PYTHONPATH="$HOME/aris"
exec python -m cll1.main
"""
    
    # Criar diretorio do servico
    print("Criando diretorio do servico...")
    result = send_request({
        "type": "mkdir",
        "path": "../usr/var/service/cll1-main"
    }, token)
    print(f"mkdir: {result}")
    
    # Enviar script de inicializacao
    print("Enviando script de inicializacao...")
    content = base64.b64encode(service_script.encode()).decode("ascii")
    result = send_request({
        "type": "put_file",
        "path": "../usr/var/service/cll1-main/run",
        "content": content
    }, token)
    print(f"put_file: {result}")
    
    # Tornar executavel
    print("Tornando executavel...")
    result = send_request({
        "type": "chmod_run",
        "path": "../usr/var/service/cll1-main/run"
    }, token)
    print(f"chmod: {result}")
    
    print("Servico cll1-main instalado!")
    print("Para habilitar, execute no Termux:")
    print("  sv-enable cll1-main")
    print("  sv restart cll1-main")


if __name__ == "__main__":
    main()
