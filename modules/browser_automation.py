"""Browser Automation - Automação de Navegador do A.R.I.S.

Usa Playwright para automação web.
Inspirado em OpenClaw e isair/aris.
"""

import asyncio
from datetime import datetime
from pathlib import Path

try:
    from playwright.async_api import async_playwright
    _PLAYWRIGHT = True
except ImportError:
    _PLAYWRIGHT = False


class BrowserAutomation:
    """Automação de navegador via Playwright."""

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None

    @property
    def available(self) -> bool:
        return _PLAYWRIGHT

    async def start(self, headless: bool = True) -> str:
        """Inicia o navegador."""
        if not _PLAYWRIGHT:
            return "Playwright não instalado. Execute: pip install playwright && playwright install chromium"

        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=headless)
            self._context = await self._browser.new_context()
            self._page = await self._context.new_page()
            # Proteção SSRF: validar cada hop de redirect via route handler
            await self._page.route("**/*", self._validate_redirect_hop)
            return "Navegador iniciado"
        except Exception as e:
            return f"Erro ao iniciar navegador: {e}"

    async def stop(self) -> str:
        """Para o navegador."""
        try:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
            self._browser = None
            self._context = None
            self._page = None
            return "Navegador fechado"
        except Exception:
            return "Navegador já fechado"

    async def navigate(self, url: str) -> str:
        """Navega para uma URL."""
        if not self._page:
            return "Navegador não iniciado"
        from core.security.shell import validate_url, InputValidationError
        try:
            validate_url(url)
        except InputValidationError as e:
            return f"URL rejeitada: {e}"
        try:
            await self._page.goto(url, wait_until="domcontentloaded")
            title = await self._page.title()
            return f"Navegado para: {title}"
        except Exception as e:
            return f"Erro ao navegar: {e}"

    def _validate_redirect_hop(self, route) -> None:
        """Route handler: valida URL apenas em requests de navegação."""
        from core.security.shell import validate_url, InputValidationError
        # Só validar requests de navegação (não assets, scripts, etc.)
        if not route.request.is_navigation_request():
            route.continue_()
            return
        try:
            validate_url(route.request.url)
            route.continue_()
        except InputValidationError:
            route.abort()

    async def get_content(self, selector: str | None = None) -> str:
        """Retorna o conteúdo da página."""
        if not self._page:
            return "Navegador não iniciado"
        try:
            if selector:
                element = await self._page.query_selector(selector)
                if element:
                    return await element.inner_text()
                return f"Elemento '{selector}' não encontrado"
            return await self._page.inner_text("body")
        except Exception as e:
            return f"Erro ao obter conteúdo: {e}"

    async def get_html(self, selector: str | None = None) -> str:
        """Retorna o HTML da página."""
        if not self._page:
            return "Navegador não iniciado"
        try:
            if selector:
                element = await self._page.query_selector(selector)
                if element:
                    return await element.inner_html()
                return f"Elemento '{selector}' não encontrado"
            return await self._page.content()
        except Exception as e:
            return f"Erro ao obter HTML: {e}"

    async def click(self, selector: str) -> str:
        """Clica em um elemento."""
        if not self._page:
            return "Navegador não iniciado"
        try:
            await self._page.click(selector)
            return f"Clique em '{selector}'"
        except Exception as e:
            return f"Erro ao clicar: {e}"

    async def type_text(self, selector: str, text: str) -> str:
        """Digita texto em um campo."""
        if not self._page:
            return "Navegador não iniciado"
        try:
            await self._page.fill(selector, text)
            return f"Texto digitado em '{selector}'"
        except Exception as e:
            return f"Erro ao digitar: {e}"

    async def screenshot(self, filename: str | None = None) -> str:
        """Captura screenshot da página."""
        if not self._page:
            return "Navegador não iniciado"
        try:
            if not filename:
                filename = f"browser_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            filepath = self._data_dir / "screenshots" / filename if self._data_dir else Path(filename)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            await self._page.screenshot(path=str(filepath))
            return f"Screenshot salva: {filepath}"
        except Exception as e:
            return f"Erro ao capturar screenshot: {e}"

    async def search_google(self, query: str) -> str:
        """Pesquisa no Google."""
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        return await self.navigate(url)

    async def fill_form(self, fields: dict) -> str:
        """Preenche um formulário.

        Args:
            fields: Dict de {selector: valor}.
        """
        if not self._page:
            return "Navegador não iniciado"
        try:
            for selector, value in fields.items():
                await self._page.fill(selector, str(value))
            return f"Formulário preenchido ({len(fields)} campos)"
        except Exception as e:
            return f"Erro ao preencher formulário: {e}"

    async def evaluate(self, expression: str) -> str:
        """Executa JavaScript na página.

        NOTA DE SEGURANÇA: Este método é intencionalmente não exposto
        via handler (não registrado como action no CommandRegistry).
        Não deve ser chamado diretamente — use get_content() ou
        get_html() para extrair dados da página.
        """
        return "Execução de JS arbitrário desativada por segurança. Use get_content() para extrair dados."

    async def wait_for(self, selector: str, timeout: int = 10000) -> str:
        """Espera um elemento aparecer."""
        if not self._page:
            return "Navegador não iniciado"
        try:
            await self._page.wait_for_selector(selector, timeout=timeout)
            return f"Elemento '{selector}' encontrado"
        except Exception:
            return f"Timeout aguardando '{selector}'"

    async def get_links(self) -> list[str]:
        """Retorna todos os links da página."""
        if not self._page:
            return []
        try:
            links = await self._page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
            return links[:50]
        except Exception:
            return []

    async def get_screenshot_base64(self) -> str:
        """Retorna screenshot como base64."""
        if not self._page:
            return ""
        try:
            screenshot = await self._page.screenshot()
            import base64
            return base64.b64encode(screenshot).decode()
        except Exception:
            return ""

    def run_async(self, coro):
        """Executa uma coroutine async."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, coro).result()
            else:
                return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    # Métodos síncronos para conveniência
    def navigate_sync(self, url: str) -> str:
        return self.run_async(self.navigate(url))

    def get_content_sync(self, selector: str | None = None) -> str:
        return self.run_async(self.get_content(selector))

    def click_sync(self, selector: str) -> str:
        return self.run_async(self.click(selector))

    def search_sync(self, query: str) -> str:
        return self.run_async(self.search_google(query))

    def screenshot_sync(self, filename: str | None = None) -> str:
        return self.run_async(self.screenshot(filename))

    def format_status(self) -> str:
        """Formata status do navegador."""
        return (
            f"🌐 Browser Automation\n"
            f"   Playwright: {'Disponível' if _PLAYWRIGHT else 'Não instalado'}\n"
            f"   Navegador: {'Ativo' if self._browser else 'Inativo'}"
        )
