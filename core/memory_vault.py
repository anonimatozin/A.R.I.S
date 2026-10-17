"""
A.R.I.S. Memory Vault — Markdown vault with wikilinks (inspired by JARVIS).

Every .md file under vault/ is one node. Frontmatter gives it a type;
wiki links ([[Another Note]]) become edges. The vault is the memory,
the graph is just a view of it.
"""
import os
import pathlib
import re
import threading
import time
import json

ROOT = pathlib.Path(__file__).resolve().parent.parent
VAULT = pathlib.Path(os.environ.get("ARIS_VAULT", ROOT / "vault"))

WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)

TYPE_COLOURS = {
    "note":     "#e9eff7",
    "concept":  "#ffb340",
    "project":  "#5f7cff",
    "person":   "#b98cff",
    "task":     "#2ed99b",
    "idea":     "#ff6ba6",
    "sop":      "#ffa033",
    "brief":    "#cbd6e4",
    "command":  "#4c9bff",
}
DEFAULT_COLOUR = "#8fa3bf"

STATE_FILE = ROOT / "data" / "vault_state.json"
_CACHE = {"at": 0.0, "data": None, "sig": None}
_LOCK = threading.Lock()
CACHE_TTL = 2.0


def _parse_frontmatter(text):
    meta, body = {}, text
    m = FRONTMATTER.match(text)
    if m:
        body = text[m.end():]
        for line in m.group(1).splitlines():
            if ":" in line and not line.strip().startswith("#"):
                k, _, v = line.partition(":")
                meta[k.strip().lower()] = v.strip().strip('"').strip("'")
    return meta, body


def _signature():
    if not VAULT.exists():
        return ()
    return tuple(sorted(
        (str(p), int(p.stat().st_mtime))
        for p in VAULT.rglob("*.md")
    ))


def build_graph(force=False):
    with _LOCK:
        now = time.time()
        if not force and _CACHE["data"] and now - _CACHE["at"] < CACHE_TTL:
            return _CACHE["data"]
        sig = _signature()
        if not force and _CACHE["data"] and sig == _CACHE["sig"]:
            _CACHE["at"] = now
            return _CACHE["data"]

        nodes, by_title, edges = {}, {}, []
        if VAULT.exists():
            for path in sorted(VAULT.rglob("*.md")):
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                meta, body = _parse_frontmatter(text)
                title = meta.get("title") or path.stem
                ntype = (meta.get("type") or "note").strip().lower()
                key = title.lower()
                snippet = " ".join(
                    ln.strip() for ln in body.splitlines()
                    if ln.strip() and not ln.strip().startswith("#")
                )[:340]
                nodes[key] = dict(
                    id=key, title=title, type=ntype,
                    colour=TYPE_COLOURS.get(ntype, DEFAULT_COLOUR),
                    file=str(path.relative_to(VAULT)),
                    tags=[t.strip() for t in (meta.get("tags") or "").split(",") if t.strip()],
                    updated=meta.get("updated", ""),
                    snippet=snippet, degree=0,
                )
                by_title[key] = key
                for target in WIKILINK.findall(body):
                    edges.append((key, target.strip().lower()))

        clean, seen = [], set()
        for src, dst in edges:
            if dst not in by_title or src == dst:
                continue
            pair = tuple(sorted((src, dst)))
            if pair in seen:
                continue
            seen.add(pair)
            clean.append(dict(source=src, target=dst))
            nodes[src]["degree"] += 1
            nodes[dst]["degree"] += 1

        counts = {}
        for n in nodes.values():
            counts[n["type"]] = counts.get(n["type"], 0) + 1

        hubs = sorted(nodes.values(), key=lambda n: (-n["degree"], n["title"]))[:8]
        data = dict(
            nodes=list(nodes.values()),
            links=clean,
            counts=sorted(counts.items(), key=lambda kv: -kv[1]),
            hubs=[dict(id=h["id"], title=h["title"], degree=h["degree"],
                       colour=h["colour"], type=h["type"]) for h in hubs],
            vault=str(VAULT),
            total=len(nodes),
        )
        _CACHE.update(at=now, data=data, sig=sig)
        return data


