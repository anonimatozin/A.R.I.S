"""Navegador controlado (Playwright/Chromium) com perfil dedicado e snapshots numerados.

O Playwright é importado de forma preguiçosa: sem ele instalado, só as ferramentas
``browser_*`` falham com instrução de instalação; busca e leitura seguem funcionando.
O perfil fica em ``data_dir/browser_profile`` (nunca no perfil real do usuário) e o
navegador é fechado por ociosidade para não segurar RAM.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ...contract.types import Risk, ToolContext, ToolResult, ToolSpec
from ...contract.utils import redact_secrets, truncate_text
from ..registry import function_tool
from .output import wrap_result
from .settings import WebSettings, web_settings
from .ssrf import SsrfBlockedError, check_url

log = logging.getLogger("aris.agent.tools.web.browser")

_REAPER_INTERVAL_S = 10.0

# Seletores de elementos interativos usados na enumeração (mesma ordem do DOM).
INTERACTIVE_SEL = (
    "a[href], button, input:not([type='hidden']), select, textarea, "
    "[role='button'], [role='link'], [role='menuitem'], [role='menuitemcheckbox'], "
    "[role='menuitemradio'], [role='tab'], [role='checkbox'], [role='radio'], "
    "[role='option'], [role='switch'], [role='textbox'], [role='searchbox'], "
    "[role='combobox'], [role='slider'], [role='spinbutton'], "
    "[contenteditable=''], [contenteditable='true'], summary"
)

_ENUM_JS = """
(sel) => {
  const out = [];
  const clean = (s) => String(s || '').replace(/\\s+/g, ' ').trim().slice(0, 80);
  const roleOf = (el) => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit.split(/\\s+/)[0];
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'button') return 'button';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'summary') return 'button';
    if (tag === 'input') {
      const t = (el.getAttribute('type') || 'text').toLowerCase();
      if (['button', 'submit', 'reset', 'image'].includes(t)) return 'button';
      if (t === 'checkbox') return 'checkbox';
      if (t === 'radio') return 'radio';
      if (t === 'range') return 'slider';
      if (t === 'number') return 'spinbutton';
      if (t === 'search') return 'searchbox';
      return 'textbox';
    }
    if (el.isContentEditable) return 'textbox';
    return tag;
  };
  const nameOf = (el) => {
    let n = clean(el.getAttribute('aria-label'));
    if (n) return n;
    const tag = el.tagName.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') {
      n = clean(el.getAttribute('placeholder'));
      if (n) return n;
      try {
        if (el.labels && el.labels.length) n = clean(el.labels[0].textContent);
      } catch (e) {}
      if (n) return n;
      const t = (el.getAttribute('type') || '').toLowerCase();
      if (tag === 'input' && ['button', 'submit', 'reset'].includes(t) && el.value) {
        return clean(el.value);
      }
      return clean(el.getAttribute('name') || el.getAttribute('id'));
    }
    n = clean(el.innerText || el.textContent);
    if (n) return n;
    return clean(el.getAttribute('title') || el.getAttribute('alt'));
  };
  let nodes = [];
  try { nodes = Array.from(document.querySelectorAll(sel)); } catch (e) { return out; }
  nodes.forEach((el, i) => {
    try {
      if (el.getAttribute('aria-hidden') === 'true') return;
      const visible = !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
      if (!visible) return;
      out.push({ idx: i, role: roleOf(el), name: nameOf(el) });
    } catch (e) {}
  });
  return out;
}
"""

_ROLE_PT = {
    "link": "link",
    "button": "botão",
    "textbox": "campo",
    "searchbox": "campo de busca",
    "combobox": "caixa de seleção",
    "checkbox": "caixa de marcação",
    "radio": "opção",
    "tab": "aba",
    "menuitem": "item de menu",
    "menuitemcheckbox": "item de menu",
    "menuitemradio": "item de menu",
    "option": "opção",
    "switch": "interruptor",
    "slider": "controle deslizante",
    "spinbutton": "campo numérico",
    "img": "imagem",
    "summary": "resumo",
}


class BrowserError(Exception):
    """Falha de navegação ou de snapshot (vira ToolResult(ok=False))."""


@dataclass
class Element:
    """Elemento interativo numerado de um snapshot."""

    idx: int  # índice em document.querySelectorAll(INTERACTIVE_SEL)
    role: str
    name: str

    def label(self) -> str:
        role = _ROLE_PT.get(self.role, self.role)
        return f'{role} "{self.name}"' if self.name else role


class BrowserSession:
    """Sessão Playwright com perfil dedicado e snapshots numerados anti-SSRF."""

    def __init__(self, settings: WebSettings, data_dir: Path, workspace_dir: Path) -> None:
        self.settings = settings
        self.profile_dir = Path(data_dir) / "browser_profile"
        self.workspace_dir = Path(workspace_dir)
        self._pw = None
        self._context = None
        self._page = None
        self.elements: list[Element] | None = None
        self.fingerprint: tuple | None = None
        self.last_used = time.monotonic()
        self._screenshot_n = 0
        self._dns_cache: dict = {}

    # ------------------------------------------------------------------ estado

    @property
    def active(self) -> bool:
        """True se há um navegador em execução."""
        return self._page is not None

    def touch(self) -> None:
        """Marca atividade recente (adiia o fechamento por ociosidade)."""
        self.last_used = time.monotonic()

    def _invalidate(self) -> None:
        self.elements = None
        self.fingerprint = None

    def _ensure_started(self) -> None:
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserError(
                "Playwright não está instalado; instale com `pip install playwright` "
                "e baixe o Chromium com `playwright install chromium` "
                "(veja aris_agent/tools/web/README.md)"
            ) from exc
        try:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self._pw = sync_playwright().start()
            self._context = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=bool(self.settings.browser_headless),
            )
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
            self._page.set_default_timeout(15000)
            self._context.route("**/*", self._route)
        except Exception as exc:  # noqa: BLE001 - erro do navegador vira mensagem útil
            self.close()
            raise BrowserError(f"não consegui iniciar o Chromium: {redact_secrets(str(exc))}") from exc
        log.info("navegador iniciado (perfil %s)", self.profile_dir)

    def close(self) -> bool:
        """Fecha navegador, contexto e runtime; devolve True se havia algo aberto."""
        was_open = self._page is not None or self._context is not None or self._pw is not None
        if self._context is not None:
            try:
                self._context.close()
            except Exception:  # noqa: BLE001 - fechamento é melhor esforço
                log.debug("erro ao fechar o contexto do navegador", exc_info=True)
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:  # noqa: BLE001
                log.debug("erro ao parar o Playwright", exc_info=True)
        self._context = None
        self._pw = None
        self._page = None
        self._dns_cache.clear()
        self._invalidate()
        if was_open:
            log.info("navegador fechado")
        return was_open

    # ------------------------------------------------------------- segurança

    def _route(self, route, request) -> None:
        """Valida cada requisição da página; bloqueia destino proibido."""
        url = getattr(request, "url", "") or ""
        scheme = url.split(":", 1)[0].lower() if ":" in url else ""
        if scheme in ("data", "blob", "about"):
            self._continue(route)
            return
        try:
            check_url(url, self.settings, self._dns_cache)
        except SsrfBlockedError as exc:
            log.debug("requisição do navegador bloqueada: %s", redact_secrets(str(exc)))
            self._abort(route)
            return
        self._continue(route)

    @staticmethod
    def _continue(route) -> None:
        try:
            route.continue_()
        except Exception:  # noqa: BLE001 - página/contexto pode ter fechado
            log.debug("route.continue_ falhou", exc_info=True)

    @staticmethod
    def _abort(route) -> None:
        try:
            route.abort()
        except Exception:  # noqa: BLE001
            log.debug("route.abort falhou", exc_info=True)

    # -------------------------------------------------------------- ações

    def open_url(self, url: str) -> tuple[str, str]:
        """Abre ``url`` (validada anti-SSRF, inclusive após redirect). Devolve (URL final, título)."""
        check_url(url, self.settings, self._dns_cache)  # antes de ligar o navegador
        self._ensure_started()
        try:
            self._page.goto(
                url, wait_until="domcontentloaded", timeout=int(self.settings.timeout_s * 1000)
            )
        except Exception as exc:  # noqa: BLE001
            raise BrowserError(f"falha ao abrir {redact_secrets(url)}: {exc}") from exc
        final = self._page.url or url
        if final.startswith(("http://", "https://")):
            try:
                check_url(final, self.settings, self._dns_cache)
            except SsrfBlockedError:
                self._safe_blank()
                raise
        self._invalidate()
        self.touch()
        title = self._title()
        return final, title

    def _safe_blank(self) -> None:
        try:
            self._page.goto("about:blank")
        except Exception:  # noqa: BLE001
            log.debug("não consegui ir para about:blank", exc_info=True)
        self._invalidate()

    def _title(self) -> str:
        try:
            return str(self._page.title() or "").strip()
        except Exception:  # noqa: BLE001
            return ""

    def _require_page(self):
        if self._page is None:
            raise BrowserError("nenhum navegador aberto; chame browser_open")
        return self._page

    def _enumerate(self) -> list[Element]:
        page = self._require_page()
        try:
            raw = page.evaluate(_ENUM_JS, INTERACTIVE_SEL)
        except Exception as exc:  # noqa: BLE001
            raise BrowserError(f"falha ao ler a página: {exc}") from exc
        out: list[Element] = []
        for item in raw or []:
            try:
                out.append(
                    Element(idx=int(item.get("idx", -1)), role=str(item.get("role") or ""),
                            name=str(item.get("name") or ""))
                )
            except (TypeError, ValueError):
                continue
        return out

    def snapshot(self) -> tuple[str, str]:
        """Texto visível + elementos numerados; guarda a assinatura anti-stale."""
        page = self._require_page()
        try:
            visible = str(page.inner_text("body", timeout=5000) or "")
        except Exception:  # noqa: BLE001 - página sem body ou ainda carregando
            visible = ""
        elements = self._enumerate()
        url = str(page.url or "")
        self.elements = elements
        self.fingerprint = (url, tuple((e.idx, e.role, e.name) for e in elements))
        self.touch()
        lines = [f"URL: {url}", f"Título: {self._title()}", "", "Texto visível:"]
        lines.append(truncate_text(visible, 4000))
        lines += ["", f"Elementos interativos ({len(elements)}):"]
        if not elements:
            lines.append("(nenhum elemento interativo visível)")
        for i, element in enumerate(elements, start=1):
            lines.append(f"[{i}] {element.label()}")
        return "\n".join(lines), url

    def _resolve(self, number: int) -> Element:
        page = self._require_page()
        if not isinstance(number, int) or isinstance(number, bool):
            raise BrowserError(f"número de elemento inválido: {number!r}")
        if self.elements is None or self.fingerprint is None:
            raise BrowserError("nenhum snapshot ativo; chame browser_snapshot")
        if not 1 <= number <= len(self.elements):
            raise BrowserError(
                f"elemento [{number}] inexistente no snapshot (1..{len(self.elements)}); "
                "chame browser_snapshot"
            )
        current = self._enumerate()
        fingerprint = (str(page.url or ""), tuple((e.idx, e.role, e.name) for e in current))
        if fingerprint != self.fingerprint:
            self._invalidate()
            raise BrowserError("snapshot desatualizado, chame browser_snapshot")
        return self.elements[number - 1]

    def _locator(self, element: Element):
        return self._require_page().locator(INTERACTIVE_SEL).nth(element.idx)

    def _after_action(self, *, allow_name_change: bool) -> None:
        """Revalida a assinatura após uma ação; invalida se a página mudou."""
        if self.fingerprint is None or self.elements is None or self._page is None:
            return
        try:
            self._page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:  # noqa: BLE001 - sem navegação nova é normal
            pass
        current = self._enumerate()
        if allow_name_change and [e.idx for e in current] == [e.idx for e in self.elements]:
            self.elements = current
            self.fingerprint = (
                str(self._page.url or ""),
                tuple((e.idx, e.role, e.name) for e in current),
            )
            return
        fingerprint = (str(self._page.url or ""), tuple((e.idx, e.role, e.name) for e in current))
        if fingerprint != self.fingerprint:
            self._invalidate()

    def click(self, number: int) -> Element:
        """Clica no elemento ``number`` do último snapshot."""
        element = self._resolve(number)
        try:
            self._locator(element).click(timeout=8000)
        except Exception as exc:  # noqa: BLE001
            raise BrowserError(f"falha ao clicar em [{number}]: {exc}") from exc
        self._after_action(allow_name_change=False)
        self.touch()
        return element

    def type_text(self, number: int, text: str, clear: bool = True) -> Element:
        """Preenche o campo ``number`` do último snapshot."""
        element = self._resolve(number)
        try:
            if clear:
                self._locator(element).fill(text)
            else:
                self._locator(element).click(timeout=8000)
                self._require_page().keyboard.insert_text(text)
        except Exception as exc:  # noqa: BLE001
            raise BrowserError(f"falha ao preencher [{number}]: {exc}") from exc
        self._after_action(allow_name_change=True)
        self.touch()
        return element

    def press(self, key: str, number: int | None = None) -> None:
        """Pressiona ``key`` (Enter, Tab...); opcionalmente em um elemento do snapshot."""
        try:
            if number is not None:
                element = self._resolve(number)
                self._locator(element).press(key, timeout=8000)
            else:
                self._require_page().keyboard.press(key)
        except BrowserError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BrowserError(f"falha ao pressionar {key!r}: {exc}") from exc
        self._after_action(allow_name_change=False)
        self.touch()

    def screenshot(self, full_page: bool = False) -> Path:
        """Salva um PNG em workspace/browser e devolve o caminho."""
        page = self._require_page()
        folder = Path(self.workspace_dir) / "browser"
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BrowserError(f"não consegui criar {folder}: {exc}") from exc
        self._screenshot_n += 1
        path = folder / f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}_{self._screenshot_n:03d}.png"
        try:
            page.screenshot(path=str(path), full_page=bool(full_page))
        except Exception as exc:  # noqa: BLE001
            raise BrowserError(f"falha ao tirar screenshot: {exc}") from exc
        self.touch()
        return path


# ----------------------------------------------------------------- sessão única

_LOCK = threading.Lock()
_SESSION: BrowserSession | None = None
_REAPER_STARTED = False
_STOP = threading.Event()


def _reaper_loop() -> None:
    """Thread daemon: fecha o navegador que ficou ocioso (economia de RAM)."""
    while not _STOP.wait(_REAPER_INTERVAL_S):
        session = _SESSION
        if session is None or not session.active:
            continue
        idle = time.monotonic() - session.last_used
        if idle >= session.settings.browser_idle_s:
            log.info("navegador ocioso por %.0f s; fechando para liberar memória", idle)
            session.touch()
            session.close()


def _session_for(ctx: ToolContext) -> BrowserSession:
    global _SESSION, _REAPER_STARTED
    with _LOCK:
        if _SESSION is None:
            _SESSION = BrowserSession(
                web_settings(ctx.config), ctx.config.data_dir, ctx.config.workspace_dir
            )
        if not _REAPER_STARTED:
            _REAPER_STARTED = True
            threading.Thread(target=_reaper_loop, name="aris-browser-reaper", daemon=True).start()
        return _SESSION


def _close_session() -> bool:
    global _SESSION
    with _LOCK:
        session = _SESSION
        _SESSION = None
    if session is None:
        return False
    return session.close()


# ------------------------------------------------------------------- ferramentas

_OPEN_SPEC = ToolSpec(
    name="browser_open",
    description="Abre uma URL no navegador controlado (Chromium com perfil dedicado). Bloqueia rede local/privada.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL http(s) a abrir no navegador"},
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    risk=Risk.EXEC,
    untrusted_output=True,
    timeout_s=60.0,
    tags=("web", "browser"),
    url_args=("url",),
)

_SNAPSHOT_SPEC = ToolSpec(
    name="browser_snapshot",
    description=(
        "Devolve o texto visível da página e a lista numerada de elementos interativos "
        "([1] botão \"Entrar\"). Use os números em browser_click/type/press."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    risk=Risk.READ,
    untrusted_output=True,
    timeout_s=30.0,
    tags=("web", "browser"),
)

_CLICK_SPEC = ToolSpec(
    name="browser_click",
    description="Clica no elemento identificado pelo número do último browser_snapshot.",
    parameters={
        "type": "object",
        "properties": {
            "element": {"type": "integer", "description": "Número do elemento no último snapshot"},
        },
        "required": ["element"],
        "additionalProperties": False,
    },
    risk=Risk.EXEC,
    untrusted_output=True,
    timeout_s=30.0,
    tags=("web", "browser"),
)

_TYPE_SPEC = ToolSpec(
    name="browser_type",
    description="Preenche o campo identificado pelo número do último browser_snapshot.",
    parameters={
        "type": "object",
        "properties": {
            "element": {"type": "integer", "description": "Número do campo no último snapshot"},
            "text": {"type": "string", "description": "Texto a digitar no campo"},
            "clear": {
                "type": "boolean",
                "description": "Limpar o campo antes de digitar (padrão true)",
            },
        },
        "required": ["element", "text"],
        "additionalProperties": False,
    },
    risk=Risk.EXEC,
    untrusted_output=True,
    timeout_s=30.0,
    tags=("web", "browser"),
)

_PRESS_SPEC = ToolSpec(
    name="browser_press",
    description="Pressiona uma tecla (Enter, Tab, Escape...), opcionalmente em um elemento do snapshot.",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Nome da tecla, ex.: Enter, Tab, Escape"},
            "element": {
                "type": "integer",
                "description": "Número do elemento a focar antes (opcional)",
            },
        },
        "required": ["key"],
        "additionalProperties": False,
    },
    risk=Risk.EXEC,
    untrusted_output=True,
    timeout_s=30.0,
    tags=("web", "browser"),
)

_SCREENSHOT_SPEC = ToolSpec(
    name="browser_screenshot",
    description="Salva um PNG da página em workspace/browser e devolve o caminho.",
    parameters={
        "type": "object",
        "properties": {
            "full_page": {
                "type": "boolean",
                "description": "Capturar a página inteira (padrão false = só a janela)",
            },
        },
        "additionalProperties": False,
    },
    risk=Risk.READ,
    untrusted_output=True,
    timeout_s=30.0,
    tags=("web", "browser"),
)

_CLOSE_SPEC = ToolSpec(
    name="browser_close",
    description="Fecha o navegador controlado e libera a memória.",
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    risk=Risk.EXEC,
    untrusted_output=True,
    timeout_s=30.0,
    tags=("web", "browser"),
)


def _err(message: str) -> ToolResult:
    return ToolResult(ok=False, error=redact_secrets(str(message)))


@function_tool(_OPEN_SPEC)
def browser_open(args: dict, ctx: ToolContext) -> ToolResult:
    """Abre a URL no navegador controlado."""
    url = str(args.get("url") or "").strip()
    if not url:
        return _err("parâmetro 'url' é obrigatório")
    session = _session_for(ctx)
    session.touch()
    try:
        final, title = session.open_url(url)
    except SsrfBlockedError as exc:
        return _err(f"URL recusada pela política de rede: {exc}")
    except BrowserError as exc:
        return _err(exc)
    content = f"URL final: {final}\nTítulo: {title or '(sem título)'}\nNavegador aberto."
    return ToolResult(
        ok=True,
        content=wrap_result(content, "navegador", ctx.config, 2000),
        data={"url": final, "title": title},
    )


@function_tool(_SNAPSHOT_SPEC)
def browser_snapshot(args: dict, ctx: ToolContext) -> ToolResult:
    """Devolve texto visível + elementos interativos numerados."""
    session = _session_for(ctx)
    session.touch()
    try:
        text, url = session.snapshot()
    except BrowserError as exc:
        return _err(exc)
    return ToolResult(
        ok=True,
        content=wrap_result(text, "navegador", ctx.config, 8000),
        data={"url": url, "elements": len(session.elements or [])},
    )


@function_tool(_CLICK_SPEC)
def browser_click(args: dict, ctx: ToolContext) -> ToolResult:
    """Clica no elemento numerado do último snapshot."""
    try:
        number = int(args.get("element"))
    except (TypeError, ValueError):
        return _err("parâmetro 'element' deve ser um número inteiro")
    session = _session_for(ctx)
    session.touch()
    try:
        element = session.click(number)
    except BrowserError as exc:
        return _err(exc)
    content = f"Clicado em [{number}]: {element.label()}"
    return ToolResult(
        ok=True,
        content=wrap_result(content, "navegador", ctx.config, 1000),
        data={"element": number, "role": element.role, "name": element.name},
    )


@function_tool(_TYPE_SPEC)
def browser_type(args: dict, ctx: ToolContext) -> ToolResult:
    """Preenche o campo numerado do último snapshot."""
    try:
        number = int(args.get("element"))
    except (TypeError, ValueError):
        return _err("parâmetro 'element' deve ser um número inteiro")
    text = str(args.get("text") if args.get("text") is not None else "")
    clear = bool(args.get("clear", True))
    session = _session_for(ctx)
    session.touch()
    try:
        element = session.type_text(number, text, clear=clear)
    except BrowserError as exc:
        return _err(exc)
    content = f"[{number}] preenchido ({len(text)} caracteres): {element.label()}"
    return ToolResult(
        ok=True,
        content=wrap_result(content, "navegador", ctx.config, 1000),
        data={"element": number, "chars": len(text)},
    )


@function_tool(_PRESS_SPEC)
def browser_press(args: dict, ctx: ToolContext) -> ToolResult:
    """Pressiona uma tecla no navegador."""
    key = str(args.get("key") or "").strip()
    if not key:
        return _err("parâmetro 'key' é obrigatório")
    number: int | None = None
    if args.get("element") is not None:
        try:
            number = int(args.get("element"))
        except (TypeError, ValueError):
            return _err("parâmetro 'element' deve ser um número inteiro")
    session = _session_for(ctx)
    session.touch()
    try:
        session.press(key, number)
    except BrowserError as exc:
        return _err(exc)
    target = f" em [{number}]" if number is not None else ""
    content = f"Tecla {key} pressionada{target}."
    return ToolResult(
        ok=True,
        content=wrap_result(content, "navegador", ctx.config, 1000),
        data={"key": key, "element": number},
    )


@function_tool(_SCREENSHOT_SPEC)
def browser_screenshot(args: dict, ctx: ToolContext) -> ToolResult:
    """Salva um PNG da página e devolve o caminho."""
    full_page = bool(args.get("full_page", False))
    session = _session_for(ctx)
    session.touch()
    try:
        path = session.screenshot(full_page=full_page)
    except BrowserError as exc:
        return _err(exc)
    return ToolResult(
        ok=True,
        content=wrap_result(f"Screenshot salvo em: {path}", "navegador", ctx.config, 1000),
        data={"path": str(path)},
        artifacts=[str(path)],
    )


@function_tool(_CLOSE_SPEC)
def browser_close(args: dict, ctx: ToolContext) -> ToolResult:
    """Fecha o navegador controlado."""
    closed = _close_session()
    message = "Navegador fechado." if closed else "Nenhum navegador aberto."
    return ToolResult(
        ok=True,
        content=wrap_result(message, "navegador", ctx.config, 500),
        data={"closed": closed},
    )
