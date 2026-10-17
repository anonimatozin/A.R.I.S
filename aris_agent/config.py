"""Configuração do agente.

Regras importantes:
* os valores vêm de (1) padrões, (2) ``aris_agent.json`` e (3) variáveis ``ARIS_AGENT_*``;
* a chave ``sections`` vem **apenas** do JSON — cada parte lê a sua
  (``llm``, ``pc``, ``web``, ``memory``, ``safety``, ``skills``, ``core``)
  sem precisar editar este arquivo;
* chaves de API **nunca** ficam no JSON: só em variáveis de ambiente.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("aris.agent.config")

DEFAULT_WORKSPACE = Path.home() / "ARIS_workspace"
DEFAULT_DATA_DIR = Path.home() / ".aris_agent"

# Nomes de chave que jamais podem persistir no JSON de configuração.
_FORBIDDEN_JSON_KEYS = {
    "api_key",
    "apikey",
    "key",
    "token",
    "access_token",
    "auth_token",
    "refresh_token",
    "password",
    "passwd",
    "secret",
    "client_secret",
    "secret_key",
    "private_key",
    "authorization",
    "chave",
    "senha",
}


def _project_root() -> Path:
    """Raiz do projeto (pai do pacote ``aris_agent``)."""
    return Path(__file__).resolve().parents[1]


def _env(name: str) -> str | None:
    value = os.environ.get(f"ARIS_AGENT_{name}")
    if value is None:
        return None
    value = value.strip()
    return value or None


def _env_bool(name: str) -> bool | None:
    raw = _env(name)
    if raw is None:
        return None
    return raw.lower() in {"1", "true", "yes", "on", "sim"}


def _env_int(name: str) -> int | None:
    raw = _env(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        log.warning("ARIS_AGENT_%s não é um inteiro: %r (ignorado)", name, raw)
        return None


def _env_float(name: str) -> float | None:
    raw = _env(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        log.warning("ARIS_AGENT_%s não é um número: %r (ignorado)", name, raw)
        return None


def _env_paths(name: str) -> list[Path] | None:
    raw = _env(name)
    if raw is None:
        return None
    parts = [p for p in raw.split(os.pathsep) if p.strip()]
    return [Path(p).expanduser() for p in parts] or None


def _strip_secrets(section: dict[str, Any], section_name: str) -> dict[str, Any]:
    """Remove do JSON chaves que parecem credencial, avisando o usuário."""
    limpo: dict[str, Any] = {}
    for key, value in section.items():
        if str(key).lower() in _FORBIDDEN_JSON_KEYS:
            log.warning(
                "seção %r do aris_agent.json tem a chave %r com valor de credencial; "
                "removida. Use a variável de ambiente correspondente.",
                section_name,
                key,
            )
            continue
        limpo[key] = value
    return limpo


@dataclass
class AgentConfig:
    """Configuração usada por todas as partes do agente."""

    workspace_dir: Path = field(default_factory=lambda: DEFAULT_WORKSPACE)
    data_dir: Path = field(default_factory=lambda: DEFAULT_DATA_DIR)
    allowed_roots: list[Path] = field(default_factory=list)
    audit_log_path: Path | None = None
    max_steps: int = 12
    max_tool_chars: int = 8000
    max_total_tokens_per_task: int = 60000
    confirm_timeout_s: float = 30.0
    agent_enabled: bool = False
    sections: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.workspace_dir = Path(self.workspace_dir).expanduser()
        self.data_dir = Path(self.data_dir).expanduser()
        if self.allowed_roots:
            self.allowed_roots = [Path(p).expanduser() for p in self.allowed_roots]
        else:
            self.allowed_roots = [self.workspace_dir]
        if self.audit_log_path is None:
            self.audit_log_path = self.data_dir / "audit.jsonl"
        else:
            self.audit_log_path = Path(self.audit_log_path).expanduser()
        self.ensure_dirs()

    def ensure_dirs(self) -> None:
        """Cria workspace e diretório de dados se não existirem (não falha se der ruim)."""
        for path in (self.workspace_dir, self.data_dir):
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:  # pragma: no cover - depende do ambiente
                log.warning("não consegui criar %s: %s", path, exc)

    def section(self, name: str) -> dict:
        """Devolve a seção da parte (dict vazio se não houver)."""
        value = self.sections.get(name)
        return dict(value) if isinstance(value, dict) else {}

    def to_dict(self) -> dict:
        """Representação serializável (sem segredos) — útil para log/debug."""
        return {
            "workspace_dir": str(self.workspace_dir),
            "data_dir": str(self.data_dir),
            "allowed_roots": [str(p) for p in self.allowed_roots],
            "audit_log_path": str(self.audit_log_path),
            "max_steps": self.max_steps,
            "max_tool_chars": self.max_tool_chars,
            "max_total_tokens_per_task": self.max_total_tokens_per_task,
            "confirm_timeout_s": self.confirm_timeout_s,
            "agent_enabled": self.agent_enabled,
            "sections": {k: dict(v) for k, v in self.sections.items()},
        }


def _read_json(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("ignorando %s: %s", path, exc)
        return {}
    if not isinstance(raw, dict):
        log.warning("ignorando %s: o conteúdo não é um objeto JSON", path)
        return {}
    log.debug("configuração carregada de %s", path)
    return raw


def _find_json(override: Path | str | None) -> Path | None:
    if override is not None:
        path = Path(override).expanduser()
        return path if path.is_file() else None
    root_json = _project_root() / "aris_agent.json"
    if root_json.is_file():
        return root_json
    data_json = Path(_env("DATA_DIR") or DEFAULT_DATA_DIR) / "aris_agent.json"
    return data_json if data_json.is_file() else None


def load_config(path: Path | str | None = None) -> AgentConfig:
    """Carrega a configuração: padrões → ``aris_agent.json`` → variáveis ``ARIS_AGENT_*``.

    ``sections`` vem só do JSON. Credenciais no JSON são removidas com aviso.
    """
    json_path = _find_json(path)
    data: dict = _read_json(json_path) if json_path else {}

    sections_raw = data.get("sections")
    sections: dict[str, dict] = {}
    if isinstance(sections_raw, dict):
        for name, value in sections_raw.items():
            if isinstance(value, dict):
                sections[str(name)] = _strip_secrets(value, str(name))
            else:
                log.warning("seção %r do JSON não é objeto; ignorada", name)

    def pick(key: str, default: Any) -> Any:
        value = data.get(key, default)
        return default if value is None else value

    cfg = AgentConfig(
        workspace_dir=Path(str(pick("workspace_dir", DEFAULT_WORKSPACE))).expanduser(),
        data_dir=Path(str(pick("data_dir", DEFAULT_DATA_DIR))).expanduser(),
        allowed_roots=[Path(str(p)).expanduser() for p in pick("allowed_roots", []) or []],
        audit_log_path=(
            Path(str(data["audit_log_path"])).expanduser() if data.get("audit_log_path") else None
        ),
        max_steps=int(pick("max_steps", 12)),
        max_tool_chars=int(pick("max_tool_chars", 8000)),
        max_total_tokens_per_task=int(pick("max_total_tokens_per_task", 60000)),
        confirm_timeout_s=float(pick("confirm_timeout_s", 30.0)),
        agent_enabled=bool(pick("agent_enabled", False)),
        sections=sections,
    )

    # Variáveis de ambiente vencem o JSON.
    if (v := _env_paths("WORKSPACE_DIR")) and len(v) == 1:
        cfg.workspace_dir = v[0]
    if (v := _env_paths("DATA_DIR")) and len(v) == 1:
        cfg.data_dir = v[0]
    if (v := _env_paths("ALLOWED_ROOTS")) is not None:
        cfg.allowed_roots = v
    if (v := _env("AUDIT_LOG")) is not None:
        cfg.audit_log_path = Path(v).expanduser()
    if (v := _env_int("MAX_STEPS")) is not None:
        cfg.max_steps = v
    if (v := _env_int("MAX_TOOL_CHARS")) is not None:
        cfg.max_tool_chars = v
    if (v := _env_int("MAX_TOTAL_TOKENS_PER_TASK")) is not None:
        cfg.max_total_tokens_per_task = v
    if (v := _env_float("CONFIRM_TIMEOUT_S")) is not None:
        cfg.confirm_timeout_s = v
    enabled = _env_bool("AGENT_ENABLED")
    if enabled is None:
        enabled = _env_bool("ENABLED")
    if enabled is not None:
        cfg.agent_enabled = enabled

    if cfg.audit_log_path is None:  # pragma: no cover - defensivo
        cfg.audit_log_path = cfg.data_dir / "audit.jsonl"
    cfg.ensure_dirs()
    return cfg
