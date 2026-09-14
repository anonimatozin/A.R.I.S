"""Tests for BLOCO 1 — Command Injection prevention.

Validates that shell metacharacters are rejected in all handlers
that cross the process boundary.
"""

import pytest

from core.security.shell import (
    ShellInjectionError,
    InputValidationError,
    validate_shell_input,
    validate_filename,
    validate_process_name,
    validate_url,
    COMMAND_WHITELIST,
    get_command,
)


# ── validate_shell_input ───────────────────────────────────


class TestShellInputValidation:
    def test_clean_text_passes(self):
        assert validate_shell_input("olá mundo") == "olá mundo"

    def test_clean_text_with_numbers(self):
        assert validate_shell_input("arquivo 2024.txt") == "arquivo 2024.txt"

    def test_semicolon_rejected(self):
        with pytest.raises(ShellInjectionError, match="proibido"):
            validate_shell_input("'; calc.exe; echo '")

    def test_pipe_rejected(self):
        with pytest.raises(ShellInjectionError):
            validate_shell_input("texto | whoami")

    def test_ampersand_rejected(self):
        with pytest.raises(ShellInjectionError):
            validate_shell_input("texto & calc.exe")

    def test_dollar_rejected(self):
        with pytest.raises(ShellInjectionError):
            validate_shell_input("$env:PATH")

    def test_backtick_rejected(self):
        with pytest.raises(ShellInjectionError):
            validate_shell_input("`whoami`")

    def test_newline_rejected(self):
        with pytest.raises(ShellInjectionError):
            validate_shell_input("linha1\n linha2")

    def test_redirect_rejected(self):
        with pytest.raises(ShellInjectionError):
            validate_shell_input("texto > /tmp/x")

    def test_parentheses_rejected(self):
        with pytest.raises(ShellInjectionError):
            validate_shell_input("(calc)")

    def test_curly_braces_rejected(self):
        with pytest.raises(ShellInjectionError):
            validate_shell_input("{calc}")

    def test_dollar_paren_bypass_rejected(self):
        with pytest.raises(ShellInjectionError):
            validate_shell_input("$(whoami)")

    def test_dollar_brace_bypass_rejected(self):
        with pytest.raises(ShellInjectionError):
            validate_shell_input("${IFS}")

    def test_hex_escape_rejected(self):
        with pytest.raises(ShellInjectionError):
            validate_shell_input("\\x41")

    def test_percent_encoding_rejected(self):
        with pytest.raises(ShellInjectionError):
            validate_shell_input("%0a calc")


# ── validate_filename ──────────────────────────────────────


class TestFilenameValidation:
    def test_clean_filename(self):
        assert validate_filename("screenshot.png") == "screenshot.png"

    def test_filename_with_spaces(self):
        assert validate_filename("my file.txt") == "my file.txt"

    def test_path_separator_rejected(self):
        with pytest.raises(InputValidationError, match="separadores"):
            validate_filename("../../etc/passwd")

    def test_backslash_rejected(self):
        with pytest.raises(InputValidationError):
            validate_filename("..\\..\\Windows\\System32")

    def test_dotdot_rejected(self):
        with pytest.raises(InputValidationError):
            validate_filename("..")

    def test_empty_rejected(self):
        with pytest.raises(InputValidationError):
            validate_filename("")

    def test_whitespace_only_rejected(self):
        with pytest.raises(InputValidationError):
            validate_filename("   ")

    def test_windows_special_chars_rejected(self):
        with pytest.raises(InputValidationError):
            validate_filename('file:?*.txt')

    def test_semicolon_in_filename_rejected(self):
        with pytest.raises(ShellInjectionError):
            validate_filename("file;calc.txt")


# ── validate_process_name ──────────────────────────────────


class TestProcessNameValidation:
    def test_clean_process_name(self):
        assert validate_process_name("chrome") == "chrome"

    def test_process_name_with_underscore(self):
        assert validate_process_name("my_process") == "my_process"

    def test_process_name_with_hyphen(self):
        assert validate_process_name("my-process") == "my-process"

    def test_process_name_with_dot(self):
        assert validate_process_name("python.exe") == "python.exe"

    def test_injection_in_process_name(self):
        with pytest.raises(ShellInjectionError):
            validate_process_name("'; calc; echo '")

    def test_path_in_process_name_rejected(self):
        with pytest.raises(InputValidationError):
            validate_process_name("C:\\Windows\\system32\\cmd.exe")

    def test_space_in_process_name_rejected(self):
        with pytest.raises(InputValidationError):
            validate_process_name("chrome browser")


