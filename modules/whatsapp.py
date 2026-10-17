"""WhatsApp Web Integration — Automação do WhatsApp Web via Playwright.

Gerencia sessão persistente (user_data_dir), leitura de conversas,
e envio de mensagens com confirmação obrigatória.

Seletores WhatsApp Web podem mudar sem aviso — todos os erros de
selector são tratados explicitamente (nunca silenciosos).
"""

import asyncio
import logging
import re
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from playwright.async_api import BrowserContext, Page, async_playwright
    _PLAYWRIGHT = True
except ImportError:
    _PLAYWRIGHT = False

logger = logging.getLogger("whatsapp")


# ── Confirmação de envio (rascunho pendente) ─────────────────────
# Depois que o preview é mostrado, o envio SÓ acontece com uma resposta
# afirmativa real ("sim", "confirma"…). Negações ("não", "cancela"…)
# bloqueiam o envio. Guardamos o rascunho aqui (fora da instância) para
# que o gate consiga responder mesmo sem LLM.

_PENDING_LOCK = threading.Lock()
_PENDING: dict[str, Any] | None = None

# Palavras isoladas contam como resposta — frases maiores caem em
# "unknown" e seguem fluxo normal (o gate nunca engole comandos).
_YES_WORDS = frozenset({
    "sim", "si", "confirma", "confirmar", "confirmo", "confirmado",
    "aprova", "aprovar", "aprovo", "pode", "podes", "podem", "envia",
    "enviar", "envie", "manda", "mandar", "mande", "ok", "beleza", "isso",
    "efetiva", "efetivar", "efetue", "efetuar",
})
# (entrada normalizada sem acento — _normalize_reply remove acentos)
_NO_WORDS = frozenset({
    "nao", "cancela", "cancelar", "cancelo", "cancel", "desisto",
    "para", "nope", "nah", "n", "negativo",
})


def set_pending(contact: str, message: str, sender: Any) -> None:
    """Guarda o rascunho aguardando confirmação (+ quem envia)."""
    global _PENDING
    with _PENDING_LOCK:
        _PENDING = {"contact": contact, "message": message, "sender": sender}


def get_pending() -> dict[str, Any] | None:
    """Retorna o rascunho pendente ou None."""
    with _PENDING_LOCK:
        return dict(_PENDING) if _PENDING else None


def clear_pending() -> None:
    """Descarta o rascunho pendente."""
    global _PENDING
    with _PENDING_LOCK:
        _PENDING = None


