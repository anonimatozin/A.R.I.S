"""Guild spaces — servidor Discord pessoal da ARIS com privacidade estrutural.

Três espaços (categorias), criados VIA BOT pelos comandos /soeu /soela /nos:
  /soeu  — só dono + bot (@everyone deny). Canais: chat, avisos, agenda,
           arquivos, comandos.
  /soela — espelho negando o próprio dono (dono deny, parceira allow quando
           designada, bot allow). Inativa até DISCORD_PARTNER_ID existir.
  /nos   — compartilhado (dono + parceira + bot). Canais: agenda-casal,
           avisos, memórias, ideias. Só entra aqui o que for compartilhado
           explicitamente — nunca puxado de canal privado pela ARIS.

Lógica pura (sem discord importado) pra ser testável. A camada do bot
(modules/discord_bot.py) traduz estes planos em chamadas da API.
"""

from __future__ import annotations

import os

# ── Estrutura ─────────────────────────────────────────────────

SOEU_CHANNELS = ("chat", "avisos", "agenda", "arquivos", "comandos")
SOELA_CHANNELS = ("chat", "avisos", "agenda", "arquivos", "comandos")
NOS_CHANNELS = ("agenda-casal", "avisos", "memórias", "ideias")
VOICE_CHANNEL_NAME = "aris-voz"

CATEGORY_SOEu = "soeu"
CATEGORY_SOELA = "soela"
CATEGORY_NOS = "nos"

# Nomes de exibição (com emoji). Preenchido após readback real da API —
# o Discord filtra/força minúsculas em nomes de canal, então nunca assumir:
# criar via API, ler de volta, travar aqui.
DISPLAY_CATEGORIES = {
    CATEGORY_SOEu: "🔒・só-eu",
    CATEGORY_SOELA: "💌・só-ela",
    CATEGORY_NOS: "💞・nós",
}
DISPLAY_CHANNELS = {
    CATEGORY_SOEu: ["💬・conversa", "📢・avisos", "🗓️・agenda", "📁・arquivos", "⚙️・comandos"],
    CATEGORY_SOELA: ["💬・conversa", "📢・avisos", "🗓️・agenda", "📁・arquivos", "⚙️・comandos"],
    CATEGORY_NOS: ["🗓️・agenda-do-casal", "📢・avisos", "💭・memórias", "💡・ideias"],
}
DISPLAY_VOICE = "🎙️・aris-voz"

# Aliases resolvidos a partir do readback (nome real → chave lógica).
# Inclui os nomes antigos simples pra compatibilidade.
CATEGORY_ALIASES = {
    "soeu": CATEGORY_SOEu,
    "soela": CATEGORY_SOELA,
    "nos": CATEGORY_NOS,
}
CHANNEL_ALIASES = {
    "chat": "chat", "conversa": "chat",
    "avisos": "avisos",
    "agenda": "agenda", "agenda-do-casal": "agenda-casal", "agenda-casal": "agenda-casal",
    "arquivos": "arquivos", "comandos": "comandos",
    "memórias": "memórias", "memorias": "memórias",
    "ideias": "ideias", "aris-voz": "aris-voz",
}


def get_owner_id() -> str:
    """Dono: DISCORD_OWNER_ID, senão o primeiro de DISCORD_ALLOWED_USERS."""
    owner = (os.getenv("DISCORD_OWNER_ID", "") or "").strip()
    if owner and owner.isdigit():
        return owner
    csv = os.getenv("DISCORD_ALLOWED_USERS", "") or ""
    for part in csv.split(","):
        part = part.strip()
        if part.isdigit():
            return part
    return ""


def get_partner_id() -> str:
    """Parceira designada (vazio = ainda não existe)."""
    partner = (os.getenv("DISCORD_PARTNER_ID", "") or "").strip()
    return partner if partner.isdigit() else ""


def can_manage_spaces(user_id: str | int, is_admin: bool = False) -> bool:
    """Só o dono (ou admin do servidor) executa /soeu /soela /nos."""
    if is_admin:
        return True
    owner = get_owner_id()
    return bool(owner) and str(user_id) == owner