# ── validate_url ───────────────────────────────────────────


class TestURLValidation:
    def test_https_passes(self):
        assert validate_url("https://example.com") == "https://example.com"

    def test_http_passes(self):
        assert validate_url("http://example.com") == "http://example.com"

    def test_file_scheme_rejected(self):
        with pytest.raises(InputValidationError, match="Esquema"):
            validate_url("file:///etc/passwd")

    def test_ftp_rejected(self):
        with pytest.raises(InputValidationError):
            validate_url("ftp://example.com")

    def test_localhost_rejected(self):
        with pytest.raises(InputValidationError, match="localhost"):
            validate_url("http://localhost:8080")

    def test_127_rejected(self):
        with pytest.raises(InputValidationError, match="127.0.0.1"):
            validate_url("http://127.0.0.1/admin")

    def test_link_local_rejected(self):
        with pytest.raises(InputValidationError, match="169.254"):
            validate_url("http://169.254.169.254/latest/meta-data/")

    def test_private_ip_rejected(self):
        with pytest.raises(InputValidationError, match="privado"):
            validate_url("http://192.168.1.1/admin")

    def test_ipv6_loopback_rejected(self):
        with pytest.raises(InputValidationError):
            validate_url("http://[::1]/admin")


# ── Whitelist ──────────────────────────────────────────────


class TestCommandWhitelist:
    def test_whitelist_has_entries(self):
        assert len(COMMAND_WHITELIST) > 0

    def test_clipboard_get_exists(self):
        cmd = get_command("clipboard_get")
        assert cmd is not None
        assert cmd.executable == "powershell"

    def test_clipboard_set_exists(self):
        cmd = get_command("clipboard_set")
        assert cmd is not None
        assert 3 in cmd.input_positions

    def test_focus_window_exists(self):
        cmd = get_command("focus_window")
        assert cmd is not None
        assert 1 in cmd.input_positions

    def test_close_app_exists(self):
        cmd = get_command("close_app")
        assert cmd is not None
        assert cmd.executable == "taskkill"

    def test_unknown_command_returns_none(self):
        assert get_command("nonexistent") is None


# ── Integration: handler-level injection ───────────────────


class TestDesktopToolsInjection:
    """Testa que os handlers rejeitam injeção."""

    def test_clipboard_set_rejects_injection(self):
        from modules.desktop_tools import DesktopTools
        dt = DesktopTools()
        result = dt.clipboard_set("'; calc.exe; echo '")
        assert "rejeitada" in result.lower() or "erro" in result.lower()
        # Must NOT contain calc.exe in the result as a successful action
        assert "Clipboard definido" not in result

    def test_clipboard_set_accepts_clean_text(self):
        from modules.desktop_tools import DesktopTools
        dt = DesktopTools()
        result = dt.clipboard_set("texto limpo")
        # Either succeeds or fails for other reasons (e.g., no display)
        assert "rejeitada" not in result.lower()

    def test_focus_window_rejects_injection(self):
        from modules.desktop_tools import DesktopTools
        dt = DesktopTools()
        result = dt.focus_window("'; calc.exe; echo '")
        assert "rejeitada" in result.lower()

    def test_focus_window_accepts_clean_name(self):
        from modules.desktop_tools import DesktopTools
        dt = DesktopTools()
        result = dt.focus_window("chrome")
        # Either succeeds (window found) or fails (not found) — both OK
        assert "rejeitada" not in result.lower()

    def test_screenshot_rejects_path_traversal(self):
        from modules.desktop_tools import DesktopTools
        dt = DesktopTools()
        result = dt.screenshot("..\\..\\Windows\\System32\\test.png")
        assert "rejeitada" in result.lower() or "inválido" in result.lower()


class TestNotificationsInjection:
    """Testa que notificações rejeitam injeção."""

    def test_notify_rejects_injection_in_title(self):
        from modules.notifications import NotificationManager
        nm = NotificationManager()
        result = nm.notify('"; Start-Process calc; echo "', "msg")
        assert "rejeitada" in result.lower()

    def test_notify_rejects_injection_in_message(self):
        from modules.notifications import NotificationManager
        nm = NotificationManager()
        result = nm.notify("title", '"; Start-Process calc; echo "')
        assert "rejeitada" in result.lower()

    def test_notify_accepts_clean_text(self):
        from modules.notifications import NotificationManager
        nm = NotificationManager()
        result = nm.notify("Título", "Mensagem limpa")
        # Should succeed or fall back to registration
        assert "rejeitada" not in result.lower()
