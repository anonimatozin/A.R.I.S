import socket
import json
import os
import base64
import subprocess
import threading
import time
import sqlite3
from datetime import datetime, timezone

HOST = "0.0.0.0"
PORT = 8765
BASE_DIR = os.path.expanduser("~/cll1")
TOKEN_FILE = os.path.join(BASE_DIR, ".env")
DB_PATH = os.path.join(BASE_DIR, "data", "aris.db")


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

    full = os.path.abspath(
        os.path.join(BASE_DIR, path)
    )

    base = os.path.abspath(BASE_DIR)

    if full != base and not full.startswith(base + os.sep):
        raise ValueError("Caminho fora do CLL1")

    return full


def send_json(sock, data):
    raw = json.dumps(
        data,
        ensure_ascii=False
    ).encode("utf-8")

    sock.sendall(
        len(raw).to_bytes(8, "big")
    )

    sock.sendall(raw)


def recv_json(sock):
    size_data = b""

    while len(size_data) < 8:
        chunk = sock.recv(
            8 - len(size_data)
        )

        if not chunk:
            raise ConnectionError(
                "Conexão encerrada"
            )

        size_data += chunk

    size = int.from_bytes(
        size_data,
        "big"
    )

    if size <= 0 or size > 20 * 1024 * 1024:
        raise ValueError(
            "Tamanho de requisição inválido"
        )

    data = b""

    while len(data) < size:
        chunk = sock.recv(
            min(65536, size - len(data))
        )

        if not chunk:
            raise ConnectionError(
                "Conexão encerrada"
            )

        data += chunk

    return json.loads(
        data.decode("utf-8")
    )


def authenticate(request):
    return request.get("token") == TOKEN


def db_connect():
    os.makedirs(
        os.path.dirname(DB_PATH),
        exist_ok=True
    )

    conn = sqlite3.connect(
        DB_PATH,
        timeout=30
    )

    conn.row_factory = sqlite3.Row

    return conn


def init_memory_db():
    with db_connect() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                importance INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)