def build_overwrites(
    space: str, owner_id: str, partner_id: str = ""
) -> dict[str, dict[str, bool | None]]:
    """Overwrites por espaço. Chaves: 'everyone' | 'owner' | 'partner' | 'bot'."""
    if space == CATEGORY_SOEu:
        return {
            "everyone": {"view": False},
            "owner": {"view": True},
            "partner": {"view": False},
            "bot": {"view": True},
        }
    if space == CATEGORY_SOELA:
        return {
            "everyone": {"view": False},
            "owner": {"view": False},
            "partner": {"view": True if partner_id else None},
            "bot": {"view": True},
        }
    if space == CATEGORY_NOS:
        return {
            "everyone": {"view": False},
            "owner": {"view": True},
            "partner": {"view": True if partner_id else None},
            "bot": {"view": True},
        }
    raise ValueError(f"espaço desconhecido: {space}")


def plan_space(space: str) -> dict:
    """Plano de criação: categoria + canais (nomes de exibição)."""
    if space not in (CATEGORY_SOEu, CATEGORY_SOELA, CATEGORY_NOS):
        raise ValueError(f"espaço desconhecido: {space}")
    plan: dict = {
        "category": DISPLAY_CATEGORIES[space],
        "text_channels": list(DISPLAY_CHANNELS[space]),
        "voice_channels": [],
    }
    if space == CATEGORY_NOS:
        plan["voice_channels"] = [DISPLAY_VOICE]
    return plan


def resolve_space(name: str | None) -> str | None:
    """Nome real (categoria) → chave lógica. None = fora dos espaços."""
    if not name:
        return None
    key = (name or "").strip().lower()
    if key in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[key]
    if key in DISPLAY_CATEGORIES.values():
        for k, v in DISPLAY_CATEGORIES.items():
            if v == key:
                return k
    return None


def resolve_channel(name):
    """Nome real (canal) -> chave logica (minusculas, sem emoji)."""
    if not name:
        return None
    import re as _re
    key = (name or "").strip().lower()
    drop = set()
    for lo, hi in ((0x1F000, 0x1FAFF), (0x2600, 0x27BF),
                     (0x2B00, 0x2BFF), (0x3000, 0x303F),
                     (0x30A0, 0x30FF), (0xFE00, 0xFE0F)):
        drop.update(range(lo, hi + 1))
    for extra in (0x00B7, 0x2022, 0x007C, 0x005F, 0x200D):
        drop.add(extra)
    key = "".join(c for c in key if ord(c) not in drop).strip()
    key = _re.sub(r"\s+", "-", key)
    return CHANNEL_ALIASES.get(key)

def classify_guild_message(
    category: str | None,
    channel_name: str,
    author_id: str | int,
    author_is_admin: bool = False,
) -> dict:
    """Decide se mensagem de guild vai pro pipeline e com qual scope.

    Retorna {"route": bool, "scope": str, "allowed": [...], "reason": str}.
    """
    author = str(author_id)
    owner = get_owner_id()
    partner = get_partner_id()
    space = resolve_space(category)
    chan = resolve_channel(channel_name)
    if space is None:
        return {"route": False, "scope": "shared", "allowed": ["shared"],
                "reason": "canal fora dos espaços gerenciados"}
    category = space
    if category == CATEGORY_SOEu and owner and author != owner:
        return {"route": False, "scope": "", "allowed": [],
                "reason": "soeu é só do dono"}
    if category == CATEGORY_SOELA:
        if partner and author != partner:
            return {"route": False, "scope": "", "allowed": [],
                    "reason": "soela é só dela"}
        if not partner and (not owner or author != owner):
            # Sem parceira designada, só o dono (admin) pode testar
            if not author_is_admin:
                return {"route": False, "scope": "", "allowed": [],
                        "reason": "soela inativa até designação"}
    if chan not in CHAT_CHANNELS.get(category, set()):
        return {"route": False, "scope": "shared", "allowed": ["shared"],
                "reason": f"#{channel_name} não é canal de conversa"}
    return {"route": True,
            "scope": channel_scope(category, author, owner, partner),
            "allowed": allowed_scopes(category, author, owner, partner),
            "reason": "ok"}


def channel_scope(
    category: str,
    author_id: str | int,
    owner_id: str = "",
    partner_id: str = "",
) -> str:
    """Scope de ESCRITA pra mensagem neste canal."""
    author = str(author_id)
    owner = owner_id or get_owner_id()
    partner = partner_id or get_partner_id()
    if category == CATEGORY_SOEu:
        return f"private:{owner or author}"
    if category == CATEGORY_SOELA:
        return f"private:{partner or author}"
    return "shared"


