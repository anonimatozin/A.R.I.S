"""Desktop Tools - Controle total do desktop do A.R.I.S.

Ferramentas para automação: mouse, teclado, janelas, mídia, clipboard.
"""

import os
import shutil
import subprocess

try:
    import pyautogui
    _PYAUTOGUI_AVAILABLE = True
except ImportError:
    _PYAUTOGUI_AVAILABLE = False


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
        """Lista janelas abertas."""
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
            validate_process_name,
            ShellInjectionError,
            InputValidationError,
        )
        try:
            safe_name = validate_process_name(process_name)
        except (ShellInjectionError, InputValidationError) as e:
            return f"Entrada rejeitada: {e}"

        ps_script = (
            "$p = Get-Process -Name '{}' -ErrorAction SilentlyContinue; "
            "if ($p) {{ Add-Type -Name Win -Namespace Native -MemberDefinition "
            "'[DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr hWnd);' ; "
            "[Native.Win]::SetForegroundWindow($p.MainWindowHandle) }}"
        ).format(safe_name)
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
        """Retorna o conteúdo do clipboard."""
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
            validate_shell_input,
            ShellInjectionError,
        )
        try:
            validate_shell_input(text)
        except ShellInjectionError as e:
            return f"Entrada rejeitada: {e}"
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
        """Abre um aplicativo de forma segura (sem shell).

        Usa ``os.startfile`` (ShellExecute, sem shell de comandos) com
        fallback para ``subprocess.Popen`` apontando para um executável
        resolvido via PATH. Nenhum texto do usuário chega a um shell,
        eliminando o vetor de injeção.
        """
        name = app_name.strip().strip('"')
        if not name:
            return "Nome de aplicativo vazio."

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

    def close_app(self, process_name: str) -> str:
        """Fecha um aplicativo pelo nome do processo."""
        try:
            subprocess.run(["taskkill", "/IM", process_name, "/F"], capture_output=True)
            return f"{process_name} fechado"
        except Exception as e:
            return f"Erro ao fechar {process_name}: {e}"

    def screenshot(self, filename: str = "screenshot.png") -> str:
        """Captura uma screenshot."""
        from core.security.shell import (
            validate_filename,
            InputValidationError,
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
            "screenshot": lambda: self.screenshot(params.get("filename", "screenshot.png")),
            "minimize_all": lambda: self.minimize_all(),
            "clipboard_get": lambda: self.clipboard_get(),
            "clipboard_set": lambda: self.clipboard_set(params.get("text", "")),
        }

        func = actions.get(action)
        if func:
            return func()
        return f"Ação desconhecida: {action}"
