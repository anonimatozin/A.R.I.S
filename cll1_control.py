import socket
import json
import os
import sys
import base64

CLL1_HOST = "192.168.0.104"
CLL1_PORT = 8765


def get_token():
    token = os.getenv("CLL1_TOKEN")

    if not token:
        print("ERRO: CLL1_TOKEN não está definido.")
        return None

    return token


def send_request(request):
    token = get_token()

    if not token:
        return None

    request["token"] = token

    try:
        data = json.dumps(request, ensure_ascii=False).encode("utf-8")

        with socket.create_connection(
            (CLL1_HOST, CLL1_PORT),
            timeout=30
        ) as sock:

            sock.sendall(len(data).to_bytes(8, "big"))
            sock.sendall(data)

            size_data = sock.recv(8)

            if len(size_data) != 8:
                raise RuntimeError("Resposta inválida")

            size = int.from_bytes(size_data, "big")

            response = b""

            while len(response) < size:
                chunk = sock.recv(
                    min(65536, size - len(response))
                )

                if not chunk:
                    break

                response += chunk

        return json.loads(response.decode("utf-8"))

    except Exception as e:
        print(f"ERRO DE CONEXÃO: {e}")
        return None


def show(response):
    if response:
        print(json.dumps(
            response,
            indent=2,
            ensure_ascii=False
        ))


def ping():
    show(send_request({
        "type": "admin_ping"
    }))


def status():
    show(send_request({
        "type": "status"
    }))


def put_file(local_file, remote_file=None):
    if not os.path.isfile(local_file):
        print(f"Arquivo não encontrado: {local_file}")
        return

    if remote_file is None:
        remote_file = os.path.basename(local_file)

    with open(local_file, "rb") as f:
        content = base64.b64encode(
            f.read()
        ).decode("ascii")

    print(f"Enviando: {local_file}")

    show(send_request({
        "type": "put_file",
        "path": remote_file,
        "content": content
    }))


def mkdir(path):
    show(send_request({
        "type": "mkdir",
        "path": path
    }))


def chmod_run(path):
    show(send_request({
        "type": "chmod_run",
        "path": path
    }))


def install_service():
    show(send_request({
        "type": "install_gateway_service"
    }))


def enable_service():
    show(send_request({
        "type": "enable_gateway_service"
    }))


def restart():
    show(send_request({
        "type": "restart_gateway"
    }))


def exec_python(path):
    show(send_request({
        "type": "exec_python",
        "path": path
    }))


def usage():
    print("""
CLL1 CONTROL

Comandos:

  python cll1_control.py ping
  python cll1_control.py status

  python cll1_control.py put arquivo.py
  python cll1_control.py put arquivo.py caminho/remoto.py

  python cll1_control.py mkdir pasta
  python cll1_control.py chmod caminho/run

  python cll1_control.py exec aris_memory.py

  python cll1_control.py install-service
  python cll1_control.py enable
  python cll1_control.py restart
""")


def main():
    if len(sys.argv) < 2:
        usage()
        return

    command = sys.argv[1].lower()

    if command == "ping":
        ping()

    elif command == "status":
        status()

    elif command == "put":
        if len(sys.argv) < 3:
            print("Informe o arquivo.")
            return

        local_file = sys.argv[2]

        remote_file = (
            sys.argv[3]
            if len(sys.argv) >= 4
            else None
        )

        put_file(local_file, remote_file)

    elif command == "mkdir":
        if len(sys.argv) < 3:
            print("Informe a pasta.")
            return

        mkdir(sys.argv[2])

    elif command == "chmod":
        if len(sys.argv) < 3:
            print("Informe o arquivo run.")
            return

        chmod_run(sys.argv[2])

    elif command == "exec":
        if len(sys.argv) < 3:
            print("Informe o script Python.")
            return

        exec_python(sys.argv[2])

    elif command == "install-service":
        install_service()

    elif command == "enable":
        enable_service()

    elif command == "restart":
        restart()

    else:
        usage()


if __name__ == "__main__":
    main()