def allowed_scopes(
    category: str,
    author_id: str | int,
    owner_id: str = "",
    partner_id: str = "",
) -> list[str]:
    """Scopes de LEITURA permitidos neste canal (filtro de query)."""
    author = str(author_id)
    owner = owner_id or get_owner_id()
    partner = partner_id or get_partner_id()
    if category == CATEGORY_SOEu:
        me = owner or author
        return ["shared", f"private:{me}"]
    if category == CATEGORY_SOELA:
        me = partner or author
        return ["shared", f"private:{me}"]
    if category == CATEGORY_NOS:
        return ["shared"]
    if owner and author == owner:
        return ["shared", f"private:{owner}"]
    if partner and author == partner:
        return ["shared", f"private:{partner}"]
    return ["shared"]


# Canais de escrita livre (conversa com a ARIS) por espaço (chaves lógicas)
CHAT_CHANNELS = {
    CATEGORY_SOEu: {"chat", "arquivos", "comandos"},
    CATEGORY_SOELA: {"chat", "arquivos", "comandos"},
    CATEGORY_NOS: {"agenda-casal", "avisos", "memórias", "ideias"},
}

# Sondagem cruzada ("o que ele te falou?"): resposta determinística, sem LLM.
_CROSS_PROBE_RES = [
    r"o que ele (te )?(falou|disse|contou)",
    r"o que ela (te )?(falou|disse|contou)",
    r"me conta .*ele.*(falou|disse)",
    r"me conta .*ela.*(falou|disse)",
    r"what did (he|she) tell you",
    r"tell me what (he|she) said",
]


def cross_scope_probe_reply(text: str, category: str) -> str | None:
    """Trava determinística: perguntou do outro lado → sem acesso, sem evasiva."""
    import re as _re2
    if category not in (CATEGORY_SOELA, CATEGORY_NOS):
        return None
    tl = (text or "").lower().strip()
    if any(_re2.search(p, tl) for p in _CROSS_PROBE_RES):
        who = "dela" if category == CATEGORY_SOELA else "um do outro"
        return (f"Não tenho acesso às conversas privadas {who} — "
                f"consigo falar só do que foi compartilhado aqui ou com você.")
    return None


# ── Exclusão com trava (padrão CRITICAL: confirmação explícita) ──
DELETE_COMMANDS = {
    "/excluir-soeu": CATEGORY_SOEu,
    "/excluir-soela": CATEGORY_SOELA,
    "/excluir-nos": CATEGORY_NOS,
    "/excluir-tudo": "tudo",
}
DELETE_CONFIRM_PHRASE = {
    CATEGORY_SOEu: CATEGORY_SOEu,
    CATEGORY_SOELA: CATEGORY_SOELA,
    CATEGORY_NOS: CATEGORY_NOS,
    "tudo": "EXCLUIR TUDO",
}
DELETE_TIMEOUT_S = 120.0

_delete_pending: dict[tuple[str, str], float] = {}


def start_delete(user_id: str | int, target: str, now: float | None = None) -> str:
    """Registra pedido de exclusão. Retorna a pergunta de confirmação."""
    import time as _t
    _delete_pending[(str(user_id), target)] = (now if now is not None else _t.time()) + DELETE_TIMEOUT_S
    phrase = DELETE_CONFIRM_PHRASE[target]
    what = "as três categorias (soeu, soela e nos)" if target == "tudo" else f"a categoria /{target}"
    return (f"⚠️ Isso apaga {what} e todos os canais dentro — irreversível. "
            f"Pra confirmar, digite exatamente `{phrase}` em até 2 minutos. "
            f"Qualquer outra coisa cancela.")


def confirm_delete(
    user_id: str | int, text: str, now: float | None = None
) -> tuple[str | None, str]:
    """Tenta confirmar pendência. Retorna (target_confirmado|None, resposta)."""
    import time as _t
    now = now if now is not None else _t.time()
    uid = str(user_id)
    for (u, target), expiry in list(_delete_pending.items()):
        if u != uid:
            continue
        if now > expiry:
            _delete_pending.pop((u, target), None)
            return None, "Tempo esgotado — exclusão cancelada. Recomece com o comando."
        if (text or "").strip() == DELETE_CONFIRM_PHRASE[target]:
            _delete_pending.pop((u, target), None)
            return target, ""
        _delete_pending.pop((u, target), None)
        return None, "Texto diferente — exclusão cancelada. Nada foi apagado."
    return None, ""
