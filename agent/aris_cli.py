"""A.R.I.S. CLI — Terminal interativo conectado ao sistema unificado.

Uso:
    aris                    # Inicia chat interativo na pasta atual
    aris status             # Mostra status do sistema
    aris chat "mensagem"    # Envia mensagem e recebe resposta
    aris files              # Lista arquivos da pasta atual
    aris memory             # Mostra memórias relevantes
    aris sync               # Sincroniza memória com pendrive
    aris help               # Mostra ajuda
"""

import os
import sys
import json
import glob
import hashlib
import io
from pathlib import Path
from datetime import datetime

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

PC_LISTENER_URL = "http://127.0.0.1:8770"
GATEWAY_URL = "http://192.168.0.106:8766"

# Carregar token de autenticação
def _load_token():
    """Carrega token do .env ou variável de ambiente."""
    env_token = os.environ.get("CLL1_TOKEN")
    if env_token:
        return env_token
    env_file = PROJECT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("CLL1_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""

AUTH_TOKEN = _load_token()


def get_current_dir():
    """Retorna o diretório atual de onde o comando foi chamado."""
    # Usar a variável de ambiente que o batch file salva
    env_dir = os.environ.get("ARIS_CWD", "")
    if env_dir and Path(env_dir).exists():
        return Path(env_dir)
    return Path(os.getcwd())


def list_files(directory=None, show_hidden=False):
    """Lista arquivos do diretório."""
    d = Path(directory) if directory else get_current_dir()
    if not d.exists():
        print(f"Pasta nao encontrada: {d}")
        return []

    files = []
    for item in sorted(d.iterdir()):
        if not show_hidden and item.name.startswith("."):
            continue
        if item.is_dir():
            files.append(f"  [DIR]  {item.name}/")
        else:
            size = item.stat().st_size
            if size > 1024 * 1024:
                size_str = f"{size / (1024*1024):.1f} MB"
            elif size > 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size} B"
            files.append(f"  [FILE] {item.name} ({size_str})")

    return files


def check_pc_online():
    """Verifica se o PC listener está rodando."""
    import urllib.request
    try:
        req = urllib.request.Request(f"{PC_LISTENER_URL}/api/llm")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            return data.get("ok", False)
    except Exception:
        return False


def check_gateway_online():
    """Verifica se o gateway está rodando."""
    import urllib.request
    try:
        req = urllib.request.Request(f"{GATEWAY_URL}/api/status")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            return data.get("ok", False)
    except Exception:
        return False


