"""Discord Bot — adaptador de canal para A.R.I.S.

Recebe mensagens do Discord, roteia para o NeuralCore (PC online)
ou edge_chat (PC offline), e envia respostas de volta.

Nao usa prefixo `!` — mensagem inteira vai pro pipeline.
Nao interpreta nada por keyword — e so adaptador de canal.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

try:
    import discord
    from discord.ext import commands

    HAS_DISCORD = True
except ImportError:
    HAS_DISCORD = False

from utils.logger import Logger

if TYPE_CHECKING:
    pass

DISCORD_MAX_MESSAGE_LENGTH = 2000


class DiscordBot:
    """Bot Discord que roteia mensagens para A.R.I.S.

    Args:
        token: Token do bot Discord.
        channel_id: ID do canal autorizado (None = todos os DMs).
        allowed_users: Lista de user IDs autorizados (None = todos).
        on_message: Callback para processar mensagem.
            Assinatura: (text: str, origin_info: dict) -> str | None
        logger: Logger opcional.
    """

    def __init__(
        self,
        token: str | None = None,
        channel_id: int | None = None,
        allowed_users: list[int] | None = None,
        on_message: Callable[[str, dict], str | None] | None = None,
        logger: Logger | None = None,
    ) -> None:
        if not HAS_DISCORD:
            raise ImportError(
                "discord.py nao esta instalado. "
                "Execute: pip install discord.py"
            )

        self._token = token or os.getenv("DISCORD_BOT_TOKEN", "")
        self._channel_id = channel_id or self._env_int("DISCORD_CHANNEL_ID")
        self._allowed_users = allowed_users or self._env_int_list(
            "DISCORD_ALLOWED_USERS"
        )
        self._on_message = on_message
        self._logger = logger
        self._bot: commands.Bot | None = None
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: Any = None

    @staticmethod
    def _env_int(key: str) -> int | None:
        val = os.getenv(key, "")
        return int(val) if val.isdigit() else None

    @staticmethod
    def _env_int_list(key: str) -> list[int] | None:
        val = os.getenv(key, "")
        if not val:
            return None
        return [int(x.strip()) for x in val.split(",") if x.strip().isdigit()]

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Inicia o bot em daemon thread."""
        if self._running:
            return

        if not self._token:
            if self._logger:
                self._logger.warning(
                    "DISCORD_BOT_TOKEN nao configurado — bot desativado"
                )
            return

        import threading

        self._thread = threading.Thread(
            target=self._run_loop,
            name="discord-bot",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Para o bot."""
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _run_loop(self) -> None:
        """Executa o event loop do Discord em thread separada."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True

        self._bot = commands.Bot(command_prefix=[], intents=intents)

        bot = self._bot

        @bot.event
        async def on_ready():
            self._running = True
            if self._logger:
                self._logger.info(
                    f"Discord bot conectado: {bot.user} "
                    f"(guilds: {len(bot.guilds)})"
                )

        @bot.event
        async def on_message(message: discord.Message):
            if message.author.bot:
                return

            if self._channel_id and message.channel.id != self._channel_id:
                return

            if self._allowed_users and message.author.id not in self._allowed_users:
                await message.channel.send(
                    "Voce nao esta autorizado a interagir comigo."
                )
                return

            text = message.content.strip()
            if not text:
                return

            origin_info = {
                "source": "discord",
                "channel": f"discord:{message.channel.id}",
                "user_id": str(message.author.id),
                "session_id": f"discord-{message.author.id}",
                "message_id": str(message.id),
                "timestamp": time.time(),
            }

            response = None
            if self._on_message:
                try:
                    loop = asyncio.get_event_loop()
                    response = await loop.run_in_executor(
                        None, lambda: self._on_message(text, origin_info)
                    )
                except Exception as e:
                    if self._logger:
                        self._logger.warning(
                            f"Erro ao processar msg Discord: {e}"
                        )
                    response = "Erro ao processar sua mensagem."

            if response:
                await self._send_split(message.channel, response)

        try:
            self._loop.run_until_complete(
                bot.start(self._token)
            )
        except Exception as e:
            if self._logger:
                self._logger.error(f"Discord bot erro: {e}")
            self._running = False

    async def _send_split(
        self, channel: Any, text: str
    ) -> None:
        """Divide e envia mensagens longas preservando ordem."""
        if len(text) <= DISCORD_MAX_MESSAGE_LENGTH:
            await channel.send(text)
            return

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

        for i, chunk in enumerate(chunks):
            try:
                await channel.send(chunk)
            except Exception as e:
                if self._logger:
                    self._logger.warning(
                        f"Erro enviando chunk {i+1}/{len(chunks)}: {e}"
                    )
                break