def search(query, limit=6):
    q = (query or "").strip().lower()
    if not q:
        return []
    hits = []
    for node in build_graph()["nodes"]:
        haystack = (node["title"] + " " + node["snippet"]).lower()
        if q in haystack:
            hits.append(node)
    hits.sort(key=lambda n: (-n["degree"], n["title"]))
    return hits[:limit]


def _scored(message):
    words = [w for w in re.split(r"[^a-z0-9]+", (message or "").lower()) if len(w) > 3]
    if not words:
        return []
    out = []
    for node in build_graph()["nodes"]:
        haystack = (node["title"] + " " + node["snippet"]).lower()
        score = sum(2 if w in node["title"].lower() else 1 for w in words if w in haystack)
        if score:
            out.append((score + node["degree"] * 0.1, node))
    out.sort(key=lambda pair: -pair[0])
    return out


def context_for(message, limit=4):
    scored = _scored(message)
    if not scored:
        return ""
    out = ["## Memoria relevante do vault A.R.I.S.",
           "Estas notas vem do vault markdown do usuario. Trate-as como fato."]
    for _, node in scored[:limit]:
        out.append(f"### {node['title']} ({node['type']})\n{node['snippet']}")
    return "\n\n".join(out)


def shortest_path(source, target):
    """Encontra caminho mais curto entre dois nos."""
    graph = build_graph()
    adj = {}
    for node in graph["nodes"]:
        adj[node["id"]] = set()
    for link in graph["links"]:
        adj[link["source"]].add(link["target"])
        adj[link["target"]].add(link["source"])

    src = source.lower().strip()
    tgt = target.lower().strip()

    if src not in adj or tgt not in adj:
        return None

    if src == tgt:
        return [src]

    visited = {src}
    queue = [[src]]
    while queue:
        path = queue.pop(0)
        node = path[-1]
        for neighbor in adj.get(node, set()):
            if neighbor == tgt:
                return path + [neighbor]
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(path + [neighbor])
    return None


def create_vault():
    """Cria vault com exemplos iniciais."""
    VAULT.mkdir(parents=True, exist_ok=True)

    examples = {
        "A.R.I.S..md": """---
type: note
updated: 2026-09-16
tags: aris, sistema
---

# A.R.I.S.

Assistente virtual distribuida com [[Modo EDGE]] e [[Modo PRIMARY]].
Roda no [[CLL1]] (Termux) e no [[PC]] (Windows).
Conecta via [[Gateway]] e [[Discord]].
""",
        "Modo EDGE.md": """---
type: concept
updated: 2026-09-16
tags: modo, edge
---

# Modo EDGE

Modo quando o PC esta offline.
Usa [[Ollama]] local no [[CLL1]] para respostas basicas.
>NNL via regex para comandos rapidos.
Fallback para [[Groq]] API quando disponivel.
""",
        "Modo PRIMARY.md": """---
type: concept
updated: 2026-09-16
tags: modo, primary
---

# Modo PRIMARY

Modo quando o PC esta online.
Usa [[PC Listener]] para proxy de LLM.
Suporte completo a ferramentas e automacoes.
""",
        "CLL1.md": """---
type: project
updated: 2026-09-16
tags: hardware, cellphone
---

# CLL1

Celular que roda [[A.R.I.S.]] via [[Termux]].
Roda [[Gateway]], [[Edge Chat]], [[Ollama]] e [[Uptime Watchdog]].
IP: 192.168.0.106
""",
        "PC.md": """---
type: project
updated: 2026-09-16
tags: hardware, computador
---

# PC

Computador principal com [[PC Listener]].
Roda automacoes, browser control e LLM proxy.
IP: 192.168.0.109
""",
        "Gateway.md": """---
type: component
updated: 2026-09-16
tags: servidor, gateway
---

# Gateway

Servidor HTTP/TCP no [[CLL1]].
Rota entre [[Discord]], [[Dashboard]] e [[PC Listener]].
Portas: TCP 8765, HTTP 8766
""",
    }

    for name, content in examples.items():
        path = VAULT / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")

    return {"ok": True, "vault": str(VAULT), "files": len(examples)}
