"""Authentication and authorization for CLL1 Gateway."""

from __future__ import annotations

import os
import json
import hashlib
import secrets
import time
from pathlib import Path
from typing import Any

_SESSIONS: dict[str, dict] = {}  # session_token -> {username, role, created, last_access}
_USERS_FILE: Path | None = None
_BASE_DIR: str = ""
SESSION_TTL_S = 12 * 3600  # 12h — sessão expira mesmo com uso
_PBKDF2_ITERATIONS = 210_000

# Roles and their permissions
ROLES = {
    "admin": {
        "description": "Administrador total",
        "permissions": ["*"],  # all permissions
    },
    "bicicleta-com-rodinhas": {
        "description": "Aprendendo a usar a A.R.I.S. - acesso limitado",
        "permissions": [
            "chat", "status", "help", "recall", "graph", "missions_view",
            "voice_call_basic", "profile_view", "goal_view",
        ],
    },
    "operador": {
        "description": "Operador padrão - uso normal",
        "permissions": [
            "chat", "status", "help", "recall", "graph", "missions", "missions_view",
            "voice_call", "profile", "goal", "personality", "files", "terminal",
            "capabilities", "audit", "services", "agents", "browser",
        ],
    },
    "power-user": {
        "description": "Usuário avançado - quase admin",
        "permissions": [
            "chat", "status", "help", "recall", "graph", "missions", "missions_view",
            "voice_call", "profile", "goal", "personality", "files", "terminal",
            "capabilities", "audit", "services", "agents", "browser",
            "user_create", "user_password_self", "backup", "kg_store",
        ],
    },
    "temporario": {
        "description": "Acesso temporário com expiração automática",
        "permissions": [
            "chat", "status", "help", "recall", "graph", "missions_view",
            "voice_call_basic", "profile_view", "goal_view",
        ],
    },
}

DEFAULT_ROLE = "bicicleta-com-rodinhas"


def _get_users_file() -> Path:
    global _USERS_FILE
    if _USERS_FILE is None:
        _USERS_FILE = Path(_BASE_DIR) / "data" / "users.json"
        _USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    return _USERS_FILE


def _load_users() -> dict[str, dict]:
    """Carrega usuários do arquivo JSON."""
    path = _get_users_file()
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_users(users: dict[str, dict]) -> None:
    """Salva usuários no arquivo JSON."""
    path = _get_users_file()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def _pbkdf2_hash(password: str, salt_hex: str | None = None) -> str:
    """Hash pbkdf2-sha256 com salt. Formato: pbkdf2$<iter>$<salt_hex>$<hash_hex>."""
    import hashlib as _hl
    import secrets as _sec
    salt_hex = salt_hex or _sec.token_hex(16)
    dk = _hl.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), _PBKDF2_ITERATIONS)
    return f"pbkdf2${_PBKDF2_ITERATIONS}${salt_hex}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    import hashlib as _hl
    import hmac as _hm
    # Novo formato pbkdf2
    if stored.startswith("pbkdf2$"):
        try:
            _, iter_s, salt_hex, hash_hex = stored.split("$")
            dk = _hl.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iter_s))
            return _hm.compare_digest(dk.hex(), hash_hex)
        except Exception:
            return False
    # Legado sha256 (migrar no próximo login com sucesso)
    return _hm.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored)


def init_auth(base_dir: str) -> None:
    global _BASE_DIR, _USERS_FILE
    _BASE_DIR = base_dir
    _USERS_FILE = None  # Reset cache para novo base_dir

    # Sem admin default "admin/admin": exige senha via env na primeira criação.
    users = _load_users()
    if not users:
        initial_pw = os.environ.get("ARIS_ADMIN_PASSWORD", "")
        if not initial_pw:
            # Não cria usuário inseguro; operador deve criar via variável de ambiente
            # ou endpoint assistido. Loga aviso uma vez.
            try:
                print("auth: nenhum usuário — defina ARIS_ADMIN_PASSWORD para criar admin inicial")
            except Exception:
                pass
            return
        users["admin"] = {
            "username": "admin",
            "password_hash": _pbkdf2_hash(initial_pw),
            "role": "admin",
            "created": time.time(),
            "created_by": "system",
        }
        _save_users(users)


def get_token() -> str | None:
    """Retorna token API legado (compatibilidade)."""
    env_token = os.environ.get("CLL1_TOKEN")
    if env_token:
        return env_token
    env_file = os.path.join(_BASE_DIR, ".env")
    try:
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("CLL1_TOKEN="):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except FileNotFoundError:
        pass
    return None


