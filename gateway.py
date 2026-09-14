import socket
import json
import os
import base64
import subprocess
import threading
import time

HOST = "0.0.0.0"
PORT = 8765
BASE_DIR = os.path.expanduser("~/cll1")
TOKEN_FILE = os.path.join(BASE_DIR, ".env")


def get_token():
    token = os.environ.get("CLL1_TOKEN")

    if token:
        return token

    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("CLL1_TOKEN="):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass

    return None


TOKEN = get_token()


def safe_path(path):
    path = os.path.normpath(path)

    if os.path.isabs(path):
        raise ValueError("Caminho absoluto não permitido")

    full = os.path.abspath(os.path.join(BASE_DIR, path))
    base = os.path.abspath(BASE_DIR)

    if full != base and not full.startswith(base + os.sep):
        raise ValueError("Caminho fora do CLL1")

    return full


def send_json(sock, data):
    raw = json.dumps(
        data,
        ensure_ascii=False
    ).encode("utf-8")

    sock.sendall(len(raw).to_bytes(8, "big"))
    sock.sendall(raw)


def recv_json(sock):
    size_data = b""

    while len(size_data) < 8:
        chunk = sock.recv(8 - len(size_data))

        if not chunk:
            raise ConnectionError("Conexão encerrada")

        size_data += chunk

    size = int.from_bytes(size_data, "big")

    if size <= 0 or size > 20 * 1024 * 1024:
        raise ValueError("Tamanho de requisição inválido")

    data = b""

    while len(data) < size:
        chunk = sock.recv(
            min(65536, size - len(data))
        )

        if not chunk:
            raise ConnectionError("Conexão encerrada")

        data += chunk

    return json.loads(data.decode("utf-8"))


def authenticate(request):
    return request.get("token") == TOKEN


def handle_request(request):
    if not authenticate(request):
        return {
            "ok": False,
            "error": "unauthorized"
        }

    command = request.get("type")

    if command == "admin_ping":
        return {
            "ok": True,
            "node": "cll-1",
            "status": "online",
            "message": "CLL1 autenticado"
        }

    if command == "status":
        result = subprocess.run(
            ["sv", "status", "cll1-gateway"],
            capture_output=True,
            text=True
        )

        return {
            "ok": True,
            "operation": "status",
            "output": (
                result.stdout.strip()
                or result.stderr.strip()
            )
        }

    if command == "mkdir":
        path = safe_path(request["path"])
        os.makedirs(path, exist_ok=True)

        return {
            "ok": True,
            "operation": "mkdir",
            "path": request["path"]
        }

    if command == "put_file":
        path = safe_path(request["path"])

        content = base64.b64decode(
            request["content"]
        )

        if len(content) > 10 * 1024 * 1024:
            return {
                "ok": False,
                "error": "file_too_large"
            }

        os.makedirs(
            os.path.dirname(path),
            exist_ok=True
        )

        with open(path, "wb") as f:
            f.write(content)

        return {
            "ok": True,
            "operation": "put_file",
            "path": request["path"],
            "size": len(content)
        }

    if command == "chmod_run":
        path = safe_path(request["path"])

        os.chmod(path, 0o700)

        return {
            "ok": True,
            "operation": "chmod_run",
            "path": request["path"]
        }

    if command == "exec_python":
        relative_path = request.get("path")

        if not relative_path:
            return {
                "ok": False,
                "error": "missing_path"
            }

        if not relative_path.endswith(".py"):
            return {
                "ok": False,
                "error": "only_python_allowed"
            }

        path = safe_path(relative_path)

        if not os.path.isfile(path):
            return {
                "ok": False,
                "error": "file_not_found",
                "path": relative_path
            }

        allowed = {
            "aris_memory.py"
        }

        if os.path.basename(path) not in allowed:
            return {
                "ok": False,
                "error": "script_not_allowed"
            }

        try:
            result = subprocess.run(
                [
                    "python",
                    path
                ],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                timeout=60
            )

            return {
                "ok": result.returncode == 0,
                "operation": "exec_python",
                "path": relative_path,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr
            }

        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "operation": "exec_python",
                "error": "timeout"
            }

    if command == "install_gateway_service":
        prefix = os.environ.get("PREFIX")

        if not prefix:
            return {
                "ok": False,
                "error": "PREFIX_not_found"
            }

        service_dir = os.path.join(
            prefix,
            "var",
            "service",
            "cll1-gateway"
        )

        run_file = os.path.join(
            service_dir,
            "run"
        )

        os.makedirs(
            service_dir,
            exist_ok=True
        )

        script = """#!/data/data/com.termux/files/usr/bin/sh
cd "$HOME/cll1" || exit 1
exec python gateway.py
"""

        with open(run_file, "w", encoding="utf-8") as f:
            f.write(script)

        os.chmod(run_file, 0o700)

        return {
            "ok": True,
            "operation": "install_gateway_service",
            "service_dir": service_dir,
            "run_file": run_file
        }

    if command == "enable_gateway_service":
        result = subprocess.run(
            ["sv-enable", "cll1-gateway"],
            capture_output=True,
            text=True
        )

        return {
            "ok": result.returncode == 0,
            "operation": "enable_gateway_service",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }

    if command == "restart_gateway":

        def restart_later():
            time.sleep(1)

            subprocess.run(
                ["sv", "restart", "cll1-gateway"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

        threading.Thread(
            target=restart_later,
            daemon=True
        ).start()

        return {
            "ok": True,
            "operation": "restart_gateway"
        }

    return {
        "ok": False,
        "error": "unknown_command"
    }


def handle_client(sock, address):
    try:
        request = recv_json(sock)
        response = handle_request(request)
        send_json(sock, response)

    except Exception as e:
        try:
            send_json(
                sock,
                {
                    "ok": False,
                    "error": str(e)
                }
            )
        except Exception:
            pass

    finally:
        sock.close()


def main():
    if not TOKEN:
        print("ERRO: CLL1_TOKEN não encontrado.")
        return

    server = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    server.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1
    )

    server.bind(
        (HOST, PORT)
    )

    server.listen(20)

    print(
        f"CLL1 Gateway online em {HOST}:{PORT}"
    )

    while True:
        client, address = server.accept()

        threading.Thread(
            target=handle_client,
            args=(client, address),
            daemon=True
        ).start()


if __name__ == "__main__":
    main()