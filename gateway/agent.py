"""Agent API — REST endpoints for agent communication."""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

_agents: dict[str, dict[str, Any]] = {}


def _load_agents(base_dir: str) -> None:
    agents_file = os.path.join(base_dir, "agents.json")
    if os.path.exists(agents_file):
        with open(agents_file, encoding="utf-8") as f:
            data = json.load(f)
            for agent in data.get("agents", []):
                _agents[agent["id"]] = agent


def list_agents(base_dir: str) -> list[dict[str, Any]]:
    if not _agents:
        _load_agents(base_dir)
    if not _agents:
        return [{"id": "default", "name": "Default Agent", "type": "local", "status": "active"}]
    return list(_agents.values())


def get_agent(agent_id: str, base_dir: str) -> dict[str, Any] | None:
    if not _agents:
        _load_agents(base_dir)
    return _agents.get(agent_id)


def create_agent(name: str, agent_type: str, base_dir: str, **kwargs: Any) -> dict[str, Any]:
    agent_id = str(uuid.uuid4())[:8]
    agent = {
        "id": agent_id,
        "name": name,
        "type": agent_type,
        "status": "active",
        "created_at": time.time(),
        **kwargs,
    }
    _agents[agent_id] = agent
    _save_agents(base_dir)
    return agent


def _save_agents(base_dir: str) -> None:
    agents_file = os.path.join(base_dir, "agents.json")
    with open(agents_file, "w", encoding="utf-8") as f:
        json.dump({"agents": list(_agents.values())}, f, ensure_ascii=False, indent=2)


def route_message(message: str, agent_id: str | None, base_dir: str) -> dict[str, Any]:
    if agent_id:
        agent = get_agent(agent_id, base_dir)
        if not agent:
            return {"ok": False, "error": f"Agent {agent_id} not found"}

    from gateway.filesystem import list_files, read_file
    from gateway.terminal import run_command

    msg_lower = message.lower().strip()

    if msg_lower.startswith("exec:"):
        cmd = message[5:].strip()
        result = run_command(cmd, timeout=30, cwd=base_dir)
        return {"ok": True, "type": "exec", "result": result}

    if msg_lower.startswith("read:"):
        path = message[5:].strip()
        try:
            content = read_file(base_dir, path)
            return {"ok": True, "type": "file", "path": path, "content": content}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    if msg_lower.startswith("ls:") or msg_lower.startswith("list:"):
        path = message.split(":", 1)[1].strip() if ":" in message else "."
        try:
            files = list_files(base_dir, path)
            return {"ok": True, "type": "list", "path": path, "files": files}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    if msg_lower in ("status", "health"):
        from gateway.services import sv_status
        return {"ok": True, "type": "status", "result": sv_status()}

    return {"ok": True, "type": "chat", "message": f"Received: {message}"}