def create_session(username: str, role: str) -> str:
    """Cria uma nova sessão e retorna o token."""
    token = secrets.token_hex(32)
    _SESSIONS[token] = {
        "username": username,
        "role": role,
        "created": time.time(),
        "last_access": time.time(),
    }
    return token


def login(username: str, password: str) -> str | None:
    """Tenta fazer login. Retorna session token ou None."""
    # Limpeza periódica oportunista: todo login varre expirados
    # (garante remoção automática mesmo sem chamada manual ao /api/users/cleanup)
    try:
        cleanup_expired_users()
    except Exception:
        pass
    users = _load_users()
    user = users.get(username)
    if not user:
        return None

    stored = user.get("password_hash", "")
    if not _verify_password(password, stored):
        return None
    # Migrar hash legado sha256 -> pbkdf2 no login com sucesso
    if not stored.startswith("pbkdf2$"):
        try:
            user["password_hash"] = _pbkdf2_hash(password)
            _save_users(users)
        except Exception:
            pass

    # Verificar expiração
    expires_at = user.get("expires_at")
    if expires_at and time.time() > expires_at:
        return None  # Usuário expirado

    return create_session(username, user.get("role", DEFAULT_ROLE))


def _session_valid(token: str) -> dict | None:
    sess = _SESSIONS.get(token)
    if not sess:
        return None
    if time.time() - sess.get("created", time.time()) > SESSION_TTL_S:
        _SESSIONS.pop(token, None)
        return None
    return sess


def logout(token: str) -> bool:
    """Invalida uma sessão (logout explícito)."""
    return _SESSIONS.pop(token, None) is not None


def is_legacy_token(token: str) -> bool:
    """True se token é o CLL1_TOKEN legado (sem role)."""
    import hmac as _hm
    legacy_token = get_token()
    if not legacy_token or not token:
        return False
    return _hm.compare_digest(token, legacy_token)


def authenticate(request: dict) -> bool:
    """Autentica por token (API) ou session (dashboard)."""
    import hmac as _hm
    token = request.get("token", "")

    # Checar session (com TTL)
    sess = _SESSIONS.get(token)
    if sess is not None:
        if time.time() - sess.get("created", time.time()) > SESSION_TTL_S:
            _SESSIONS.pop(token, None)
        else:
            sess["last_access"] = time.time()
            return True

    # Checar token API antigo (comparação constant-time)
    legacy_token = get_token()
    return bool(legacy_token) and bool(token) and _hm.compare_digest(token, legacy_token)


def get_session(token: str) -> dict | None:
    """Retorna info da sessão se válida (respeita TTL)."""
    return _session_valid(token)


def get_user_role(token: str) -> str | None:
    """Retorna role do usuário da sessão."""
    session = _SESSIONS.get(token)
    if session:
        return session.get("role")
    return None


def get_username(token: str) -> str | None:
    """Retorna username da sessão."""
    session = _SESSIONS.get(token)
    if session:
        return session.get("username")
    return None


def has_permission(token: str, permission: str) -> bool:
    """Verifica se usuário tem permissão."""
    role = get_user_role(token)
    if not role:
        return False

    role_perms = ROLES.get(role, {}).get("permissions", [])
    if "*" in role_perms:
        return True
    return permission in role_perms


def require_permission(token: str, permission: str) -> dict | None:
    """Retorna erro se não tem permissão, None se ok."""
    if not has_permission(token, permission):
        role = get_user_role(token) or "none"
        return {
            "ok": False,
            "error": f"Permissão negada: '{permission}' requer role superior (atual: {role})"
        }
    return None


def list_users(requesting_token: str) -> dict:
    """Lista todos os usuários (apenas admin)."""
    err = require_permission(requesting_token, "user_create")
    if err:
        return err

    users = _load_users()
    safe_users = []
    now = time.time()
    for u in users.values():
        expires_at = u.get("expires_at")
        expired = expires_at and now > expires_at
        safe_users.append({
            "username": u["username"],
            "role": u.get("role", DEFAULT_ROLE),
            "created": u.get("created", 0),
            "created_by": u.get("created_by", "unknown"),
            "expires_at": u.get("expires_at"),
            "expired": expired,
        })
    return {"ok": True, "users": safe_users, "roles": ROLES}


