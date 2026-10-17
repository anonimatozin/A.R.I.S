"""Espaços do servidor + privacidade estrutural de memória (sem Discord real)."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules import guild_spaces as gs
from modules.home_control import handle as home_handle, parse as home_parse

OWNER = "111"
PARTNER = "222"
OUTSIDER = "333"

ENV = {"DISCORD_OWNER_ID": OWNER, "DISCORD_PARTNER_ID": PARTNER,
       "DISCORD_ALLOWED_USERS": f"{OWNER},{PARTNER}"}


# ── Estrutura ─────────────────────────────────────────────────

def test_overwrites_soeu_private_owner_only():
    ow = gs.build_overwrites("soeu", OWNER, PARTNER)
    assert ow["everyone"]["view"] is False
    assert ow["owner"]["view"] is True
    assert ow["partner"]["view"] is False
    assert ow["bot"]["view"] is True


def test_overwrites_soela_denies_owner():
    ow = gs.build_overwrites("soela", OWNER, PARTNER)
    assert ow["owner"]["view"] is False
    assert ow["partner"]["view"] is True


def test_overwrites_nos_shared():
    ow = gs.build_overwrites("nos", OWNER, PARTNER)
    assert ow["owner"]["view"] is True
    assert ow["partner"]["view"] is True
    assert ow["everyone"]["view"] is False


def test_plan_channels_and_voice():
    soeu = gs.plan_space("soeu")
    assert len(soeu["text_channels"]) == 5
    assert all(gs.resolve_channel(c) for c in soeu["text_channels"])
    assert soeu["voice_channels"] == []
    nos = gs.plan_space("nos")
    assert len(nos["text_channels"]) == 4
    assert all(gs.resolve_channel(c) for c in nos["text_channels"])
    assert len(nos["voice_channels"]) == 1
    assert gs.resolve_channel(nos["voice_channels"][0]) == "aris-voz"


def test_manage_restricted_to_owner():
    with patch.dict(os.environ, ENV, clear=False):
        assert gs.can_manage_spaces(OWNER) is True
        assert gs.can_manage_spaces(PARTNER) is False
        assert gs.can_manage_spaces(OUTSIDER) is False
        assert gs.can_manage_spaces(OUTSIDER, is_admin=True) is True


# ── Scope ─────────────────────────────────────────────────────

def test_scope_mapping():
    with patch.dict(os.environ, ENV, clear=False):
        assert gs.channel_scope("soeu", OWNER) == f"private:{OWNER}"
        assert gs.channel_scope("soela", PARTNER) == f"private:{PARTNER}"
        assert gs.channel_scope("nos", OWNER) == "shared"
        assert gs.allowed_scopes("soeu", OWNER) == ["shared", f"private:{OWNER}"]
        assert gs.allowed_scopes("soela", PARTNER) == ["shared", f"private:{PARTNER}"]
        assert gs.allowed_scopes("nos", OWNER) == ["shared"]
        # Outro lado nunca entra na lista
        assert f"private:{PARTNER}" not in gs.allowed_scopes("soeu", OWNER)
        assert f"private:{OWNER}" not in gs.allowed_scopes("soela", PARTNER)


def test_classify_blocks_outsider_and_unknown():
    with patch.dict(os.environ, ENV, clear=False):
        r = gs.classify_guild_message("soeu", "chat", OUTSIDER)
        assert r["route"] is False
        r = gs.classify_guild_message("aleatorio", "chat", OWNER)
        assert r["route"] is False
        r = gs.classify_guild_message("soeu", "chat", OWNER)
        assert r["route"] is True
        assert r["scope"] == f"private:{OWNER}"


def test_cross_probe_deterministic():
    with patch.dict(os.environ, ENV, clear=False):
        r = gs.cross_scope_probe_reply("o que ele te falou ontem?", "soela")
        assert r is not None
        assert "cesso" in r and "conversas privadas" in r
        assert gs.cross_scope_probe_reply("o que ele te falou?", "soeu") is None
        assert gs.cross_scope_probe_reply("qual a previsão do tempo?", "soela") is None


# ── Isolamento real (usuário simulado = parceira) ─────────────

def _edge_chat(tmpdir):
    from edge.edge_chat import EdgeChat
    from edge.edge_config import EdgeConfig
    cfg = EdgeConfig(edge_groq_api_key="test-key", memory_dir=Path(tmpdir))
    return EdgeChat(cfg)


def test_edge_isolation_simulated_partner(tmp_path):
    """Ele fala no privado dele; 'ela' (simulada) não alcança via query."""
    chat = _edge_chat(str(tmp_path))
    chat._save_memory("meu salário é 15 mil e a senha do cofre é 1234",
                      "anotado", scope=f"private:{OWNER}")
    chat._save_memory("receita de bolo compartilhada", "anotado", scope="shared")
    # Ela pergunta no canal dela: filtro = shared + private:dela
    got = chat._search_memories("salário", allowed_scopes=["shared", f"private:{PARTNER}"])
    assert all("salário" not in m.get("content", "") for m in got)
    got_shared = chat._search_memories("bolo", allowed_scopes=["shared", f"private:{PARTNER}"])
    assert any("bolo" in m.get("content", "") for m in got_shared)
    # Ele alcança o próprio
    got_owner = chat._search_memories("salário", allowed_scopes=["shared", f"private:{OWNER}"])
    assert any("salário" in m.get("content", "") for m in got_owner)
    # Lista vazia = nada (nunca tudo)
    assert chat._search_memories("salário", allowed_scopes=[]) == []


def test_memory_manager_scope(tmp_path):
    from core.memory import MemoryManager
    from core.memory_models import MemoryCategory
    from utils.logger import Logger
    log = Logger(name="t", log_dir=str(tmp_path), level="CRITICAL")
    mm = MemoryManager(logger=log, db_dir=tmp_path / "db")
    mm.save("segredo", "conteúdo privado do dono", category=MemoryCategory.CONVERSATIONS,
            scope=f"private:{OWNER}")
    mm.save("público", "conteúdo compartilhado", category=MemoryCategory.CONVERSATIONS,
            scope="shared")
    hers = mm.search("conteúdo", allowed_scopes=["shared", f"private:{PARTNER}"])
    assert [m.title for m in hers] == ["público"]
    his = mm.search("conteúdo", allowed_scopes=["shared", f"private:{OWNER}"])
    assert {m.title for m in his} == {"segredo", "público"}
    assert mm.search("conteúdo", allowed_scopes=[]) == []


def test_probe_reply_end_to_end_simulated():
    """'o que ele te falou?' no canal dela → sem acesso, sem invenção."""
    with patch.dict(os.environ, ENV, clear=False):
        reply = gs.cross_scope_probe_reply("o que ele te falou?", "soela")
        assert reply is not None
        assert "15 mil" not in reply and "1234" not in reply


# ── Aliases de exibição ───────────────────────────────────────

def test_resolve_display_names():
    assert gs.resolve_space("🔒・só-eu") == "soeu"
    assert gs.resolve_space("soeu") == "soeu"
    assert gs.resolve_space("💞・nós") == "nos"
    assert gs.resolve_space("aleatorio") is None
    assert gs.resolve_channel("💬・conversa") == "chat"
    assert gs.resolve_channel("chat") == "chat"
    assert gs.resolve_channel("🗓️・agenda-do-casal") == "agenda-casal"
    assert gs.resolve_channel("💭・memórias") == "memórias"


def test_classify_display_names():
    with patch.dict(os.environ, ENV, clear=False):
        r = gs.classify_guild_message("🔒・só-eu", "💬・conversa", OWNER)
        assert r["route"] is True
        assert r["scope"] == f"private:{OWNER}"
        r = gs.classify_guild_message("💞・nós", "💡・ideias", OWNER)
        assert r["route"] is True
        assert r["scope"] == "shared"


def test_plan_uses_display_names():
    p = gs.plan_space("nos")
    assert any("aris-voz" in v for v in p["voice_channels"])
    assert any("mem" in c for c in p["text_channels"])


# ── Exclusão com trava ────────────────────────────────────────

def test_delete_requires_exact_phrase():
    gs._delete_pending.clear()
    q = gs.start_delete(OWNER, "soeu")
    assert "soeu" in q and "irrevers" in q
    # texto errado = cancela, nada confirmado
    target, reply = gs.confirm_delete(OWNER, "pode apagar")
    assert target is None
    assert "cancelada" in reply
    # sem pendência = silencioso
    target, reply = gs.confirm_delete(OWNER, "soeu")
    assert target is None and reply == ""


def test_delete_confirms_exact_phrase():
    gs._delete_pending.clear()
    gs.start_delete(OWNER, "soeu", now=1000.0)
    target, _ = gs.confirm_delete(OWNER, "soeu", now=1001.0)
    assert target == "soeu"
    # uso único: de novo = silencioso
    target, reply = gs.confirm_delete(OWNER, "soeu", now=1002.0)
    assert target is None and reply == ""


def test_delete_tudo_needs_full_phrase():
    gs._delete_pending.clear()
    gs.start_delete(OWNER, "tudo", now=1000.0)
    target, reply = gs.confirm_delete(OWNER, "tudo", now=1001.0)
    assert target is None and "cancelada" in reply
    gs.start_delete(OWNER, "tudo", now=1000.0)
    target, _ = gs.confirm_delete(OWNER, "EXCLUIR TUDO", now=1001.0)
    assert target == "tudo"


def test_delete_expires():
    gs._delete_pending.clear()
    gs.start_delete(OWNER, "nos", now=1000.0)
    target, reply = gs.confirm_delete(OWNER, "nos", now=1000.0 + 121)
    assert target is None and "esgotado" in reply


def test_delete_other_user_cannot_confirm():
    gs._delete_pending.clear()
    gs.start_delete(OWNER, "soeu", now=1000.0)
    target, reply = gs.confirm_delete(OUTSIDER, "soeu", now=1001.0)
    assert target is None and reply == ""
    target, _ = gs.confirm_delete(OWNER, "soeu", now=1001.0)
    assert target == "soeu"


def test_delete_space_removes_category_and_channels():
    import asyncio
    from modules.discord_bot import DiscordBot
    with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "fake",
                                 "DISCORD_ALLOWED_USERS": OWNER}):
        bot = DiscordBot()

    deleted = []

    class FakeCh:
        def __init__(self, name):
            self.name = name
        async def delete(self):
            deleted.append(("ch", self.name))

    class FakeCat:
        def __init__(self, name):
            self.name = name
            self.channels = [FakeCh("x"), FakeCh("y")]
        async def delete(self):
            deleted.append(("cat", self.name))

    class FakeGuild:
        categories = [FakeCat("soeu"), FakeCat("outra")]

    msg = asyncio.new_event_loop().run_until_complete(
        bot._delete_space(FakeGuild(), "soeu"))
    assert "soeu" in msg
    assert ("cat", "soeu") in deleted
    assert all(d[1] != "outra" for d in deleted)


# ── Voz (guarda honesta) ──────────────────────────────────────

def test_join_voice_without_channel_reports_pending():
    import asyncio
    from modules.discord_bot import DiscordBot
    with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "fake",
                                 "DISCORD_ALLOWED_USERS": OWNER}):
        bot = DiscordBot()
    class FakeGuild:
        voice_channels = []
    msg = asyncio.new_event_loop().run_until_complete(bot._join_voice(FakeGuild()))
    assert "Crie o /nos primeiro" in msg


def test_join_voice_names_missing_recv():
    import asyncio
    import discord
    from modules.discord_bot import DiscordBot
    with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "fake",
                                 "DISCORD_ALLOWED_USERS": OWNER}):
        bot = DiscordBot()
    class FakeChannel:
        name = "aris-voz"
    class FakeGuild:
        voice_channels = [FakeChannel()]
    msg = asyncio.new_event_loop().run_until_complete(bot._join_voice(FakeGuild()))
    assert "voice-recv" in msg  # declara o pendente, não mocka


# ── Casa (sem mock de execução) ───────────────────────────────

def test_home_ignores_substrings():
    # "ligar o pc" contém "ar" como substring — não é comando de casa
    assert home_parse("ligar o pc") is None
    assert home_parse("Liga o PC") is None
    assert home_parse("acende a luz da sala") is not None


def test_home_parses_and_refuses_without_hardware():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("HOME_API_URL", None)
        assert home_parse("acende a luz da sala") == {"action": "on", "device": "luz", "room": "sala"}
        assert home_parse("qual a previsão do tempo?") is None
        r = home_handle("apaga a luz do quarto")
        assert r is not None
        assert "não executei nada" in r
        assert "ligad" not in r.replace("desligado", "")
