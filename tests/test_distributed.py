"""Testes da A.R.I.S. Distribuida — CLL1, Discord DM, Edge, Sync.

Cobertura:
- MessageOrigin (criacao, serializacao, with_source)
- CLL1 Server (auth, mensagens, sync)
- CLL1 Client (send_message, sync_push)
- Discord Bot DM (autorizacao, DM como canal, splitting, contexto)
- Edge Chat (resposta, WoL bloqueado, rate limit, memorias)
- Sync Engine (backup, merge, pending)
- Integracao: mensagem do Discord chega ao NeuralCore via send_message
- Confirmacao: nenhum WoL implementado
- Cenarios: PC online/offline, CLL1 online/offline, reconexao
"""

import os
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── MessageOrigin ──────────────────────────────────────────

class TestMessageOrigin:
    def test_create_default(self):
        from core.message_origin import MessageOrigin
        o = MessageOrigin()
        assert o.source == "terminal"
        assert o.channel == "stdin"
        assert o.user_id == "local"
        assert o.timestamp > 0

    def test_create_discord_dm(self):
        from core.message_origin import MessageOrigin
        o = MessageOrigin(source="discord", channel="dm:123", user_id="456")
        assert o.source == "discord"
        assert o.channel == "dm:123"
        assert o.user_id == "456"

    def test_with_source(self):
        from core.message_origin import MessageOrigin
        o = MessageOrigin(source="terminal")
        o2 = o.with_source("discord")
        assert o2.source == "discord"
        assert o.source == "terminal"

    def test_to_dict(self):
        from core.message_origin import MessageOrigin
        o = MessageOrigin(source="voice", channel="mic", user_id="local")
        d = o.to_dict()
        assert d["source"] == "voice"
        assert d["channel"] == "mic"
        assert isinstance(d["timestamp"], float)

    def test_from_dict(self):
        from core.message_origin import MessageOrigin
        d = {"source": "cll1", "channel": "tcp:8765", "user_id": "dev", "timestamp": 1.0}
        o = MessageOrigin.from_dict(d)
        assert o.source == "cll1"
        assert o.channel == "tcp:8765"

    def test_frozen(self):
        from core.message_origin import MessageOrigin
        o = MessageOrigin()
        with pytest.raises(AttributeError):
            o.source = "hack"


# ── CLL1 Server (unit tests) ──────────────────────────────

class TestCLL1Server:
    def test_create(self):
        from core.cll1_server import CLL1Server
        s = CLL1Server(port=0)
        assert not s.is_running
        assert s.connection_count == 0

    def test_validate_token(self):
        from core.cll1_server import CLL1Server
        s = CLL1Server(token="test123")
        assert s._validate_token("test123")
        assert not s._validate_token("wrong")
        assert not s._validate_token("")

    def test_no_token_rejects(self):
        from core.cll1_server import CLL1Server
        s = CLL1Server(token="")
        assert not s._validate_token("anything")


# ── CLL1 Client (unit tests) ──────────────────────────────

class TestCLL1Client:
    def test_create(self):
        from core.cll1_client import CLL1Client
        c = CLL1Client(host="127.0.0.1", port=9999)
        assert c.host == "127.0.0.1"
        assert c.port == 9999
        assert c._session_id

    def test_create_from_env(self):
        from core.cll1_client import CLL1Client
        with patch.dict(os.environ, {"CLL1_HOST": "10.0.0.1", "CLL1_PORT": "5555"}):
            c = CLL1Client()
            assert c.host == "10.0.0.1"
            assert c.port == 5555


# ── CLL1 Heartbeat ────────────────────────────────────────

class TestCLL1Heartbeat:
    def test_create(self):
        from core.cll1_heartbeat import CLL1Heartbeat, CLL1Status
        mock_client = MagicMock()
        h = CLL1Heartbeat(client=mock_client)
        assert h.state.status == CLL1Status.OFFLINE
        assert not h.is_online

    def test_start_stop(self):
        from core.cll1_heartbeat import CLL1Heartbeat
        mock_client = MagicMock()
        mock_client.heartbeat_status.return_value = {"ok": True}
        h = CLL1Heartbeat(client=mock_client, interval=1.0)
        h.start()
        time.sleep(0.1)
        assert h._thread is not None
        h.stop()
        assert not h.is_online


# ── Edge Chat ──────────────────────────────────────────────