def cleanup_expired_users() -> dict:
    """Remove usuários temporários expirados. Retorna contagem de removidos.

    Também invalida sessões ativas desses usuários (desconexão automática).
    Chamada oportunisticamente a cada login() além do endpoint manual
    /api/users/cleanup — ou seja, roda periodicamente na prática.
    """
    users = _load_users()
    now = time.time()
    removed = []
    for username, u in list(users.items()):
        expires_at = u.get("expires_at")
        if expires_at and now > expires_at:
            if u.get("role") == "temporario":
                del users[username]
                removed.append(username)
    if removed:
        _save_users(users)
        # Invalidar sessões dos removidos (desconexão automática)
        for token, sess in list(_SESSIONS.items()):
            if sess.get("username") in removed:
                del _SESSIONS[token]
    return {"ok": True, "removed": removed, "count": len(removed)}


def hash_password(password: str) -> str:
    """Gera hash pbkdf2-sha256 de uma senha."""
    return _pbkdf2_hash(password)


# --- User Management ---

def list_users(requesting_token: str) -> dict:
    """Lista todos os usuários (apenas admin)."""
    err = require_permission(requesting_token, "user_create")
    if err:
        return err

    users = _load_users()
    safe_users = []
    for u in users.values():
        safe_users.append({
            "username": u["username"],
            "role": u.get("role", DEFAULT_ROLE),
            "created": u.get("created", 0),
            "created_by": u.get("created_by", "unknown"),
        })
    return {"ok": True, "users": safe_users, "roles": ROLES}


def create_user(requesting_token: str, username: str, password: str, role: str = DEFAULT_ROLE, expires_at: float | None = None) -> dict:
    """Cria novo usuário (apenas admin/power-user).
    
    Args:
        expires_at: Timestamp de expiração (opcional). Obrigatório para role 'temporario'.
    """
    err = require_permission(requesting_token, "user_create")
    if err:
        return err

    if role not in ROLES:
        return {"ok": False, "error": f"Role inválida: {role}. Disponíveis: {list(ROLES.keys())}"}

    # Para role temporario, exige expiração
    if role == "temporario" and expires_at is None:
        return {"ok": False, "error": "Role 'temporario' requer parâmetro 'expires_at' (timestamp)"}

    users = _load_users()
    if username in users:
        return {"ok": False, "error": f"Usuário '{username}' já existe"}

    user_data = {
        "username": username,
        "password_hash": hash_password(password),
        "role": role,
        "created": time.time(),
        "created_by": get_username(requesting_token) or "unknown",
    }
    
    if expires_at is not None:
        user_data["expires_at"] = expires_at

    users[username] = user_data
    _save_users(users)
    return {"ok": True, "username": username, "role": role, "expires_at": expires_at}


def change_password(requesting_token: str, username: str, old_password: str, new_password: str) -> dict:
    """Altera senha. Admin pode alterar de qualquer um; usuário só a própria."""
    users = _load_users()
    target_user = users.get(username)
    if not target_user:
        return {"ok": False, "error": "Usuário não encontrado"}

    requester = get_username(requesting_token)
    requester_role = get_user_role(requesting_token)

    # Verificar se é admin ou o próprio usuário
    if requester != username and requester_role != "admin":
        return {"ok": False, "error": "Só pode alterar a própria senha"}

    # Se não é admin, verificar senha antiga
    if requester_role != "admin":
        if hash_password(old_password) != target_user.get("password_hash"):
            return {"ok": False, "error": "Senha atual incorreta"}

    target_user["password_hash"] = hash_password(new_password)
    _save_users(users)
    return {"ok": True}


def delete_user(requesting_token: str, username: str) -> dict:
    """Deleta usuário (apenas admin, não pode deletar a si mesmo)."""
    err = require_permission(requesting_token, "user_create")
    if err:
        return err

    requester = get_username(requesting_token)
    if username == requester:
        return {"ok": False, "error": "Não pode deletar a si mesmo"}

    users = _load_users()
    if username not in users:
        return {"ok": False, "error": "Usuário não encontrado"}

    if users[username].get("role") == "admin":
        return {"ok": False, "error": "Não pode deletar admin"}

    del users[username]
    _save_users(users)
    return {"ok": True}


def change_role(requesting_token: str, username: str, new_role: str) -> dict:
    """Altera role de usuário (apenas admin)."""
    err = require_permission(requesting_token, "user_create")
    if err:
        return err

    if new_role not in ROLES:
        return {"ok": False, "error": f"Role inválida: {new_role}"}

    users = _load_users()
    if username not in users:
        return {"ok": False, "error": "Usuário não encontrado"}

    if users[username].get("role") == "admin" and new_role != "admin":
        return {"ok": False, "error": "Não pode remover role admin"}

    users[username]["role"] = new_role
    _save_users(users)
    return {"ok": True, "username": username, "role": new_role}


def get_available_roles() -> dict:
    """Retorna roles disponíveis."""
    return {"ok": True, "roles": ROLES}