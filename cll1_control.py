import socket
import json
import os
import sys
import base64

CLL1_HOST = "192.168.0.106"
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


def full_status():
    print("=== CLL1 FULL STATUS ===\n")

    svc = send_request({"type": "status"})
    if svc and svc.get("ok"):
        print(f"Servico: {svc.get('output', 'N/A')}")
    else:
        print("Servico: NAO DISPONIVEL")

    print()

    gw = send_request({"type": "admin_ping"})
    if gw and gw.get("ok"):
        print(f"Gateway TCP: ATIVO (porta {CLL1_PORT})")
    else:
        print("Gateway TCP: DOWN")

    info = send_request({"type": "exec_python", "path": "test_exec.py"})
    if info and info.get("ok"):
        stdout = info.get("stdout", "")
        for line in stdout.strip().split("\n"):
            if line.strip():
                print(line.strip())
    else:
        print("Componentes: NAO DISPONIVEL")

    print("\n========================")


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


def get_file(remote_file, local_file=None):
    if local_file is None:
        local_file = os.path.basename(remote_file)

    response = send_request({
        "type": "get_file",
        "path": remote_file
    })

    if not response:
        return

    if not response.get("ok"):
        show(response)
        return

    content = response.get("content")

    if not content:
        print("Arquivo vazio ou resposta inválida.")
        return

    with open(local_file, "wb") as f:
        f.write(base64.b64decode(content))

    print(f"Arquivo recebido: {local_file}")


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


def sched_start():
    show(send_request({"type": "scheduler_start"}))


def sched_stop():
    show(send_request({"type": "scheduler_stop"}))


def sched_status():
    show(send_request({"type": "scheduler_status"}))


def ts(action="status"):
    show(send_request({"type": "tailscale", "action": action}))


def restart_verify(timeout=90):
    """Restart com VERIFICAÇÃO real: compara boot_time antes/depois.

    Não confia em "comando enviado" — só reporta sucesso se o CLL1
    voltar com um boot_time (timestamp de boot do processo) DIFERENTE.
    """
    import time as _time
    import datetime as _dt

    before = send_request({"type": "status"})
    boot_before = (before or {}).get("boot_time")
    print(f"boot_time ANTES: {boot_before} "
          f"({_dt.datetime.fromtimestamp(boot_before).isoformat() if boot_before else 'desconhecido'})")

    resp = send_request({"type": "restart_gateway"})
    print("resposta do restart:")
    show(resp)
    if not (resp or {}).get("ok"):
        print("FALHA: gateway recusou o restart.")
        return False

    print(f"\nAguardando reinício (timeout {timeout}s)...")
    deadline = _time.time() + timeout
    attempt = 0
    while _time.time() < deadline:
        attempt += 1
        _time.sleep(5)
        try:
            cur = send_request({"type": "status"})
        except Exception:
            cur = None
        if not cur or not cur.get("ok"):
            print(f"  [{attempt}] gateway ainda fora do ar...")
            continue
        boot_after = cur.get("boot_time")
        if boot_after and boot_before and boot_after != boot_before:
            print("\nRESTART CONFIRMADO [OK]")
            print(f"  boot_time ANTES : {boot_before} ({_dt.datetime.fromtimestamp(boot_before).isoformat()})")
            print(f"  boot_time DEPOIS: {boot_after} ({_dt.datetime.fromtimestamp(boot_after).isoformat()})")
            print(f"  sv status: {cur.get('output', 'N/A')}")
            return True
        elif boot_after and not boot_before:
            print(f"\nRESTART PROVAVEL [OK] (boot_time agora disponível: {boot_after})")
            return True
        else:
            print(f"  [{attempt}] gateway respondeu mas boot_time inalterado ({boot_after})...")
    print("\nFALHA: timeout — boot_time não mudou. O restart NÃO foi confirmado.")
    print("Verifique data/restart.log no CLL1 e o serviço runit 'cll1-main'.")
    return False


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
  python cll1_control.py fullstatus

  python cll1_control.py put arquivo.py
  python cll1_control.py put arquivo.py caminho/remoto.py

  python cll1_control.py get arquivo_remoto.py
  python cll1_control.py get arquivo_remoto.py arquivo_local.py

  python cll1_control.py mkdir pasta
  python cll1_control.py chmod caminho/run

  python cll1_control.py exec aris_memory.py

  python cll1_control.py install-service
  python cll1_control.py enable
  python cll1_control.py restart
  python cll1_control.py restart-verify   (restart + confirma boot_time mudou)

  python cll1_control.py sched-start
  python cll1_control.py sched-stop
  python cll1_control.py sched-status

  python cll1_control.py ts-status | ts-start | ts-up | ts-funnel | ts-funnel-off
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

    elif command == "fullstatus":
        full_status()

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

    elif command == "get":
        if len(sys.argv) < 3:
            print("Informe o arquivo remoto.")
            return

        remote_file = sys.argv[2]

        local_file = (
            sys.argv[3]
            if len(sys.argv) >= 4
            else None
        )

        get_file(remote_file, local_file)

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

    elif command == "restart-verify":
        ok = restart_verify()
        sys.exit(0 if ok else 1)

    elif command == "sched-start":
        sched_start()

    elif command == "sched-stop":
        sched_stop()

    elif command == "sched-status":
        sched_status()

    elif command == "ts-status":
        ts("status")

    elif command == "ts-start":
        ts("start")

    elif command == "ts-up":
        ts("up")

    elif command == "ts-funnel":
        ts("funnel")

    elif command == "ts-funnel-off":
        ts("funnel_off")

    else:
        usage()


if __name__ == "__main__":
    main()