def memory_add(request):
    content = str(
        request.get("content", "")
    ).strip()

    if not content:
        return {
            "ok": False,
            "error": "memory_content_empty"
        }

    category = str(
        request.get(
            "category",
            "general"
        )
    )

    try:
        importance = int(
            request.get(
                "importance",
                1
            )
        )
    except Exception:
        importance = 1

    importance = max(
        1,
        min(10, importance)
    )

    now = datetime.now(
        timezone.utc
    ).isoformat()

    with db_connect() as conn:

        cursor = conn.execute("""
            INSERT INTO memories
            (
                content,
                category,
                importance,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            content,
            category,
            importance,
            now,
            now
        ))

        memory_id = cursor.lastrowid

    return {
        "ok": True,
        "operation": "memory_add",
        "id": memory_id
    }


def memory_get(request):
    try:
        limit = int(
            request.get(
                "limit",
                20
            )
        )
    except Exception:
        limit = 20

    limit = max(
        1,
        min(100, limit)
    )

    with db_connect() as conn:

        rows = conn.execute("""
            SELECT
                id,
                content,
                category,
                importance,
                created_at,
                updated_at
            FROM memories
            ORDER BY
                importance DESC,
                updated_at DESC
            LIMIT ?
        """, (
            limit,
        )).fetchall()

    return {
        "ok": True,
        "operation": "memory_get",
        "memories": [
            dict(row)
            for row in rows
        ]
    }


def memory_search(request):
    query = str(
        request.get("query", "")
    ).strip()

    if not query:
        return {
            "ok": False,
            "error": "search_query_empty"
        }

    try:
        limit = int(
            request.get(
                "limit",
                20
            )
        )
    except Exception:
        limit = 20

    limit = max(
        1,
        min(100, limit)
    )

    pattern = f"%{query}%"

    with db_connect() as conn:

        rows = conn.execute("""
            SELECT
                id,
                content,
                category,
                importance,
                created_at,
                updated_at
            FROM memories
            WHERE content LIKE ?
               OR category LIKE ?
            ORDER BY
                importance DESC,
                updated_at DESC
            LIMIT ?
        """, (
            pattern,
            pattern,
            limit
        )).fetchall()

    return {
        "ok": True,
        "operation": "memory_search",
        "query": query,
        "memories": [
            dict(row)
            for row in rows
        ]
    }


def memory_state(request):
    key = str(
        request.get("key", "")
    ).strip()

    if not key:
        return {
            "ok": False,
            "error": "state_key_empty"
        }

    value = request.get("value")

    with db_connect() as conn:

        if value is not None:

            now = datetime.now(
                timezone.utc
            ).isoformat()

            conn.execute("""
                INSERT INTO system_state
                (
                    key,
                    value,
                    updated_at
                )
                VALUES (?, ?, ?)
                ON CONFLICT(key)
                DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
            """, (
                key,
                str(value),
                now
            ))

            return {
                "ok": True,
                "operation": "memory_state",
                "key": key,
                "value": str(value)
            }

        row = conn.execute("""
            SELECT value
            FROM system_state
            WHERE key = ?
        """, (
            key,
        )).fetchone()

    return {
        "ok": True,
        "operation": "memory_state",
        "key": key,
        "value": (
            row["value"]
            if row
            else None
        )
    }


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
            [
                "sv",
                "status",
                "cll1-main"
            ],
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

        path = safe_path(
            request["path"]
        )

        os.makedirs(
            path,
            exist_ok=True
        )

        return {
            "ok": True,
            "operation": "mkdir",
            "path": request["path"]
        }

    if command == "put_file":

        path = safe_path(
            request["path"]
        )

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

        with open(
            path,
            "wb"
        ) as f:
            f.write(content)

        return {
            "ok": True,
            "operation": "put_file",
            "path": request["path"],
            "size": len(content)
        }

    if command == "get_file":

        path = safe_path(
            request["path"]
        )

        if not os.path.isfile(path):
            return {
                "ok": False,
                "error": "file_not_found",
                "path": request["path"]
            }

        try:

            with open(
                path,
                "rb"
            ) as f:
                content = f.read()

            if len(content) > 10 * 1024 * 1024:
                return {
                    "ok": False,
                    "error": "file_too_large"
                }

            return {
                "ok": True,
                "operation": "get_file",
                "path": request["path"],
                "content": base64.b64encode(
                    content
                ).decode("ascii"),
                "size": len(content)
            }

        except Exception as e:

            return {
                "ok": False,
                "error": str(e)
            }

    if command == "chmod_run":

        path = safe_path(
            request["path"]
        )

        os.chmod(
            path,
            0o700
        )

        return {
            "ok": True,
            "operation": "chmod_run",
            "path": request["path"]
        }

    if command == "exec_python":

        relative_path = request.get(
            "path"
        )

        if not relative_path:
            return {
                "ok": False,
                "error": "missing_path"
            }

        if not relative_path.endswith(
            ".py"
        ):
            return {
                "ok": False,
                "error": "only_python_allowed"
            }

        path = safe_path(
            relative_path
        )

        if not os.path.isfile(path):
            return {
                "ok": False,
                "error": "file_not_found",
                "path": relative_path
            }

        allowed = {
            "aris_memory.py",
            "install_deps.py",
            "install_simple.py",
            "test_exec.py",
            "install_bg.py",
            "install_direct.py",
            "restart_gw.py"
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

    if command == "memory_add":
        return memory_add(request)

    if command == "memory_get":
        return memory_get(request)

    if command == "memory_search":
        return memory_search(request)

    if command == "memory_state":
        return memory_state(request)

    if command == "install_gateway_service":

        prefix = os.environ.get(
            "PREFIX"
        )

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

        with open(
            run_file,
            "w",
            encoding="utf-8"
        ) as f:
            f.write(script)

        os.chmod(
            run_file,
            0o700
        )

        return {
            "ok": True,
            "operation":
                "install_gateway_service",
            "service_dir":
                service_dir,
            "run_file":
                run_file
        }

    if command == "enable_gateway_service":

        result = subprocess.run(
            [
                "sv-enable",
                "cll1-gateway"
            ],
            capture_output=True,
            text=True
        )

        return {
            "ok": result.returncode == 0,
            "operation":
                "enable_gateway_service",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }

    if command == "restart_gateway":

        def restart_later():

            time.sleep(1)

            subprocess.run(
                [
                    "sv",
                    "restart",
                    "cll1-gateway"
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

        threading.Thread(
            target=restart_later,
            daemon=True
        ).start()

        return {
            "ok": True,
            "operation":
                "restart_gateway",
            "message":
                "Gateway reiniciando"
        }

    if command == "heartbeat":

        node_id = str(
            request.get("node_id", "")
        ).strip()

        if not node_id:
            return {
                "ok": False,
                "error": "node_id_empty"
            }

        aris_status = str(
            request.get("status", "unknown")
        )

        pc_status = str(
            request.get("pc_status", "")
        )

        version = str(
            request.get("version", "1.0.0")
        )

        now = datetime.now(
            timezone.utc
        ).isoformat()

        state_value = json.dumps({
            "node_id": node_id,
            "status": aris_status,
            "pc_status": pc_status,
            "version": version,
            "timestamp": now,
        }, ensure_ascii=False)

        with db_connect() as conn:

            conn.execute("""
                INSERT INTO system_state
                (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key)
                DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
            """, (
                f"heartbeat:{node_id}",
                state_value,
                now,
            ))

        return {
            "ok": True,
            "operation": "heartbeat",
            "node_id": node_id,
            "timestamp": now,
        }

    if command == "get_state":

        key = str(
            request.get("key", "")
        ).strip()

        if not key:
            return {
                "ok": False,
                "error": "state_key_empty"
            }

        with db_connect() as conn:

            row = conn.execute("""
                SELECT value, updated_at
                FROM system_state
                WHERE key = ?
            """, (key,)).fetchone()

        if row is None:
            return {
                "ok": True,
                "operation": "get_state",
                "key": key,
                "value": None,
                "updated_at": None,
            }

        return {
            "ok": True,
            "operation": "get_state",
            "key": key,
            "value": row["value"],
            "updated_at": row["updated_at"],
        }

    return {
        "ok": False,
        "error": "unknown_command"
    }


def handle_client(
    sock,
    address
):

    try:

        request = recv_json(
            sock
        )

        response = handle_request(
            request
        )

        send_json(
            sock,
            response
        )

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

    global TOKEN

    TOKEN = get_token()

    if not TOKEN:

        print(
            "ERRO: CLL1_TOKEN não encontrado."
        )

        return

    init_memory_db()

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
        (
            HOST,
            PORT
        )
    )

    server.listen(20)

    print(
        f"CLL1 Gateway online em {HOST}:{PORT}"
    )

    while True:

        client, address = server.accept()

        threading.Thread(
            target=handle_client,
            args=(
                client,
                address
            ),
            daemon=True
        ).start()


if __name__ == "__main__":
    main()