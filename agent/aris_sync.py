"""aris_sync.py — Sincroniza memória do A.R.I.S. com pendrive.

Uso:
    python aris_sync.py              # Sync automático
    python aris_sync.py push         # PC -> Pendrive
    python aris_sync.py pull         # Pendrive -> PC
    python aris_sync.py status       # Ver status
"""

import json
import os
import shutil
import sys
from pathlib import Path
from datetime import datetime

PROJECT_DIR = Path(__file__).parent.parent
DATA_DIR = PROJECT_DIR / "data"
KG_FILE = DATA_DIR / "knowledge_graph.json"

# Arquivos que sincronizam
SYNC_FILES = [
    "knowledge_graph.json",
    "feedback.jsonl",
    "personality_state.json",
]


def find_pendrive():
    """Encontra o pendrive ARIS_MEMORY."""
    for letter in "DEFGHIJ":
        drive = Path(f"{letter}:\\")
        if drive.exists():
            # Procurar pasta ARIS_MEMORY
            for name in ["ARIS_MEMORY", "ARIS", "aris_memory"]:
                candidate = drive / name
                if candidate.is_dir():
                    return candidate
            # Se tem .git do ARIS na raiz
            if (drive / ".git").exists() or (drive / "data").exists():
                return drive
    return None


def sync_push(pendrive_dir):
    """Copia memória do PC pro pendrive."""
    if not KG_FILE.exists():
        print("Knowledge graph local nao existe.")
        return False

    dest_dir = pendrive_dir / "data"
    dest_dir.mkdir(parents=True, exist_ok=True)

    for fname in SYNC_FILES:
        src = DATA_DIR / fname
        dst = dest_dir / fname
        if src.exists():
            shutil.copy2(src, dst)
            print(f"  PUSH: {fname} ({src.stat().st_size} bytes)")

    # Salvar timestamp
    meta_file = dest_dir / "sync_meta.json"
    meta = {
        "last_sync": datetime.now().isoformat(),
        "direction": "push",
        "source": "pc",
    }
    meta_file.write_text(json.dumps(meta, indent=2))
    print(f"  Sync salvo em {pendrive_dir}")
    return True


def sync_pull(pendrive_dir):
    """Copia memória do pendrive pro PC (merge)."""
    src_dir = pendrive_dir / "data"
    if not src_dir.exists():
        print("Pasta data/ nao encontrada no pendrive.")
        return False

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    for fname in SYNC_FILES:
        src = src_dir / fname
        dst = DATA_DIR / fname
        if not src.exists():
            continue

        if fname == "knowledge_graph.json" and dst.exists():
            # Merge do knowledge graph
            merge_kg(dst, src)
        else:
            # Para outros arquivos, copiar se mais recente
            src_time = src.stat().st_mtime
            dst_time = dst.stat().st_mtime if dst.exists() else 0
            if src_time > dst_time:
                shutil.copy2(src, dst)
                print(f"  PULL: {fname} (mais recente do pendrive)")
            else:
                print(f"  SKIP: {fname} (PC ja tem versao mais recente)")

    print(f"  Sync concluido de {pendrive_dir}")
    return True


def merge_kg(local_file, pendrive_file):
    """Merge do knowledge graph — combina nós de ambos, mantendo o mais recente."""
    try:
        local_data = json.loads(local_file.read_text(encoding="utf-8"))
    except Exception:
        local_data = {"nodes": {}, "edges": []}

    try:
        remote_data = json.loads(pendrive_file.read_text(encoding="utf-8"))
    except Exception:
        return

    local_nodes = local_data.get("nodes", {})
    remote_nodes = remote_data.get("nodes", {})

    # Merge nós — remoto ganha se mais recente
    merged = 0
    for nid, node in remote_nodes.items():
        if nid not in local_nodes:
            local_nodes[nid] = node
            merged += 1
        else:
            # Pegar o mais recente
            local_time = local_nodes[nid].get("last_accessed", "")
            remote_time = node.get("last_accessed", "")
            if remote_time > local_time:
                local_nodes[nid] = node
                merged += 1

    # Merge arestas — adicionar novas do remoto
    local_edges = local_data.get("edges", [])
    remote_edges = remote_data.get("edges", [])
    local_edge_set = {(e["source"], e["target"], e["type"]) for e in local_edges}

    for edge in remote_edges:
        key = (edge["source"], edge["target"], edge["type"])
        if key not in local_edge_set:
            local_edges.append(edge)
            merged += 1

    # Salvar
    local_data["nodes"] = local_nodes
    local_data["edges"] = local_edges
    local_file.write_text(json.dumps(local_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  MERGE: {merged} itens novos no knowledge graph")


def show_status():
    """Mostra status do sync."""
    print(f"\n{'='*50}")
    print(f"  A.R.I.S. SYNC STATUS")
    print(f"{'='*50}")

    # Arquivos locais
    print(f"\n  Arquivos locais:")
    for fname in SYNC_FILES:
        f = DATA_DIR / fname
        if f.exists():
            size = f.stat().st_size
            mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m %H:%M")
            print(f"    {fname}: {size} bytes (modificado: {mtime})")
        else:
            print(f"    {fname}: NAO EXISTE")

    # Pendrive
    pendrive = find_pendrive()
    if pendrive:
        print(f"\n  Pendrive: {pendrive}")
        remote_data = pendrive / "data"
        if remote_data.exists():
            for fname in SYNC_FILES:
                f = remote_data / fname
                if f.exists():
                    size = f.stat().st_size
                    mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m %H:%M")
                    print(f"    {fname}: {size} bytes (modificado: {mtime})")
                else:
                    print(f"    {fname}: NAO EXISTE")
        else:
            print(f"    Pasta data/ nao encontrada")
    else:
        print(f"\n  Pendrive: NAO DETECTADO")

    print(f"{'='*50}\n")


def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
    else:
        cmd = "auto"

    if cmd == "status":
        show_status()
        return

    pendrive = find_pendrive()
    if not pendrive:
        print("Pendrive ARIS_MEMORY nao detectado. Conecte o pendrive e tente novamente.")
        return

    print(f"Pendrive encontrado: {pendrive}")

    if cmd == "push":
        sync_push(pendrive)
    elif cmd == "pull":
        sync_pull(pendrive)
    else:
        # Auto: push se PC tem dados mais recentes, pull se pendrive tem
        print("Sync automático...")
        if KG_FILE.exists():
            sync_push(pendrive)
        sync_pull(pendrive)


if __name__ == "__main__":
    main()