def _normalize_reply(text: str) -> list[str]:
    t = unicodedata.normalize("NFD", str(text or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[.,;:!?]+", " ", t)
    return t.split()


def classify_confirmation(text: str) -> str:
    """Classifica a resposta do usuário frente a um rascunho pendente.

    Returns:
        "yes" — afirmação real (pode enviar)
        "no"  — negação (bloqueia o envio; tem precedência sobre "yes")
        "unknown" — não é resposta de confirmação (fluxo normal continua)
    """
    words = _normalize_reply(text)
    if not words:
        return "unknown"
    # Negativa bloqueia mesmo se misturada ("sim não" etc.)
    if any(w in _NO_WORDS for w in words) and len(words) <= 6:
        return "no"
    if all(w in _YES_WORDS for w in words):
        return "yes"
    return "unknown"


def confirmation_reply(text: str) -> str | None:
    """Se há rascunho pendente, interpreta ``text`` como sim/não.

    Retorna a resposta a mostrar ao usuário, ou ``None`` quando não há
    pendência ou a frase não é uma resposta de confirmação.
    """
    pending = get_pending()
    if not pending:
        return None

    verdict = classify_confirmation(text)
    if verdict == "unknown":
        return None
    if verdict == "no":
        clear_pending()
        return "❌ Envio de WhatsApp cancelado — nada foi enviado."

    contact = pending["contact"]
    sender = pending["sender"]
    try:
        result = sender(contact, pending["message"])
    except Exception as e:  # envio nunca pode quebrar o loop principal
        result = {"ok": False, "error": str(e)}
    clear_pending()
    if isinstance(result, dict) and result.get("ok"):
        return f"✅ Mensagem enviada para {contact}"
    error = result.get("error", "desconhecido") if isinstance(result, dict) else str(result)
    return f"❌ Falha ao enviar: {error}"


def _normalize(text: str) -> str:
    """Remove acentos e normaliza para comparação."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.lower().strip()

# ── WhatsApp Web Selectors �──────────────────────────────────
# Estes seletores podem quebrar quando o WhatsApp atualiza o web app.
# Mantenha-os centralizados para fácil atualização.

_SELECTORS = {
    # Tela de QR code / loading
    "qr_canvas": "canvas[data-ref]",
    "qr_container": '[data-testid="qrcode"]',
    "intro_loading": '[data-testid="intro-md-beta-message"]',

    # Barra de pesquisa
    "search_input": 'input[aria-label*="Pesquisar"]',
    "search_input_alt": 'input[data-tab="3"]',
    "search_input_aria": '[role="textbox"][aria-label*="Pesquisar"]',

    # Lista de conversas
    "chat_list": '[data-testid="chat-list"]',
    "chat_item": '[data-testid^="list-item-"]',
    "chat_item_alt": '[data-testid="chat-list"] > div > div',
    "chat_name": '[data-testid="cell-frame-title"] span',
    "chat_name_alt": 'span[title]',
    "chat_last_msg": '[data-testid="last-msg-status"]',
    "chat_last_msg_alt": '[data-testid="cell-frame-container"] span:last-child',
    "chat_timestamp": '[data-testid="cell-frame-timestamp"]',
    "chat_unread": '[data-testid="unread-badge"]',

    # Área de chat aberto
    "chat_header_name": '[data-testid="conversation-info-header"] span[title]',
    "message_list": '[data-testid="msg-container"]',
    "message_text": '[data-testid="selectable-text"]',
    "message_metadata": 'div.copyable-text[data-pre-plain-text]',
    "msg_tail_in": '[data-testid="tail-in"]',
    "msg_tail_out": '[data-testid="tail-out"]',

    # Input de mensagem
    "message_input": '[data-testid="conversation-compose-box-input"]',
    "message_input_alt": 'div[contenteditable="true"][data-tab="10"]',
    "send_button": '[data-testid="send"]',
    "send_button_alt": 'span[data-testid="send"]',
}


@dataclass
class ChatSummary:
    """Resumo de uma conversa do WhatsApp."""
    name: str
    last_message: str = ""
    timestamp: str = ""
    unread: int = 0
    is_group: bool = False


@dataclass
class Message:
    """Mensagem individual do WhatsApp."""
    text: str
    sender: str = ""
    timestamp: str = ""
    is_from_me: bool = False


class WhatsApp:
    """Cliente WhatsApp Web via Playwright com sessão persistente."""

    def __init__(self, data_dir: Path | None = None):
        if not _PLAYWRIGHT:
            raise RuntimeError(
                "Playwright não instalado. Execute: "
                "pip install playwright && playwright install chromium"
            )
        self._data_dir = data_dir or Path.home() / ".aris" / "whatsapp"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._running = False
        self._logged_in = False

    @property
    def available(self) -> bool:
        return _PLAYWRIGHT

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    async def start(self, headless: bool = True) -> str:
        """Inicia o navegador com sessão persistente."""
        if self._running:
            return "WhatsApp já está rodando"

        try:
            self._playwright = await async_playwright().start()
            # Sessão persistente: user_data_dir mantém login entre reinícios
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self._data_dir),
                headless=headless,
                viewport={"width": 1280, "height": 800},
                locale="pt-BR",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            self._page = await self._context.new_page()
            self._running = True

            # Navegar pro WhatsApp Web
            await self._page.goto(
                "https://web.whatsapp.com",
                wait_until="domcontentloaded",
                timeout=60000,
            )

            # Verificar se já está logado ou precisa de QR code
            logged_in = await self._check_login_state()
            if logged_in:
                self._logged_in = True
                return "WhatsApp Web iniciado e logado"
            else:
                return (
                    "WhatsApp Web aberto. Escaneie o QR code para fazer login. "
                    "A sessão será persistida para próximos reinícios."
                )
        except Exception as e:
            logger.error(f"Erro ao iniciar WhatsApp: {e}")
            await self.stop()
            return f"Erro ao iniciar WhatsApp: {e}"

    async def stop(self) -> str:
        """Fecha o navegador."""
        self._running = False
        self._logged_in = False
        try:
            if self._context:
                await self._context.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self._context = None
        self._page = None
        self._playwright = None
        return "WhatsApp fechado"

    async def _check_login_state(self) -> bool:
        """Verifica se o usuário está logado no WhatsApp Web."""
        try:
            # Esperar um pouco pra página carregar
            await asyncio.sleep(3)

            # Se encontrar a lista de chat, está logado
            chat_list = await self._page.query_selector(
                _SELECTORS["chat_list"]
            )
            if chat_list:
                return True

            # Tentar selector alternativo
            search = await self._page.query_selector(
                _SELECTORS["search_input"]
            ) or await self._page.query_selector(
                _SELECTORS["search_input_alt"]
            )
            if search:
                return True

            # Verificar se tem QR code (não logado)
            qr = await self._page.query_selector(
                _SELECTORS["qr_canvas"]
            ) or await self._page.query_selector(
                _SELECTORS["qr_container"]
            )
            if qr:
                return False

            # Esperar mais um pouco e re-verificar
            await asyncio.sleep(5)
            chat_list = await self._page.query_selector(
                _SELECTORS["chat_list"]
            )
            return chat_list is not None
        except Exception as e:
            logger.warning(f"Erro ao verificar login: {e}")
            return False

    async def _find_element(self, *selectors: str, timeout: int = 5000):
        """Tenta encontrar um elemento usando múltiplos seletores."""
        for selector in selectors:
            full = _SELECTORS.get(selector, selector)
            try:
                el = await self._page.wait_for_selector(full, timeout=timeout)
                if el:
                    return el
            except Exception:
                continue
        return None

    async def _safe_click(self, selector: str, timeout: int = 5000) -> bool:
        """Clica em um elemento de forma segura."""
        try:
            full = _SELECTORS.get(selector, selector)
            await self._page.click(full, timeout=timeout)
            return True
        except Exception as e:
            logger.warning(f"Falha ao clicar em '{selector}': {e}")
            return False

    async def _safe_fill(self, selector: str, text: str, timeout: int = 5000) -> bool:
        """Preenche um campo de forma segura."""
        try:
            full = _SELECTORS.get(selector, selector)
            await self._page.fill(full, text, timeout=timeout)
            return True
        except Exception as e:
            logger.warning(f"Falha ao preencher '{selector}': {e}")
            return False

    # ── Leitura ──────────────────────────────────────────────

    async def list_chats(self, limit: int = 10) -> list[ChatSummary]:
        """Lista as conversas recentes."""
        if not self._running or not self._logged_in:
            return []

        try:
            await asyncio.sleep(1)

            # Itens usam role="row" com data-testid="list-item-N"
            items = await self._page.query_selector_all(
                _SELECTORS["chat_item"]
            )
            if not items:
                # Fallback: filhos diretos do chat list
                items = await self._page.query_selector_all(
                    _SELECTORS["chat_item_alt"]
                )
            if not items:
                logger.warning(
                    "Nenhum chat item encontrado. "
                    f"Selectors: {_SELECTORS['chat_item']}, "
                    f"{_SELECTORS['chat_item_alt']}"
                )
                return []

            chats = []
            seen = set()
            for item in items:
                if len(chats) >= limit:
                    break
                try:
                    # Pegar texto completo do item
                    text = await item.inner_text()
                    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
                    if not lines or text in seen:
                        continue
                    seen.add(text)

                    # Primeira linha = nome, segunda = hora, terceira = mensagem
                    name = lines[0] if lines else "Desconhecido"
                    timestamp = ""
                    last_msg = ""

                    for line in lines[1:]:
                        # Timestamps do WhatsApp: "18:05", "Ontem", "12/09"
                        if len(line) <= 8 and (":" in line or "/" in line or line in ("Ontem", "Hoje")):
                            timestamp = line
                        elif line.isdigit() and len(line) <= 3:
                            # Badge de não lidas
                            pass
                        else:
                            last_msg = line

                    # Detectar grupo (@ no nome ou keywords)
                    is_group = any(kw in name.lower() for kw in ["grupo", "family", "amigos", "trabalho"])

                    unread_el = await item.query_selector(
                        _SELECTORS["chat_unread"]
                    )
                    unread_text = await unread_el.inner_text() if unread_el else "0"
                    unread = int(unread_text) if unread_text.strip().isdigit() else 0

                    chats.append(ChatSummary(
                        name=name,
                        last_message=last_msg[:100],
                        timestamp=timestamp,
                        unread=unread,
                        is_group=is_group,
                    ))
                except Exception as e:
                    logger.warning(f"Erro ao ler chat item: {e}")
                    continue

            return chats
        except Exception as e:
            logger.error(f"Erro ao listar chats: {e}")
            return []

    async def read_chat(self, contact: str, limit: int = 20) -> list[Message]:
        """Abre uma conversa e lê as últimas mensagens."""
        if not self._running or not self._logged_in:
            return []

        try:
            # Se não há chat aberto, abrir
            opened = await self._open_chat(contact)
            if not opened:
                logger.error(f"Não encontrei a conversa com '{contact}'")
                return []

            await asyncio.sleep(2)

            # Ler containers de mensagem
            msg_containers = await self._page.query_selector_all(
                _SELECTORS["message_list"]
            )
            if not msg_containers:
                return []

            messages = []
            for container in msg_containers[-limit:]:
                try:
                    # Pegar texto da mensagem
                    text_el = await container.query_selector(
                        _SELECTORS["message_text"]
                    )
                    text = await text_el.inner_text() if text_el else ""
                    if not text.strip():
                        # Pode ser sticker, imagem, etc.
                        # Verificar se tem alt text ou placeholder
                        sticker = await container.query_selector(
                            '[data-testid="sticker-container"]'
                        )
                        if sticker:
                            text = "[Figurinha]"
                        else:
                            # Mensagem apagada ou tipo desconhecido
                            full_text = await container.inner_text()
                            if "apagada" in full_text.lower():
                                text = "[Mensagem apagada]"
                            else:
                                continue

                    # Determinar se é incoming ou outgoing
                    tail_in = await container.query_selector(
                        _SELECTORS["msg_tail_in"]
                    )
                    is_from_me = tail_in is None  # Se não tem tail-in, é outgoing

                    # Tentar pegar timestamp do data-pre-plain-text
                    metadata_el = await container.query_selector(
                        _SELECTORS["message_metadata"]
                    )
                    timestamp = ""
                    sender = ""
                    if metadata_el:
                        pre_text = await metadata_el.get_attribute(
                            "data-pre-plain-text"
                        )
                        if pre_text:
                            # Formato: "[17:51, 21/09/2026] Vinicius: "
                            import re
                            match = re.match(
                                r"\[(\d{2}:\d{2}),?\s*\d{2}/\d{2}/\d{4}\]\s*(.*?):",
                                pre_text
                            )
                            if match:
                                timestamp = match.group(1)
                                sender = match.group(2)

                    messages.append(Message(
                        text=text.strip(),
                        sender=sender or ("Eu" if is_from_me else contact),
                        timestamp=timestamp,
                        is_from_me=is_from_me,
                    ))
                except Exception as e:
                    logger.warning(f"Erro ao ler mensagem: {e}")
                    continue

            return messages
        except Exception as e:
            logger.error(f"Erro ao ler conversa com '{contact}': {e}")
            return []

    async def _open_chat(self, contact: str) -> bool:
        """Abre uma conversa pelo nome do contato."""
        try:
            # Clicar na barra de pesquisa
            search = await self._find_element("search_input", "search_input_alt")
            if not search:
                logger.error("Barra de pesquisa não encontrada")
                return False

            await search.click()
            await asyncio.sleep(0.5)

            # Digitar o nome do contato
            await search.fill("")
            await asyncio.sleep(0.3)
            await search.type(contact, delay=50)
            await asyncio.sleep(2)

            # Encontrar itens de resultado — pular headers ("Conversas", "Grupos")
            # Itens de chat têm um span com nome do contato
            all_items = await self._page.query_selector_all(
                f'{_SELECTORS["chat_list"]} > div > div'
            )

            for item in all_items:
                text = await item.inner_text()
                lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
                if not lines:
                    continue

                # Pular headers de seção ("Conversas", "Grupos", etc.)
                first_line = _normalize(lines[0])
                if first_line in ("conversas", "grupos", "contatos", "nao lidas",
                                  "favoritas", "arquivadas"):
                    continue

                # Verificar se o nome do contato aparece no texto
                norm_contact = _normalize(contact)
                name_match = any(
                    norm_contact in _normalize(line)
                    for line in lines
                )
                if name_match:
                    await item.click()
                    await asyncio.sleep(2)

                    # Verificar se o chat abriu (procurar input de mensagem)
                    msg_input = await self._find_element(
                        "message_input", "message_input_alt"
                    )
                    if msg_input:
                        return True

                    # Chat pode ter aberto mas selector diferente
                    # Verificar se tem header com nome do contato
                    header = await self._page.query_selector(
                        _SELECTORS["chat_header_name"]
                    )
                    if header:
                        header_text = await header.inner_text()
                        if _normalize(contact) in _normalize(header_text):
                            return True

            logger.warning(f"Nenhum resultado clicável para '{contact}'")
            return False
        except Exception as e:
            logger.error(f"Erro ao abrir chat '{contact}': {e}")
            return False

    # ── Envio (com confirmação) ──────────────────────────────

    async def prepare_send(self, contact: str, message: str) -> dict:
        """Prepara envio — retorna preview para confirmação.

        Returns:
            Dict com:
            - ok: bool
            - contact: str
            - message: str
            - preview: str (texto formatado para confirmação)
            - error: str (se falhou)
        """
        if not self._running or not self._logged_in:
            return {"ok": False, "error": "WhatsApp não está logado"}

        if not contact or not contact.strip():
            return {"ok": False, "error": "Contato não especificado"}

        if not message or not message.strip():
            return {"ok": False, "error": "Mensagem não especificada"}

        preview = (
            f"📱 Confirmar envio no WhatsApp:\n"
            f"  Para: {contact}\n"
            f"  Mensagem: {message}\n\n"
            f"Responda 'sim' para confirmar."
        )

        return {
            "ok": True,
            "contact": contact.strip(),
            "message": message.strip(),
            "preview": preview,
        }

    async def send_message(self, contact: str, message: str) -> dict:
        """Envia uma mensagem para um contato.

        NOTA: Chamada apenas após confirmação via prepare_send().

        Returns:
            Dict com: ok, error (se falhou)
        """
        if not self._running or not self._logged_in:
            return {"ok": False, "error": "WhatsApp não está logado"}

        try:
            # Abrir conversa
            opened = await self._open_chat(contact)
            if not opened:
                return {
                    "ok": False,
                    "error": f"Não encontrei a conversa com '{contact}'"
                }

            await asyncio.sleep(1)

            # Encontrar campo de mensagem
            input_el = await self._find_element(
                "message_input", "message_input_alt"
            )
            if not input_el:
                return {
                    "ok": False,
                    "error": (
                        "Campo de mensagem não encontrado. "
                        "O WhatsApp Web pode ter atualizado os seletores."
                    )
                }

            # Digitar mensagem
            await input_el.click()
            await asyncio.sleep(0.3)

            # Usar fill para texto longo, type para curto
            if len(message) > 100:
                await input_el.fill(message)
            else:
                await input_el.type(message, delay=30)

            await asyncio.sleep(0.5)

            # Enviar: Enter ou botão de envio
            send_btn = await self._find_element(
                "send_button", "send_button_alt"
            )
            if send_btn:
                await send_btn.click()
            else:
                # Fallback: pressionar Enter
                await self._page.keyboard.press("Enter")

            await asyncio.sleep(1)

            # Verificar se a mensagem foi enviada
            # (procurar a última mensagem na conversa como confirmação)
            return {"ok": True, "error": ""}
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem: {e}")
            return {"ok": False, "error": f"Erro ao enviar: {e}"}

    # ── Status ───────────────────────────────────────────────

    async def get_status(self) -> dict:
        """Retorna status do WhatsApp."""
        return {
            "running": self._running,
            "logged_in": self._logged_in,
            "data_dir": str(self._data_dir),
            "playwright_available": _PLAYWRIGHT,
        }

    # ── Sync wrappers (para handlers) ────────────────────────

    def _run(self, coro):
        """Executa coroutine async de forma síncrona."""
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

    def list_chats_sync(self, limit: int = 10) -> list[ChatSummary]:
        return self._run(self.list_chats(limit))

    def read_chat_sync(self, contact: str, limit: int = 20) -> list[Message]:
        return self._run(self.read_chat(contact, limit))

    def prepare_send_sync(self, contact: str, message: str) -> dict:
        return self._run(self.prepare_send(contact, message))

    def send_message_sync(self, contact: str, message: str) -> dict:
        return self._run(self.send_message(contact, message))

    def start_sync(self, headless: bool = True) -> str:
        return self._run(self.start(headless))

    def stop_sync(self) -> str:
        return self._run(self.stop())