def send_to_edge_chat(text, cwd=None):
    """Envia mensagem pro edge chat e retorna resposta."""
    import urllib.request
    payload = json.dumps({
        "message": text,
        "cwd": str(cwd or get_current_dir()),
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"{GATEWAY_URL}/api/chat",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {AUTH_TOKEN}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            return data.get("response", "Sem resposta")
    except Exception as e:
        return f"Erro de conexao: {e}"


def send_pc_command(command, **kwargs):
    """Envia comando pro PC listener."""
    import urllib.request
    payload = json.dumps({"command": command, **kwargs}).encode("utf-8")
    try:
        req = urllib.request.Request(
            PC_LISTENER_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def search_knowledge_graph(query, limit=5):
    """Busca no knowledge graph."""
    import urllib.request
    payload = json.dumps({"query": query, "limit": limit}).encode("utf-8")
    try:
        req = urllib.request.Request(
            f"{GATEWAY_URL}/api/kg/search",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {AUTH_TOKEN}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("results", [])
    except Exception:
        return []


def show_status():
    """Mostra status completo do sistema."""
    cwd = get_current_dir()
    print(f"\n{'='*50}")
    print(f"  A.R.I.S. STATUS")
    print(f"{'='*50}")
    print(f"  Pasta atual: {cwd}")

    pc = check_pc_online()
    gw = check_gateway_online()
    print(f"  PC Listener: {'ONLINE' if pc else 'OFFLINE'}")
    print(f"  Gateway:     {'ONLINE' if gw else 'OFFLINE'}")

    if gw:
        print(f"  Control Center: {GATEWAY_URL}")

    # Verificar pendrive
    for drive in ["D:\\", "E:\\"]:
        if os.path.exists(drive + "ARIS_MEMORY"):
            print(f"  Pendrive: {drive}ARIS_MEMORY (conectado)")
            break
    else:
        print(f"  Pendrive: nao detectado")

    print(f"{'='*50}\n")


def show_memory():
    """Mostra memórias relevantes da pasta atual."""
    cwd = get_current_dir()
    results = search_knowledge_graph(str(cwd), limit=5)
    if results:
        print("\nMemórias relevantes:")
        for r in results:
            print(f"  [{r.get('type', '?')}] {r['content'][:100]}")
    else:
        print("Nenhuma memoria encontrada para esta pasta.")


def sync_with_pendrive():
    """Sincroniza knowledge graph com pendrive."""
    import subprocess
    sync_script = PROJECT_DIR / "agent" / "aris_sync.py"
    result = subprocess.run(
        [sys.executable, str(sync_script), "push"],
        capture_output=True, text=True, timeout=30,
        cwd=str(PROJECT_DIR),
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr)


def interactive_chat():
    """Chat interativo com A.R.I.S."""
    cwd = get_current_dir()
    print(f"\n{'='*50}")
    print(f"  A.R.I.S. CLI — Chat Interativo")
    print(f"  Pasta: {cwd}")
    print(f"  Digite 'sair' para encerrar")
    print(f"  Digite 'arquivos' para ver arquivos")
    print(f"  Digite 'status' para ver status")
    print(f"{'='*50}\n")

    while True:
        try:
            user_input = input("voce> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAte logo!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("sair", "exit", "quit"):
            print("Ate logo!")
            break

        if user_input.lower() == "arquivos":
            files = list_files(cwd)
            if files:
                print(f"\nArquivos em {cwd}:")
                for f in files:
                    print(f"  {f}")
            else:
                print("Nenhum arquivo encontrado.")
            continue

        if user_input.lower() == "status":
            show_status()
            continue

        if user_input.lower() == "memoria":
            show_memory()
            continue

        if user_input.lower() == "sync":
            sync_with_pendrive()
            continue

        # Enviar pro edge chat
        print("A.R.I.S.: ", end="", flush=True)
        response = send_to_edge_chat(user_input, cwd)
        print(response)


def show_help():
    """Mostra ajuda."""
    print("""
A.R.I.S. CLI — Assistente de Raciocinio e Integracao de Sistemas

Uso:
    aris                   Chat interativo na pasta atual
    aris status            Ver status do sistema
    aris chat "mensagem"   Enviar mensagem
    aris files             Listar arquivos da pasta
    aris memory            Ver memorias relevantes
    aris sync              Sincronizar com pendrive
    aris help              Esta ajuda

Exemplos:
    aris                   # Inicia chat
    aris files             # Lista arquivos
    aris chat "abre o navegador"  # Comando direto
    """)


def main():
    args = sys.argv[1:]

    if not args:
        interactive_chat()
        return

    cmd = args[0].lower()

    if cmd == "status":
        show_status()
    elif cmd == "files" or cmd == "arquivos":
        files = list_files()
        for f in files:
            print(f)
    elif cmd == "chat":
        msg = " ".join(args[1:]) if len(args) > 1 else input("Mensagem: ")
        print(send_to_edge_chat(msg))
    elif cmd == "memory" or cmd == "memoria":
        show_memory()
    elif cmd == "sync":
        sync_with_pendrive()
    elif cmd == "help":
        show_help()
    else:
        # Tratar como mensagem direta
        msg = " ".join(args)
        print(send_to_edge_chat(msg))


if __name__ == "__main__":
    main()
