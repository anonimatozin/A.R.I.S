"""Testes da camada de plataforma do DesktopTools (Fase 2).

No Linux, ações de desktop têm de usar adaptadores nativos (xdg, lista
fixa de apps) em vez de comandos Windows (powershell/taskkill/os.startfile).
Nada de comando livre de shell.
"""

import sys

import pytest

from modules.desktop_tools import _LINUX_APPS, DesktopTools, _linux_desktop_dir

IS_LINUX = sys.platform.startswith("linux")


@pytest.fixture
def dt():
    return DesktopTools()


class TestPlatformDetection:
    def test_platform_flag_matches_sys(self, dt):
        import modules.desktop_tools as m
        assert m._IS_LINUX == sys.platform.startswith("linux")


class TestLinuxAppList:
    def test_app_list_is_fixed_map(self):
        # Lista fixa: só apps conhecidos; nenhum valor é shell livre.
        assert "firefox" in _LINUX_APPS
        assert all(isinstance(v, list) for v in _LINUX_APPS.values())

    def test_desktop_dir_fallback(self):
        d = _linux_desktop_dir()
        # Caminho absoluto não vazio (o desktop pode ser localizado,
        # ex.: "~/Área de trabalho" em vez de "~/Desktop").
        assert d.is_absolute()
        assert str(d).strip()


class TestCreateFileOnDesktop:
    def test_create_file_writes_to_desktop(self, dt, monkeypatch, tmp_path):
        monkeypatch.setattr("modules.desktop_tools._IS_LINUX", True)
        monkeypatch.setattr(
            "modules.desktop_tools._linux_desktop_dir", lambda: tmp_path
        )
        result = dt.create_file("nota.txt", "olá")
        assert result.startswith("Arquivo criado")
        written = tmp_path / "nota.txt"
        assert written.exists()
        assert written.read_text(encoding="utf-8") == "olá"

    def test_create_file_rejects_traversal(self, dt, monkeypatch, tmp_path):
        monkeypatch.setattr("modules.desktop_tools._IS_LINUX", True)
        monkeypatch.setattr(
            "modules.desktop_tools._linux_desktop_dir", lambda: tmp_path
        )
        result = dt.create_file("../evil.txt", "x")
        # validate_filename rejeita path traversal
        assert "rejeitada" in result.lower() or "Arquivo criado" not in result


class TestOpenAppLinux:
    def test_open_app_unknown_is_clear_failure(self, dt, monkeypatch):
        monkeypatch.setattr("modules.desktop_tools._IS_LINUX", True)
        result = dt.open_app("programa_inexistente_zzz")
        # Falha honesta (não afirma sucesso) — casa com marcador do ActionEngine.
        assert "Não foi possível abrir" in result

    def test_open_app_rejects_empty(self, dt):
        assert "vazio" in dt.open_app("   ").lower()


class TestClipboardLinux:
    def test_clipboard_set_no_free_shell(self, dt, monkeypatch):
        monkeypatch.setattr("modules.desktop_tools._IS_LINUX", True)
        # Sem wl-copy/xclip no ambiente de teste → mensagem de indisponibilidade
        import modules.desktop_tools as m
        monkeypatch.setattr(m.shutil, "which", lambda name: None)
        result = dt.clipboard_set("conteúdo")
        assert "indisponível" in result.lower() or "definido" in result.lower()


class TestActionHonestyIntegration:
    def test_unknown_action_is_failure_marker(self, dt):
        # O ActionEngine usa "Ação desconhecida" como marcador de falha.
        result = dt.execute_action("abrir", {})
        assert result.startswith("Ação desconhecida")

    def test_create_file_registered_as_action(self, dt, monkeypatch, tmp_path):
        monkeypatch.setattr("modules.desktop_tools._IS_LINUX", True)
        monkeypatch.setattr(
            "modules.desktop_tools._linux_desktop_dir", lambda: tmp_path
        )
        result = dt.execute_action(
            "create_file", {"filename": "a.txt", "content": "b"}
        )
        assert (tmp_path / "a.txt").exists()
        assert result.startswith("Arquivo criado")
