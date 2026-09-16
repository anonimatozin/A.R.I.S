"""CLI — comandos de linha de comando do A.R.I.S.

Uso:
    aris                   — inicia interacao
    aris status            — status do servico
    aris message "texto"   — envia mensagem
    aris stop              — para o servico
    aris debug             — informacoes de debug
    aris install           — instala auto-start
    aris uninstall         — remove auto-start
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _send_to_agent(command: str, **kwargs) -> dict | None:
    """Envia comando ao Agent via IPC."""
    try:
        from agent.ipc import IPCClient
        client = IPCClient()
        return client.send({"command": command, **kwargs})
    except Exception:
        return None


def cmd_status() -> None:
    """Mostra status do servico."""
    result = _send_to_agent("status")
    if result is None:
        print("A.R.I.S. nao esta rodando.")
        print("Para iniciar: aris start")
        return

    print("=== A.R.I.S. Status ===")
    print(f"  Running: {result.get('running', False)}")
    print(f"  PID: {result.get('pid', 'N/A')}")

    session = result.get("session", {})
    print(f"  Session: {session.get('state', 'unknown')}")
    print(f"  Interactions: {session.get('interactions', 0)}")
    print(f"  Time since last: {session.get('time_since_last', 0)}s")
    print(f"  Time until idle: {session.get('time_until_idle', 0)}s")


def cmd_message(text: str) -> None:
    """Envia mensagem ao Agent."""
    result = _send_to_agent("message", text=text, source="cli")
    if result is None:
        print("Erro: A.R.I.S. nao esta rodando.")
        return
    if result.get("ok"):
        print(result.get("response", ""))
    else:
        print(f"Erro: {result.get('error', 'desconhecido')}")


def cmd_stop() -> None:
    """Para o servico."""
    result = _send_to_agent("stop")
    if result is None:
        print("A.R.I.S. nao esta rodando.")
        return
    print("A.R.I.S. sendo encerrado...")


def cmd_debug() -> None:
    """Mostra informacoes de debug."""
    result = _send_to_agent("status")
    if result is None:
        print("Agent offline.")
        return

    print("=== A.R.I.S. Debug ===")
    print(json.dumps(result, indent=2, default=str))

    # Verificar arquivos
    aris_dir = Path.home() / ".aris"
    print(f"\n  Dir: {aris_dir}")
    if aris_dir.exists():
        for f in aris_dir.iterdir():
            print(f"    {f.name}: {f.stat().st_size} bytes")


def cmd_session() -> None:
    """Mostra status da sessao."""
    result = _send_to_agent("session")
    if result is None:
        print("Agent offline.")
        return

    print("=== Session ===")
    print(f"  State: {result.get('state', 'unknown')}")
    print(f"  Interactions: {result.get('interactions', 0)}")
    print(f"  Time since last: {result.get('time_since_last', 0)}s")
    print(f"  Time until idle: {result.get('time_until_idle', 0)}s")
    print(f"  Duration: {result.get('duration', 0)}s")


def cmd_install() -> None:
    """Instala auto-start no Windows."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        script = Path(__file__).parent.parent / "run_aris.bat"
        winreg.SetValueEx(key, "ARIS", 0, winreg.REG_SZ, f'"{script}"')
        winreg.CloseKey(key)
        print("Auto-start instalado com sucesso!")
        print("A.R.I.S. iniciara automaticamente com o Windows.")
    except Exception as e:
        print(f"Erro ao instalar: {e}")


def cmd_uninstall() -> None:
    """Remove auto-start do Windows."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        winreg.DeleteValue(key, "ARIS")
        winreg.CloseKey(key)
        print("Auto-start removido.")
    except FileNotFoundError:
        print("Auto-start nao estava instalado.")
    except Exception as e:
        print(f"Erro ao remover: {e}")


def cmd_start() -> None:
    """Inicia o Agent em background."""
    import subprocess
    script = Path(__file__).parent.parent / "run_aris.bat"
    if not script.exists():
        print("Script run_aris.bat nao encontrado.")
        return

    # Iniciar em background (sem janela)
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    subprocess.Popen(
        [str(script)],
        startupinfo=startupinfo,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    print("A.R.I.S. iniciando em background...")


def main() -> None:
    """Entry point do CLI."""
    args = sys.argv[1:]

    if not args:
        # Sem argumentos — iniciar interacao interativa
        cmd_start()
        return

    command = args[0].lower()

    if command == "status":
        cmd_status()
    elif command == "message" or command == "msg":
        text = " ".join(args[1:]) if len(args) > 1 else input("Digite: ")
        cmd_message(text)
    elif command == "stop":
        cmd_stop()
    elif command == "debug":
        cmd_debug()
    elif command == "session":
        cmd_session()
    elif command == "start":
        cmd_start()
    elif command == "install":
        cmd_install()
    elif command == "uninstall":
        cmd_uninstall()
    elif command == "help" or command == "--help" or command == "-h":
        print(__doc__)
    else:
        # Tratar como mensagem
        cmd_message(" ".join(args))


if __name__ == "__main__":
    main()
