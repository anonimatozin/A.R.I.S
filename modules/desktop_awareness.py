"""Desktop Awareness - Captura de Tela + OCR do A.R.I.S.

Monitora a tela em tempo real e extrai informações via OCR.
Inspirado em vierisid/aris e isair/aris.
"""

import threading
import time
from datetime import datetime
from pathlib import Path

try:
    import pyautogui
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pytesseract
    _TESSERACT = True
except ImportError:
    _TESSERACT = False

try:
    from PIL import Image
    _PIL = True
except ImportError:
    _PIL = False


class DesktopAwareness:
    """Monitor de tela em tempo real."""

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir
        self._screenshot_dir = data_dir / "screenshots" if data_dir else None
        self._running = False
        self._thread: threading.Thread | None = None
        self._interval = 30  # segundos
        self._last_text = ""
        self._history: list[dict] = []
        self._callbacks: list = []

        if self._screenshot_dir:
            self._screenshot_dir.mkdir(parents=True, exist_ok=True)

    @property
    def available(self) -> bool:
        return _PYAUTOGUI and _PIL

    @property
    def ocr_available(self) -> bool:
        return _TESSERACT and _PIL

    def capture_screenshot(self, filename: str | None = None) -> str | None:
        """Captura uma screenshot.

        Returns:
            Caminho da screenshot ou None.
        """
        if not _PYAUTOGUI:
            return None

        if not filename:
            filename = f"screen_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"

        if self._screenshot_dir:
            filepath = self._screenshot_dir / filename
        else:
            filepath = Path(filename)

        try:
            screenshot = pyautogui.screenshot()
            screenshot.save(str(filepath))
            return str(filepath)
        except Exception:
            return None

    def extract_text_from_screen(self) -> str:
        """Extrai texto da tela via OCR."""
        if not self.ocr_available:
            return "OCR não disponível (instale pytesseract e Tesseract)"

        try:
            screenshot = pyautogui.screenshot()
            text = pytesseract.image_to_string(screenshot, lang="eng+por")
            self._last_text = text.strip()
            return self._last_text
        except Exception as e:
            return f"Erro OCR: {e}"

    def extract_text_from_image(self, image_path: str) -> str:
        """Extrai texto de uma imagem específica."""
        if not self.ocr_available:
            return "OCR não disponível"

        try:
            img = Image.open(image_path)
            text = pytesseract.image_to_string(img, lang="eng+por")
            return text.strip()
        except Exception as e:
            return f"Erro OCR: {e}"

    def get_screen_text(self, use_cache: bool = True) -> str:
        """Retorna o texto da tela (com cache)."""
        if use_cache and self._last_text:
            return self._last_text
        return self.extract_text_from_screen()

    def search_on_screen(self, query: str) -> dict:
        """Busca um texto específico na tela.

        Returns:
            dict com found, text, position.
        """
        text = self.extract_text_from_screen()
        query_lower = query.lower()
        text_lower = text.lower()

        if query_lower in text_lower:
            # Encontrar posição aproximada
            idx = text_lower.index(query_lower)
            context = text[max(0, idx-50):idx+len(query)+50]
            return {
                "found": True,
                "text": text,
                "query": query,
                "context": context,
                "position": idx,
            }
        return {"found": False, "text": text, "query": query}

    def monitor_screen(self, interval: int = 30, callback=None) -> None:
        """Inicia monitoramento contínuo da tela.

        Args:
            interval: Intervalo em segundos.
            callback: Função chamada quando o texto muda.
        """
        self._interval = interval
        self._running = True
        if callback:
            self._callbacks.append(callback)

        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def _monitor_loop(self) -> None:
        """Loop de monitoramento."""
        last_text = ""
        while self._running:
            try:
                current_text = self.extract_text_from_screen()

                if current_text != last_text:
                    # Texto mudou
                    entry = {
                        "timestamp": datetime.now().isoformat(),
                        "text_preview": current_text[:200],
                        "text_length": len(current_text),
                    }
                    self._history.append(entry)

                    # Limitar histórico
                    if len(self._history) > 100:
                        self._history = self._history[-100:]

                    # Chamar callbacks
                    for callback in self._callbacks:
                        try:
                            callback(current_text, last_text)
                        except Exception:
                            pass

                    last_text = current_text
                    self._last_text = current_text

            except Exception:
                pass

            time.sleep(self._interval)

    def stop_monitoring(self) -> None:
        """Para o monitoramento."""
        self._running = False

    def get_active_window_info(self) -> dict:
        """Retorna informações da janela ativa."""
        try:
            import ctypes
            user32 = ctypes.windll.user32

            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)

            # Obter processo
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            import psutil
            try:
                process = psutil.Process(pid.value)
                process_name = process.name()
            except Exception:
                process_name = "unknown"

            return {
                "title": buf.value,
                "process": process_name,
                "pid": pid.value,
                "hwnd": hwnd,
            }
        except Exception:
            return {"title": "", "process": "", "pid": 0, "hwnd": 0}

    def find_text_on_screen(self, text: str) -> dict:
        """Tenta encontrar e clicar em um texto na tela.

        Returns:
            dict com success, position, message.
        """
        if not _PYAUTOGUI or not self.ocr_available:
            return {"success": False, "message": "Requisitos não instalados"}

        try:
            screenshot = pyautogui.screenshot()
            data = pytesseract.image_to_data(screenshot, lang="eng+por", output_type=pytesseract.Output.DICT)

            for i, word in enumerate(data["text"]):
                if text.lower() in word.lower():
                    x = data["left"][i] + data["width"][i] // 2
                    y = data["top"][i] + data["height"][i] // 2
                    return {
                        "success": True,
                        "position": (x, y),
                        "text": word,
                        "confidence": data["conf"][i],
                    }

            return {"success": False, "message": f"Texto '{text}' não encontrado na tela"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def get_history(self, limit: int = 10) -> list[dict]:
        """Retorna histórico de capturas."""
        return self._history[-limit:]

    def format_status(self) -> str:
        """Formata status do monitoramento."""
        lines = [
            "🖥️ Desktop Awareness",
            f"   Monitoramento: {'Ativo' if self._running else 'Inativo'}",
            f"   OCR: {'Disponível' if self.ocr_available else 'Não disponível'}",
            f"   Intervalo: {self._interval}s",
            f"   Capturas: {len(self._history)}",
        ]
        if self._last_text:
            preview = self._last_text[:100].replace("\n", " ")
            lines.append(f"   Último texto: {preview}...")
        return "\n".join(lines)
