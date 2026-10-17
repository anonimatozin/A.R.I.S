"""Desktop Tools - Controle total do desktop do A.R.I.S.

Ferramentas para automação: mouse, teclado, janelas, mídia, clipboard.

Plataforma: os métodos de sistema (janelas, apps, clipboard, área de
trabalho) têm adaptadores por ``sys.platform`` — Windows usa as APIs
nativas, Linux usa xdg/wmctrl/xclip. Nenhum texto do usuário vira
comando livre de shell.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

_IS_LINUX = sys.platform.startswith("linux")
_IS_WINDOWS = sys.platform.startswith("win")

try:
    import pyautogui
    _PYAUTOGUI_AVAILABLE = True
except BaseException:  # noqa: BLE001 - pyautogui chama sys.exit() sem tkinter/display
    _PYAUTOGUI_AVAILABLE = False


# ── Helpers de plataforma (Linux) ───────────────────────────

# Lista FIXA de aplicativos conhecidos no Linux (nome amigável → argv).
# Nada de comando livre: só o que está neste mapa pode ser aberto por nome.
_LINUX_APPS: dict[str, list[str]] = {
    "firefox": ["firefox"],
    "chrome": ["google-chrome"],
    "google chrome": ["google-chrome"],
    "chromium": ["chromium"],
    "navegador": ["firefox"],
    "discord": ["discord"],
    "spotify": ["spotify"],
    "terminal": ["gnome-terminal"],
    "calculadora": ["gnome-calculator"],
    "calculator": ["gnome-calculator"],
    "explorador": ["nautilus"],
    "explorer": ["nautilus"],
    "files": ["nautilus"],
    "editor": ["gnome-text-editor"],
    "notepad": ["gnome-text-editor"],
    "bloco de notas": ["gnome-text-editor"],
}


def _run(argv: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    """Roda um argv fixo (sem shell)."""
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def _linux_desktop_dir() -> Path:
    """Diretório da área de trabalho via xdg-user-dir (fallback ~/Desktop)."""
    if _IS_LINUX and shutil.which("xdg-user-dir"):
        try:
            out = _run(["xdg-user-dir", "DESKTOP"], timeout=5).stdout.strip()
            if out:
                return Path(out)
        except Exception:
            pass
    return Path.home() / "Desktop"


def _validate_app_name(name: str) -> bool:
    """Nome de app livre de caracteres de shell/path traversal."""
    import re

    return bool(re.fullmatch(r"[A-Za-z0-9 ._\-]+", name))


class DesktopTools:
    """Ferramentas de automação do desktop."""

    def __init__(self):
        self._available = _PYAUTOGUI_AVAILABLE
        if self._available:
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.1

    @property
    def available(self) -> bool:
        return self._available

    # ── Mouse ──────────────────────────────────────────────

    def mouse_move(self, x: int, y: int) -> str:
        """Move o mouse para coordenadas."""
        if not self._available:
            return "pyautogui não instalado"
        pyautogui.moveTo(x, y)
        return f"Mouse movido para ({x}, {y})"

    def mouse_click(self, x: int | None = None, y: int | None = None, button: str = "left") -> str:
        """Clica em uma posição."""
        if not self._available:
            return "pyautogui não instalado"
        if x is not None and y is not None:
            pyautogui.click(x, y, button=button)
        else:
            pyautogui.click(button=button)
        return f"Click {button} executado"

    def mouse_double_click(self, x: int | None = None, y: int | None = None) -> str:
        """Duplo clique."""
        if not self._available:
            return "pyautogui não instalado"
        if x is not None and y is not None:
            pyautogui.doubleClick(x, y)
        else:
            pyautogui.doubleClick()
        return "Duplo clique executado"

    def mouse_scroll(self, clicks: int = 3) -> str:
        """Rola o scroll do mouse."""
        if not self._available:
            return "pyautogui não instalado"
        pyautogui.scroll(clicks)
        return f"Scroll: {clicks} cliques"

    def mouse_position(self) -> str:
        """Retorna posição atual do mouse."""
        if not self._available:
            return "pyautogui não instalado"
        pos = pyautogui.position()
        return f"Posição: ({pos.x}, {pos.y})"

    # ── Teclado ────────────────────────────────────────────

    def type_text(self, text: str) -> str:
        """Digita um texto."""
        if not self._available:
            return "pyautogui não instalado"
        pyautogui.typewrite(text, interval=0.02)
        return f"Texto digitado: {text[:50]}..."

    def hotkey(self, *keys: str) -> str:
        """Executa uma combinação de teclas."""
        if not self._available:
            return "pyautogui não instalado"
        pyautogui.hotkey(*keys)
        return f"Hotkey: {'+'.join(keys)}"

    def press_key(self, key: str, presses: int = 1) -> str:
        """Pressiona uma tecla."""
        if not self._available:
            return "pyautogui não instalado"
        pyautogui.press(key, presses=presses)
        return f"Tecla '{key}' pressionada {presses}x"

    # ── Janelas ────────────────────────────────────────────

    def list_windows(self) -> str:
        """Lista janelas abertas (Windows: powershell / Linux: wmctrl)."""
        if _IS_LINUX:
            if not shutil.which("wmctrl"):
                return "Listagem de janelas indisponível no Linux (instale wmctrl)."
            try:
                result = _run(["wmctrl", "-l"])
                return result.stdout if result.stdout.strip() else "Nenhuma janela encontrada"
            except Exception as e:
                return f"Erro: {e}"
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | Select-Object ProcessName, MainWindowTitle | Format-Table -AutoSize"],
                capture_output=True, text=True, timeout=10
            )
            return result.stdout if result.stdout else "Nenhuma janela encontrada"
        except Exception as e:
            return f"Erro: {e}"

    def focus_window(self, process_name: str) -> str:
        """Foca em uma janela pelo nome do processo."""
        from core.security.shell import (
            InputValidationError,
            ShellInjectionError,
            validate_process_name,
        )
        try:
            safe_name = validate_process_name(process_name)
        except (ShellInjectionError, InputValidationError) as e:
            return f"Entrada rejeitada: {e}"

        if _IS_LINUX:
            if not shutil.which("wmctrl"):
                return "Foco de janela indisponível no Linux (instale wmctrl)."
            try:
                result = _run(["wmctrl", "-a", safe_name])
                if result.returncode == 0:
                    return f"Janela '{process_name}' focada"
                return f"Janela '{process_name}' não encontrada"
            except Exception as e:
                return f"Erro ao focar janela: {e}"

        ps_script = (
            f"$p = Get-Process -Name '{safe_name}' -ErrorAction SilentlyContinue; "
            "if ($p) { Add-Type -Name Win -Namespace Native -MemberDefinition "
            "'[DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr hWnd);' ; "
            "[Native.Win]::SetForegroundWindow($p.MainWindowHandle) }"
        )
        try:
            result = subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True, text=True, timeout=10
            )
            found = bool(result.stdout and result.stdout.strip())
            return (f"Janela '{process_name}' focada" if found
                    else f"Janela '{process_name}' não encontrada")
        except Exception as e:
            return f"Erro ao focar janela: {e}"

    def minimize_all(self) -> str:
        """Minimiza todas as janelas (Show Desktop)."""
        if _IS_LINUX:
            # xdotool: atalho do desktop (GNOME/KDE) para Show Desktop.
            if shutil.which("xdotool"):
                try:
                    _run(["xdotool", "key", "--clearmodifiers", "super+d"])
                    return "Todas as janelas minimizadas"
                except Exception as e:
                    return f"Erro ao minimizar janelas: {e}"
            return "Minimizar janelas indisponível no Linux (instale xdotool)."
        if not self._available:
            return "pyautogui não instalado"
        pyautogui.hotkey("win", "d")
        return "Todas as janelas minimizadas"

    # ── Mídia ──────────────────────────────────────────────

    def media_play_pause(self) -> str:
        """Play/Pause da mídia."""
        if not self._available:
            return "pyautogui não instalado"
        pyautogui.press("playpause")
        return "Play/Pause"

    def media_next(self) -> str:
        """Próxima faixa."""
        if not self._available:
            return "pyautogui não instalado"
        pyautogui.press("nexttrack")
        return "Próxima faixa"

    def media_previous(self) -> str:
        """Faixa anterior."""
        if not self._available:
            return "pyautogui não instalado"
        pyautogui.press("prevtrack")
        return "Faixa anterior"

    def volume_up(self, steps: int = 5) -> str:
        """Aumenta o volume."""
        if not self._available:
            return "pyautogui não instalado"
        for _ in range(steps):
            pyautogui.press("volumeup")
        return f"Volume aumentado {steps}x"

    def volume_down(self, steps: int = 5) -> str:
        """Diminui o volume."""
        if not self._available:
            return "pyautogui não instalado"
        for _ in range(steps):
            pyautogui.press("volumedown")
        return f"Volume diminuído {steps}x"

    def volume_mute(self) -> str:
        """Mudo."""
        if not self._available:
            return "pyautogui não instalado"
        pyautogui.press("volumemute")
        return "Volume mutado"

    # ── Clipboard ──────────────────────────────────────────

    def clipboard_get(self) -> str:
        """Retorna o conteúdo do clipboard (Windows / Linux xclip|wl-paste)."""
        if _IS_LINUX:
            try:
                if shutil.which("wl-paste"):
                    result = _run(["wl-paste", "--no-newline"], timeout=5)
                elif shutil.which("xclip"):
                    result = _run(["xclip", "-selection", "clipboard", "-o"], timeout=5)
                else:
                    return "Clipboard indisponível no Linux (instale wl-clipboard ou xclip)."
                return result.stdout.strip() if result.stdout.strip() else "Clipboard vazio"
            except Exception:
                return "Erro ao acessar clipboard"
        try:
            result = subprocess.run(
                ["powershell", "-Command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=5
            )
            return result.stdout.strip() if result.stdout else "Clipboard vazio"
        except Exception:
            return "Erro ao acessar clipboard"

    def clipboard_set(self, text: str) -> str:
        """Define o conteúdo do clipboard."""
        from core.security.shell import (
            ShellInjectionError,
            validate_shell_input,
        )
        try:
            validate_shell_input(text)
        except ShellInjectionError as e:
            return f"Entrada rejeitada: {e}"
        if _IS_LINUX:
            try:
                if shutil.which("wl-copy"):
                    proc = subprocess.run(
                        ["wl-copy"], input=text, capture_output=True, text=True, timeout=5
                    )
                elif shutil.which("xclip"):
                    proc = subprocess.run(
                        ["xclip", "-selection", "clipboard"], input=text,
                        capture_output=True, text=True, timeout=5
                    )
                else:
                    return "Clipboard indisponível no Linux (instale wl-clipboard ou xclip)."
                if proc.returncode == 0:
                    return f"Clipboard definido: {text[:50]}..."
                return "Erro ao definir clipboard"
            except Exception:
                return "Erro ao definir clipboard"
        try:
            subprocess.run(
                ["powershell", "-Command", "Set-Clipboard", "-Value", text],
                capture_output=True, timeout=5
            )
            return f"Clipboard definido: {text[:50]}..."
        except Exception:
            return "Erro ao definir clipboard"

    # ── Sistema ────────────────────────────────────────────

    # Aliases conhecidos (nome amigável → alvo do Windows)
    APP_ALIASES = {
        "chrome": "chrome", "firefox": "firefox", "discord": "discord",
        "spotify": "spotify", "notepad": "notepad", "calculator": "calc",
        "bloco de notas": "notepad", "navegador": "chrome",
        "explorer": "explorer", "windows explorer": "explorer",
        "explorador": "explorer", "painel de controle": "control",
    }

    def open_app(self, app_name: str) -> str:
        """Abre um aplicativo de forma segura (sem shell de comandos).

        Linux: só a lista fixa ``_LINUX_APPS`` (por nome) ou ``xdg-open``
        para um caminho/URL — nenhum texto do usuário vira comando livre.
        Windows: ``os.startfile`` (ShellExecute) com fallback para
        ``subprocess.Popen`` resolvendo o executável no PATH.
        """
        name = app_name.strip().strip('"')
        if not name:
            return "Nome de aplicativo vazio."

        if _IS_LINUX:
            return self._open_app_linux(name)

        name = self.APP_ALIASES.get(name.lower(), name)

        # 1. os.startfile: associação do Windows, sem shell
        try:
            os.startfile(name)
            return f"Abrindo {name}..."
        except OSError:
            pass

        # 2. Resolver executável no PATH (sem shell)
        exe = shutil.which(name)
        if exe:
            try:
                subprocess.Popen([exe])
                return f"Abrindo {exe}..."
            except Exception as e:
                return f"Erro ao abrir {name}: {e}"

        return f"Não foi possível abrir '{name}' (aplicativo não encontrado)."

    def _open_app_linux(self, name: str) -> str:
        """Abre app no Linux: lista fixa ou xdg-open (arquivo/URL)."""
        # 1. Lista fixa de apps (nome amigável → argv)
        argv = _LINUX_APPS.get(name.lower())
        if argv:
            exe = shutil.which(argv[0])
            if exe:
                try:
                    subprocess.Popen([exe, *argv[1:]])
                    return f"Abrindo {name}..."
                except Exception as e:
                    return f"Erro ao abrir {name}: {e}"
            return f"Não foi possível abrir '{name}' (aplicativo não encontrado)."

        # 2. xdg-open: só para caminho existente ou URL (não é comando livre)
        is_url = name.startswith(("http://", "https://"))
        if is_url or os.path.exists(name):
            if shutil.which("xdg-open"):
                try:
                    subprocess.Popen(["xdg-open", name])
                    return f"Abrindo {name}..."
                except Exception as e:
                    return f"Erro ao abrir {name}: {e}"
            return "xdg-open indisponível no Linux."

        return f"Não foi possível abrir '{name}' (aplicativo não encontrado)."

    def close_app(self, process_name: str) -> str:
        """Fecha um aplicativo pelo nome do processo."""
        from core.security.shell import (
            InputValidationError,
            ShellInjectionError,
            validate_process_name,
        )
        try:
            safe_name = validate_process_name(process_name)
        except (ShellInjectionError, InputValidationError) as e:
            return f"Entrada rejeitada: {e}"

        if _IS_LINUX:
            try:
                result = _run(["pkill", "-x", safe_name], timeout=10)
                if result.returncode == 0:
                    return f"{process_name} fechado"
                return f"{process_name} não estava rodando"
            except Exception as e:
                return f"Erro ao fechar {process_name}: {e}"
        try:
            subprocess.run(["taskkill", "/IM", process_name, "/F"], capture_output=True)
            return f"{process_name} fechado"
        except Exception as e:
            return f"Erro ao fechar {process_name}: {e}"

    def create_file(self, filename: str, content: str = "") -> str:
        """Cria um arquivo na área de trabalho (Linux: xdg-user-dir DESKTOP).

        Sem abrir editor: só grava o arquivo e devolve o caminho.
        """
        from core.security.shell import (
            InputValidationError,
            validate_filename,
        )
        try:
            safe_name = validate_filename(filename)
        except InputValidationError as e:
            return f"Entrada rejeitada: {e}"

        if _IS_LINUX:
            desktop = _linux_desktop_dir()
        else:
            desktop = Path(os.path.expandvars("%USERPROFILE%")) / "Desktop"
        try:
            desktop.mkdir(parents=True, exist_ok=True)
            path = desktop / safe_name
            path.write_text(content or "", encoding="utf-8")
            return f"Arquivo criado: {path}"
        except Exception as e:
            return f"Erro ao criar arquivo: {e}"

    def screenshot(self, filename: str = "screenshot.png") -> str:
        """Captura uma screenshot."""
        from core.security.shell import (
            InputValidationError,
            validate_filename,
        )
        try:
            safe_name = validate_filename(filename)
        except InputValidationError as e:
            return f"Entrada rejeitada: {e}"
        if not self._available:
            return "pyautogui não instalado"
        path = os.path.join(os.getcwd(), safe_name)
        pyautogui.screenshot(path)
        return f"Screenshot salva: {path}"

    def get_screen_size(self) -> str:
        """Retorna o tamanho da tela."""
        if not self._available:
            return "pyautogui não instalado"
        size = pyautogui.size()
        return f"Tela: {size.width}x{size.height}"

    def execute_action(self, action: str, params: dict) -> str:
        """Executa uma ação genérica via JSON.

        Args:
            action: Nome da ação.
            params: Parâmetros da ação.

        Returns:
            Resultado da execução.
        """
        actions = {
            "mouse_move": lambda: self.mouse_move(params.get("x", 0), params.get("y", 0)),
            "mouse_click": lambda: self.mouse_click(params.get("x"), params.get("y"), params.get("button", "left")),
            "type_text": lambda: self.type_text(params.get("text", "")),
            "hotkey": lambda: self.hotkey(*params.get("keys", [])),
            "press_key": lambda: self.press_key(params.get("key", "")),
            "volume_up": lambda: self.volume_up(params.get("steps", 5)),
            "volume_down": lambda: self.volume_down(params.get("steps", 5)),
            "volume_mute": lambda: self.volume_mute(),
            "media_play_pause": lambda: self.media_play_pause(),
            "media_next": lambda: self.media_next(),
            "media_previous": lambda: self.media_previous(),
            "open_app": lambda: self.open_app(params.get("app", "")),
            "close_app": lambda: self.close_app(params.get("process", "")),
            "create_file": lambda: self.create_file(
                params.get("filename", "novo_arquivo.txt"),
                params.get("content", ""),
            ),
            "screenshot": lambda: self.screenshot(params.get("filename", "screenshot.png")),
            "minimize_all": lambda: self.minimize_all(),
            "clipboard_get": lambda: self.clipboard_get(),
            "clipboard_set": lambda: self.clipboard_set(params.get("text", "")),
        }

        func = actions.get(action)
        if func:
            return func()
        return f"Ação desconhecida: {action}"