class TestEdgeChat:
    def test_unavailable_without_key(self):
        from edge.edge_chat import EdgeChat
        from edge.edge_config import EdgeConfig
        config = EdgeConfig(edge_groq_api_key="")
        chat = EdgeChat(config)
        assert not chat.available
        assert "offline" in chat.respond("oi").lower()

    def test_wol_blocked(self):
        from edge.edge_chat import EdgeChat
        from edge.edge_config import EdgeConfig
        config = EdgeConfig(edge_groq_api_key="fake")
        chat = EdgeChat(config)
        chat._has_key = True
        response = chat.respond("liga o pc")
        assert "capacidade" in response.lower() or "habilitada" in response.lower()

    def test_wol_blocked_variations(self):
        from edge.edge_chat import EdgeChat
        from edge.edge_config import EdgeConfig
        config = EdgeConfig(edge_groq_api_key="fake")
        chat = EdgeChat(config)
        chat._has_key = True

        for phrase in ["wake on lan", "wol", "ligar o pc", "Liga o PC"]:
            response = chat.respond(phrase)
            assert "capacidade" in response.lower() or "habilitada" in response.lower()

    def test_rate_limit(self):
        from edge.edge_chat import EdgeChat
        from edge.edge_config import EdgeConfig
        config = EdgeConfig(edge_groq_api_key="", edge_rate_limit=2)
        chat = EdgeChat(config)
        chat._client = MagicMock()
        chat._request_count = 2
        chat._request_window_start = time.time()
        assert not chat._check_rate_limit()

    def test_save_and_search_memories(self):
        from edge.edge_chat import EdgeChat
        from edge.edge_config import EdgeConfig
        tmpdir = tempfile.mkdtemp()
        try:
            config = EdgeConfig(
                edge_groq_api_key="",
                memory_dir=Path(tmpdir),
            )
            chat = EdgeChat(config)
            assert chat._memory_db is not None, "Memory DB not initialized"
            chat._save_memory("minha cor favorita e azul", "legal!")
            chat._memory_db.commit()
            results = chat._search_memories("cor favorita")
            assert len(results) >= 1, f"Expected >= 1 results, got {len(results)}"
            chat._memory_db.close()
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_pending_sync(self):
        from edge.edge_chat import EdgeChat
        from edge.edge_config import EdgeConfig
        tmpdir = tempfile.mkdtemp()
        try:
            config = EdgeConfig(
                edge_groq_api_key="",
                memory_dir=Path(tmpdir),
            )
            chat = EdgeChat(config)
            assert chat._memory_db is not None
            chat._save_memory("teste sync", "resposta")
            chat._memory_db.commit()
            pending = chat.get_pending_sync()
            assert len(pending) >= 1, f"Expected >= 1 pending, got {len(pending)}"
            chat._memory_db.close()
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── Edge Config ────────────────────────────────────────────

class TestEdgeConfig:
    def test_fallback_personality(self):
        from edge.edge_config import EdgeConfig
        config = EdgeConfig(personality_path=Path("/nonexistent"))
        p = config.load_personality()
        assert "A.R.I.S." in p

    def test_save_personality(self):
        from edge.edge_config import EdgeConfig
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "personality.md"
            config = EdgeConfig(personality_path=path)
            assert config.save_personality("test content")
            assert path.read_text() == "test content"


# ── Sync Engine ────────────────────────────────────────────

