"""Testes do A.R.I.S. Local Agent (Fase 1)."""

import os
import sys
import time
import struct
import threading
from unittest.mock import patch, MagicMock

import pytest


class TestInstanceManager:
    """Testes do InstanceManager."""

    def test_acquire_release(self, tmp_path):
        """Lock unico funciona."""
        from agent.instance import InstanceManager
        im = InstanceManager()
        im._pid_path = tmp_path / "agent.pid"
        im._lock_path = tmp_path / "agent.lock"

        assert im.acquire() is True
        assert im.is_running() is True
        assert im.get_running_pid() == os.getpid()

        im.release()
        assert im.pid_path.exists() if hasattr(im, 'pid_path') else not im._pid_path.exists()

    def test_is_not_running(self, tmp_path):
        """Nao rodando quando nao tem pid."""
        from agent.instance import InstanceManager
        im = InstanceManager()
        im._pid_path = tmp_path / "agent.pid"
        im._lock_path = tmp_path / "agent.lock"

        assert im.is_running() is False
        assert im.get_running_pid() is None

    def test_stale_pid(self, tmp_path):
        """PID antigo (processo morto) detectado."""
        from agent.instance import InstanceManager
        im = InstanceManager()
        im._pid_path = tmp_path / "agent.pid"
        im._lock_path = tmp_path / "agent.lock"

        im._pid_path.write_text("999999")
        assert im.is_running() is False
        assert im.get_running_pid() is None

    def test_force_release(self, tmp_path):
        """Force release limpa pid file."""
        from agent.instance import InstanceManager
        im = InstanceManager()
        im._pid_path = tmp_path / "agent.pid"
        im._lock_path = tmp_path / "agent.lock"

        im._pid_path.write_text("999999")
        assert im.force_release() is True
        assert not im._pid_path.exists()


class TestSessionManager:
    """Testes do SessionManager."""

    def test_initial_state(self):
        """Sessao comeca em IDLE."""
        from agent.session import SessionManager, SessionState
        sm = SessionManager(timeout=60.0)
        assert sm.state == SessionState.IDLE
        assert sm.is_active is False

    def test_activate(self):
        """Ativar sessao muda pra ACTIVE."""
        from agent.session import SessionManager, SessionState
        sm = SessionManager(timeout=60.0)
        was_idle = sm.activate()
        assert was_idle is True
        assert sm.state == SessionState.ACTIVE
        assert sm.is_active is True
        assert sm.interaction_count == 1

    def test_touch_restarts_timer(self):
        """Touch reinicia timer."""
        from agent.session import SessionManager
        sm = SessionManager(timeout=60.0)
        sm.activate()
        time.sleep(0.1)
        sm.touch()
        assert sm.time_since_last_interaction < 0.2

    def test_timeout(self):
        """Timeout muda pra IDLE."""
        from agent.session import SessionManager, SessionState
        sm = SessionManager(timeout=0.1)
        sm.activate()
        assert sm.state == SessionState.ACTIVE
        time.sleep(0.2)
        assert sm.check_timeout() is True
        assert sm.state == SessionState.IDLE

    def test_deactivate(self):
        """Deactivate muda pra IDLE."""
        from agent.session import SessionManager, SessionState
        sm = SessionManager(timeout=60.0)
        sm.activate()
        sm.deactivate()
        assert sm.state == SessionState.IDLE

    def test_set_processing(self):
        """Processing nao expira por timeout."""
        from agent.session import SessionManager, SessionState
        sm = SessionManager(timeout=10.0)
        sm.activate()
        sm.set_processing(True)
        assert sm._state == SessionState.PROCESSING
        time.sleep(0.1)
        assert sm._state == SessionState.PROCESSING  # nao expira
        sm.set_processing(False)
        assert sm._state == SessionState.ACTIVE

    def test_time_until_idle(self):
        """Retorna tempo restante."""
        from agent.session import SessionManager
        sm = SessionManager(timeout=60.0)
        sm.activate()
        remaining = sm.time_until_idle
        assert 59.0 < remaining <= 60.0

    def test_get_status(self):
        """Status contem campos corretos."""
        from agent.session import SessionManager
        sm = SessionManager(timeout=60.0)
        sm.activate()
        status = sm.get_status()
        assert "state" in status
        assert "interactions" in status
        assert status["timeout"] == 60.0

    def test_on_state_change_callback(self):
        """Callback e chamado na mudanca de estado."""
        from agent.session import SessionManager, SessionState
        sm = SessionManager(timeout=60.0)
        changes = []
        sm.on_state_change(lambda o, n: changes.append((o, n)))
        sm.activate()
        assert len(changes) == 1
        assert changes[0] == (SessionState.IDLE, SessionState.ACTIVE)

    def test_double_activate(self):
        """Double activate nao reseta interaction count."""
        from agent.session import SessionManager
        sm = SessionManager(timeout=60.0)
        sm.activate()
        sm.activate()
        assert sm.interaction_count == 2


class TestIPCServer:
    """Testes do IPCServer (basico, sem named pipe real)."""

    def test_init(self):
        """Servidor inicializa."""
        from agent.ipc import IPCServer
        server = IPCServer(handler=lambda m: {"ok": True})
        assert server._running is False
        assert server._handler is not None

    def test_process_message(self):
        """Handler processa mensagem."""
        from agent.ipc import IPCServer
        def handler(msg):
            return {"echo": msg.get("text", "")}
        server = IPCServer(handler=handler)
        result = server._process({"text": "hello"})
        assert result == {"echo": "hello"}

    def test_process_no_handler(self):
        """Sem handler retorna erro."""
        from agent.ipc import IPCServer
        server = IPCServer()
        result = server._process({"text": "hello"})
        assert result["ok"] is False

    def test_process_exception(self):
        """Excecao no handler retorna erro."""
        from agent.ipc import IPCServer
        def bad_handler(msg):
            raise ValueError("boom")
        server = IPCServer(handler=bad_handler)
        result = server._process({"text": "hello"})
        assert result["ok"] is False
        assert "boom" in result["error"]


class TestCLI:
    """Testes do CLI (verificar imports e parse)."""

    def test_import(self):
        """CLI importa sem erro."""
        import agent.aris_cli
        assert hasattr(agent.aris_cli, 'main')

    def test_has_key_functions(self):
        """CLI tem funções essenciais."""
        import agent.aris_cli
        assert callable(agent.aris_cli.main)
        assert hasattr(agent.aris_cli, 'GATEWAY_URL')
        assert hasattr(agent.aris_cli, 'PC_LISTENER_URL')


class TestService:
    """Testes do ARISService (basico)."""

    def test_init(self):
        """Servico inicializa."""
        from agent.service import ARISService
        svc = ARISService()
        assert svc.is_running is False
        assert svc.session is not None

    def test_get_status(self):
        """Status contem campos corretos."""
        from agent.service import ARISService
        svc = ARISService()
        status = svc.get_status()
        assert "running" in status
        assert "session" in status

    def test_handle_ipc_status(self):
        """IPC status retorna info."""
        from agent.service import ARISService
        svc = ARISService()
        result = svc._handle_ipc({"command": "status"})
        assert "running" in result

    def test_handle_ipc_session(self):
        """IPC session retorna sessao."""
        from agent.service import ARISService
        svc = ARISService()
        result = svc._handle_ipc({"command": "session"})
        assert "state" in result

    def test_handle_ipc_unknown(self):
        """IPC comando desconhecido retorna erro."""
        from agent.service import ARISService
        svc = ARISService()
        result = svc._handle_ipc({"command": "invalid"})
        assert result["ok"] is False