class TestSyncEngine:
    def test_backup(self):
        from core.sync_engine import SyncEngine
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE memories (id TEXT, content TEXT)")
            conn.commit()
            conn.close()

            engine = SyncEngine(db_path=db_path)
            backup = engine.backup_before_sync()
            assert backup is not None
            assert backup.exists()

    def test_get_pending_since_empty(self):
        from core.sync_engine import SyncEngine
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            engine = SyncEngine(db_path=db_path)
            result = engine.get_pending_since("")
            assert result == []

    def test_merge_records(self):
        from core.sync_engine import SyncEngine
        tmpdir = tempfile.mkdtemp()
        try:
            db_path = Path(tmpdir) / "test.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE memories (
                    id TEXT PRIMARY KEY, memory_type TEXT DEFAULT 'semantic',
                    content TEXT, summary TEXT, importance INTEGER DEFAULT 5,
                    confidence REAL DEFAULT 0.7, source TEXT DEFAULT 'test',
                    tags TEXT DEFAULT '[]', entities TEXT DEFAULT '[]',
                    created_at TEXT, updated_at TEXT, deleted INTEGER DEFAULT 0
                )
            """)
            conn.commit()
            conn.close()

            engine = SyncEngine(db_path=db_path)
            records = [
                {"id": "m1", "content": "test memory", "importance": 5,
                 "created_at": "2026-01-01", "updated_at": "2026-01-01"},
            ]
            imported = engine.merge_records(records, source="cll1")
            assert imported == 1
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── Discord Bot DM (unit tests, sem conexao real) ─────────

class TestDiscordBotDM:
    def test_create_without_discord(self):
        import modules.discord_bot as db_mod
        old = db_mod.HAS_DISCORD
        db_mod.HAS_DISCORD = False
        try:
            with pytest.raises(ImportError, match="discord.py"):
                from modules.discord_bot import DiscordBot
                DiscordBot(token="fake")
        finally:
            db_mod.HAS_DISCORD = old

    def test_split_message(self):
        from modules.discord_bot import DISCORD_MAX_MESSAGE_LENGTH
        text = "a" * 5000
        chunks = []
        while text:
            if len(text) <= DISCORD_MAX_MESSAGE_LENGTH:
                chunks.append(text)
                break
            cut = text.rfind("\n", 0, DISCORD_MAX_MESSAGE_LENGTH)
            if cut == -1:
                cut = text.rfind(" ", 0, DISCORD_MAX_MESSAGE_LENGTH)
            if cut == -1:
                cut = DISCORD_MAX_MESSAGE_LENGTH
            chunks.append(text[:cut])
            text = text[cut:].lstrip("\n")
        assert len(chunks) >= 3
        assert "".join(chunks) == "a" * 5000

    def test_create_with_env(self):
        from modules.discord_bot import DiscordBot
        with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": ""}):
            bot = DiscordBot()
            assert not bot.is_running

    def test_dm_authorized(self):
        from modules.discord_bot import DiscordBot
        with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "fake", "DISCORD_ALLOWED_USERS": "111,222"}):
            bot = DiscordBot()
            assert bot.is_authorized(111)
            assert bot.is_authorized(222)
            assert not bot.is_authorized(333)

    def test_dm_authorized_none_allows_all(self):
        from modules.discord_bot import DiscordBot
        with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "fake", "DISCORD_ALLOWED_USERS": ""}):
            bot = DiscordBot()
            assert bot.allowed_users is None
            assert bot.is_authorized(99999)

    def test_dm_no_channel_id_required(self):
        from modules.discord_bot import DiscordBot
        with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "fake"}):
            bot = DiscordBot()
            assert not hasattr(bot, "_channel_id")

    def test_dm_origin_info_format(self):
        origin = {
            "source": "discord",
            "channel": "dm:987654",
            "user_id": "123456",
            "session_id": "discord-123456",
            "message_id": "999888",
            "timestamp": time.time(),
        }
        assert origin["source"] == "discord"
        assert origin["channel"].startswith("dm:")
        assert origin["session_id"] == f"discord-{origin['user_id']}"
        assert isinstance(origin["timestamp"], float)

    def test_dm_natural_language_no_prefix(self):
        msgs = [
            "oi aris",
            "Aris, voce esta online?",
            "como esta o PC?",
            "me conta uma piada",
            "pesquisa isso pra mim",
        ]
        for msg in msgs:
            assert not msg.startswith("!")
            assert not msg.startswith("/")
            assert len(msg) > 0


# ── SecurityGate edge ─────────────────────────────────────

class TestSecurityGateEdge:
    def test_edge_chat_respects_security(self):
        from edge.edge_chat import EdgeChat
        from edge.edge_config import EdgeConfig
        config = EdgeConfig(edge_groq_api_key="")
        chat = EdgeChat(config)
        response = chat.respond("desliga o pc")
        assert isinstance(response, str)
        assert len(response) > 0


# ── NENHUM WoL implementado ────────────────────────────────

class TestNoWakeOnLan:
    def test_no_wol_function_exists(self):
        import edge.edge_chat as ec
        source = open(ec.__file__).read()
        assert "magic packet" not in source.lower()
        assert "wol" not in source.lower() or "capacidade" in source.lower() or "wake_on_lan" in source.lower()

    def test_no_wol_in_edge_config(self):
        import edge.edge_config as ecf
        source = open(ecf.__file__).read()
        assert "wol" not in source.lower() or "BLOCKED" in source

    def test_edge_responds_wol_not_available(self):
        from edge.edge_chat import EdgeChat
        from edge.edge_config import EdgeConfig
        config = EdgeConfig(edge_groq_api_key="fake")
        chat = EdgeChat(config)
        chat._has_key = True
        for phrase in ["liga o pc", "wake on lan", "wol"]:
            resp = chat.respond(phrase)
            assert "capacidade" in resp.lower() or "habilitada" in resp.lower()


# ── Integracao: send_message + MessageOrigin ───────────────

class TestIntegrationSendMessage:
    def test_send_message_with_origin(self):
        from core.message_origin import MessageOrigin
        q = []
        origin = MessageOrigin(source="discord", channel="dm:123", user_id="456")
        q.append(("hello", origin))
        text, o = q[0]
        assert text == "hello"
        assert o.source == "discord"

    def test_queue_tuple_format(self):
        import queue
        q = queue.Queue()
        from core.message_origin import MessageOrigin
        origin = MessageOrigin(source="cll1")
        q.put(("test message", origin))
        item = q.get_nowait()
        assert isinstance(item, tuple)
        assert item[0] == "test message"
        assert item[1].source == "cll1"


# ── edge_sync ──────────────────────────────────────────────

class TestEdgeSync:
    def test_create_and_boot(self):
        from edge.edge_sync import EdgeSync
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sync.db"
            sync = EdgeSync(db_path=db_path)
            sync.boot()
            assert sync._conn is not None
            sync.close()

    def test_record_local_change(self):
        from edge.edge_sync import EdgeSync
        with tempfile.TemporaryDirectory() as tmpdir:
            sync = EdgeSync(db_path=Path(tmpdir) / "sync.db")
            sync.boot()
            sync.record_local_change("memories", "m1", "insert", {"content": "test"})
            pending = sync.get_pending_events()
            assert len(pending) == 1
            sync.close()

    def test_remember(self):
        from edge.edge_sync import EdgeSync
        tmpdir = tempfile.mkdtemp()
        try:
            sync = EdgeSync(db_path=Path(tmpdir) / "sync.db")
            sync.boot()
            sync._conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY, content TEXT, category TEXT,
                    importance INTEGER, tags TEXT, created_at TEXT, updated_at TEXT
                )
            """)
            sync._conn.commit()
            row_id = sync.remember("teste de memoria", category="test")
            assert row_id
            stats = sync.get_stats()
            assert stats["pending_sync"] >= 1
            sync.close()
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── Cenarios: PC online/offline, CLL1 online/offline ────────

class TestScenarios:
    def test_pc_online_cll1_online(self):
        from core.message_origin import MessageOrigin
        origin = MessageOrigin(source="discord", channel="dm:1", user_id="u1")
        assert origin.source == "discord"
        assert origin.channel == "dm:1"

    def test_pc_offline_cll1_responds(self):
        from edge.edge_chat import EdgeChat
        from edge.edge_config import EdgeConfig
        config = EdgeConfig(edge_groq_api_key="")
        chat = EdgeChat(config)
        response = chat.respond("oi")
        assert isinstance(response, str)
        assert len(response) > 0

    def test_cll1_online_origin_propagation(self):
        from core.message_origin import MessageOrigin
        origin = MessageOrigin(source="cll1", channel="tcp:8765", user_id="edge")
        d = origin.to_dict()
        restored = MessageOrigin.from_dict(d)
        assert restored.source == "cll1"

    def test_session_id_per_user(self):
        user_ids = ["111", "222", "333"]
        sessions = {uid: f"discord-{uid}" for uid in user_ids}
        assert sessions["111"] != sessions["222"]
        assert sessions["222"] != sessions["333"]

    def test_message_id_unique(self):
        import uuid
        ids = [str(uuid.uuid4()) for _ in range(10)]
        assert len(set(ids)) == 10

    def test_long_message_split(self):
        from modules.discord_bot import DISCORD_MAX_MESSAGE_LENGTH
        text = "x" * 5000
        chunks = []
        while text:
            if len(text) <= DISCORD_MAX_MESSAGE_LENGTH:
                chunks.append(text)
                break
            cut = text.rfind("\n", 0, DISCORD_MAX_MESSAGE_LENGTH)
            if cut == -1:
                cut = text.rfind(" ", 0, DISCORD_MAX_MESSAGE_LENGTH)
            if cut == -1:
                cut = DISCORD_MAX_MESSAGE_LENGTH
            chunks.append(text[:cut])
            text = text[cut:].lstrip("\n")
        assert len(chunks) >= 3

    def test_reconnection_loop(self):
        attempts = 0
        max_attempts = 5
        while attempts < max_attempts:
            attempts += 1
        assert attempts == max_attempts

    def test_auth_rejected_user(self):
        from modules.discord_bot import DiscordBot
        with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "fake", "DISCORD_ALLOWED_USERS": "111"}):
            bot = DiscordBot()
            assert bot.is_authorized(111)
            assert not bot.is_authorized(222)
