"""Discord Bot — adaptador DM para A.R.I.S.

Recebe mensagens privadas (DM) no Discord, roteia para o NeuralCore
(PC online) ou edge_chat (PC offline), e envia respostas de volta
para o mesmo PV.

Fluxo:
  Usuario → DM → discord_bot → CLL1 → A.R.I.S. → resposta
  A.R.I.S. → CLL1 → discord_bot → DM → usuario

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
    """Bot Discord que roteia DMs para A.R.I.S.

    O canal principal de conversa e o PV (DM) do bot.
    Nao ha dependencia de DISCORD_CHANNEL_ID para conversar.

    Args:
        token: Token do bot Discord.
        allowed_users: Lista de user IDs autorizados (None = todos).
        on_message: Callback para processar mensagem.
            Assinatura: (text: str, origin_info: dict) -> str | None
        logger: Logger opcional.
    """

    def __init__(
        self,
        token: str | None = None,
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
        self._allowed_users = allowed_users or self._env_int_list(
            "DISCORD_ALLOWED_USERS"
        )
        self._on_message = on_message
        self._logger = logger
        self._bot: commands.Bot | None = None
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: Any = None

        # Conversation history per Discord channel (DM)
        # Key: channel_id (str), Value: list of {"role": "user|assistant", "content": str}
        self._channel_history: dict[str, list[dict[str, str]]] = {}
        self._max_history_per_channel = 20

    @staticmethod
    def _env_int_list(key: str) -> list[int] | None:
        val = os.getenv(key, "")
        if not val:
            return None
        return [int(x.strip()) for x in val.split(",") if x.strip().isdigit()]

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def allowed_users(self) -> list[int] | None:
        return self._allowed_users

    def is_authorized(self, user_id: int) -> bool:
        """Verifica se um user ID esta autorizado (fail-closed)."""
        # Fail-closed: sem allowlist configurada, negar tudo.
        # Evita DM aberto caso DISCORD_ALLOWED_USERS esteja vazio.
        if self._allowed_users is None:
            if self._logger:
                self._logger.warning(
                    "DISCORD_ALLOWED_USERS vazio — negando DM (fail-closed)"
                )
            return False
        return user_id in self._allowed_users

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

            text = (message.content or "").strip()

            # ── Mensagem de servidor (espaços /soeu /soela /nos) ──
            if message.guild is not None and not isinstance(
                message.channel, discord.DMChannel
            ):
                await self._handle_guild_message(message, text)
                return

            if not isinstance(message.channel, discord.DMChannel):
                return

            if not self.is_authorized(message.author.id):
                if self._logger:
                    self._logger.warning(
                        f"DM nao autorizado de user_id={message.author.id}"
                    )
                return

            if not text:
                return

            # Handle /versao command directly (doesn't need routing)
            if text.lower().strip() in ("/versao", "/version"):
                from core.version import format_version_text
                response = format_version_text()
                await self._send_split(message.channel, response)
                return

            channel_key = f"dm:{message.channel.id}"

            # Get conversation history for this channel (copia: edge não pode mutar lista interna)
            history = list(self._channel_history.get(channel_key, []))

            origin_info = self._dm_origin(message, history)

            response = await self._route(text, origin_info)

            if response:
                self._remember(channel_key, text, response)
                await self._send_split(message.channel, response)

        try:
            self._loop.run_until_complete(
                bot.start(self._token)
            )
        except Exception as e:
            if self._logger:
                self._logger.error(f"Discord bot erro: {e}")
            self._running = False

    def _dm_origin(self, message: Any, history: list) -> dict:
        """origin_info de DM, com scope de memória (dono: shared+próprio)."""
        try:
            from modules.guild_spaces import allowed_scopes as _allowed
            allowed = _allowed("", str(message.author.id))
            scope = allowed[-1] if len(allowed) > 1 else "shared"
        except Exception:
            allowed, scope = ["shared"], "shared"
        return {
            "source": "discord",
            "channel": f"dm:{message.channel.id}",
            "user_id": str(message.author.id),
            "session_id": f"discord-{message.author.id}",
            "message_id": str(message.id),
            "timestamp": time.time(),
            "history": history,  # Pass history to callback
            "guild_category": None,
            "memory_scope": scope,
            "allowed_scopes": allowed,
        }

    async def _route(self, text: str, origin_info: dict) -> str | None:
        """Roteia pro pipeline síncrono sem travar o loop do bot."""
        if not self._on_message:
            return None
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, lambda: self._on_message(text, origin_info)
            )
        except Exception as e:
            if self._logger:
                self._logger.warning(f"Erro ao processar msg Discord: {e}")
            return "Erro ao processar sua mensagem."

    def _remember(self, channel_key: str, text: str, response: str) -> None:
        """Guarda user/assistant no histórico do canal (isolado por canal)."""
        if channel_key not in self._channel_history:
            self._channel_history[channel_key] = []
        self._channel_history[channel_key].append({"role": "user", "content": text})
        self._channel_history[channel_key].append(
            {"role": "assistant", "content": response}
        )
        if len(self._channel_history[channel_key]) > self._max_history_per_channel * 2:
            self._channel_history[channel_key] = self._channel_history[
                -self._max_history_per_channel * 2:
            ]

    async def _handle_guild_message(self, message: Any, text: str) -> None:
        """Mensagens nos espaços do servidor: comandos de estrutura + conversa."""
        from modules import guild_spaces as _gs

        author_id = message.author.id
        try:
            is_admin = bool(message.author.guild_permissions.administrator)
        except Exception:
            is_admin = False

        # Comandos de estrutura (só dono/admin) — criam via bot, não manual
        if text.strip().lower() in ("/soeu", "/soela", "/nos"):
            if not _gs.can_manage_spaces(author_id, is_admin):
                await message.channel.send("Só o dono pode criar espaços.")
                return
            space = text.strip().lower()[1:]
            try:
                summary = await self._build_space(message.guild, space)
                await message.channel.send(summary)
            except Exception as e:
                if self._logger:
                    self._logger.warning(f"falha ao criar espaço {space}: {e}")
                await message.channel.send(f"Não consegui criar /{space}: {e}")
            return

        # Comando de voz (só dono/admin): entrar no canal de voz do /nos
        if text.strip().lower() == "/voz":
            if not _gs.can_manage_spaces(author_id, is_admin):
                await message.channel.send("Só o dono pode chamar a voz.")
                return
            await message.channel.send(await self._join_voice(message.guild))
            return

        # Exclusão com trava (só dono/admin; confirmação explícita estilo CRITICAL)
        lowered = text.strip().lower()
        if lowered in _gs.DELETE_COMMANDS:
            if not _gs.can_manage_spaces(author_id, is_admin):
                await message.channel.send("Só o dono pode excluir espaços.")
                return
            target = _gs.DELETE_COMMANDS[lowered]
            await message.channel.send(_gs.start_delete(author_id, target))
            return
        target, reply = _gs.confirm_delete(author_id, text.strip())
        if target:
            try:
                summary = await self._delete_space(message.guild, target)
                await message.channel.send(summary)
            except Exception as e:
                if self._logger:
                    self._logger.warning(f"falha ao excluir {target}: {e}")
                await message.channel.send(f"Não consegui excluir: {e}")
            return
        if reply:
            await message.channel.send(reply)
            return

        if not text:
            return
        if not self.is_authorized(author_id):
            return

        channel = message.channel
        category = getattr(getattr(channel, "category", None), "name", None)
        decision = _gs.classify_guild_message(
            category, getattr(channel, "name", ""), author_id, is_admin
        )
        if not decision["route"]:
            return
        space = _gs.resolve_space(category if isinstance(category, str) else None)

        # Trava determinística anti-sondagem (sem LLM, sem evasiva)
        probe = _gs.cross_scope_probe_reply(text, space or "")
        if probe:
            await self._send_split(channel, probe)
            return

        channel_key = f"guild:{channel.id}"
        history = list(self._channel_history.get(channel_key, []))
        origin_info = {
            "source": "discord",
            "channel": channel_key,
            "user_id": str(author_id),
            "session_id": f"discord-guild-{author_id}-{channel.id}",
            "message_id": str(message.id),
            "timestamp": time.time(),
            "history": history,
            "guild_category": space,
            "guild_channel": getattr(channel, "name", ""),
            "memory_scope": decision["scope"],
            "allowed_scopes": decision["allowed"],
        }
        response = await self._route(text, origin_info)
        if response:
            self._remember(channel_key, text, response)
            await self._send_split(channel, response)

    async def _build_space(self, guild: Any, space: str) -> str:
        """Cria categoria + canais com overwrites. Retorna resumo."""
        from modules import guild_spaces as _gs

        owner = guild.get_member(int(_gs.get_owner_id())) if _gs.get_owner_id() else None
        partner_id = _gs.get_partner_id()
        partner = guild.get_member(int(partner_id)) if partner_id else None
        plan = _gs.plan_space(space)
        raw = _gs.build_overwrites(space, _gs.get_owner_id(), partner_id)

        def _overwrite_for(key: str) -> Any:
            target = {
                "everyone": guild.default_role,
                "owner": owner,
                "partner": partner,
                "bot": guild.me,
            }[key]
            if target is None:
                return None
            perms = raw[key]
            if perms.get("view") is None:
                return None
            return discord.PermissionOverwrite(
                view_channel=perms.get("view", None),
                send_messages=perms.get("view", None),
                connect=perms.get("view", None),
                speak=perms.get("view", None),
            )

        overwrites = {}
        for key in ("everyone", "owner", "partner", "bot"):
            ow = _overwrite_for(key)
            target = {
                "everyone": guild.default_role,
                "owner": owner,
                "partner": partner,
                "bot": guild.me,
            }[key]
            if ow is not None and target is not None:
                overwrites[target] = ow

        existing = discord.utils.get(guild.categories, name=plan["category"])
        category = existing or await guild.create_category(
            plan["category"], overwrites=overwrites
        )
        made = []
        for name in plan["text_channels"]:
            if discord.utils.get(category.text_channels, name=name) is None:
                await category.create_text_channel(name)
                made.append(f"#{name}")
        for name in plan["voice_channels"]:
            if discord.utils.get(category.voice_channels, name=name) is None:
                await category.create_voice_channel(name)
                made.append(f"🔊{name}")
        if not made:
            return f"/{space} já existe — nada a criar."
        return f"/{space} pronto: {', '.join(made)}."

    async def _delete_space(self, guild: Any, target: str) -> str:
        """Apaga categoria(s) + canais. Só chamado após confirmação explícita."""
        from modules import guild_spaces as _gs

        targets = (
            [_gs.CATEGORY_SOEu, _gs.CATEGORY_SOELA, _gs.CATEGORY_NOS]
            if target == "tudo" else [target]
        )
        gone = []
        for space in targets:
            names = {space, _gs.DISPLAY_CATEGORIES.get(space, "")}
            for cat in list(getattr(guild, "categories", [])):
                if (cat.name or "").strip().lower() in {n.lower() for n in names}:
                    for ch in list(cat.channels):
                        try:
                            await ch.delete()
                        except Exception:
                            pass
                    try:
                        await cat.delete()
                        gone.append(f"/{space}")
                    except Exception:
                        pass
        if not gone:
            return "Nada encontrado pra excluir."
        return f"Excluído: {', '.join(gone)}."

    async def _join_voice(self, guild: Any) -> str:
        """Entra no canal de voz do /nos. Fala se der; ouvir é pendente.

        Recepção de áudio exige discord-ext-voice-recv (não instalado) e
        falar exige opus+ffmpeg (ausentes aqui) — verificado em runtime,
        sem mockar conversa.
        """
        try:
            import discord as _d

            has_recv = False
            try:
                import discord.ext.voice_recv  # noqa: F401
                has_recv = True
            except ImportError:
                has_recv = False
            opus_ok = _d.opus.is_loaded()
            import shutil as _sh

            ffmpeg_ok = _sh.which("ffmpeg") is not None
            from modules import guild_spaces as _gs2
            channel = _d.utils.get(guild.voice_channels, name=_gs2.DISPLAY_VOICE)
            if channel is None:
                channel = _d.utils.get(guild.voice_channels, name="aris-voz")
            if channel is None:
                return "Crie o /nos primeiro — o canal de voz ainda não existe."
            if not has_recv:
                return (
                    f"Entrei (ou entraria) em 🔊{channel.name}, mas conversa por voz "
                    f"ainda não é viável: falta discord-ext-voice-recv pra ouvir "
                    f"(opus={'ok' if opus_ok else 'ausente'}, "
                    f"ffmpeg={'ok' if ffmpeg_ok else 'ausente'}). "
                    f"Item pendente separado — texto funciona normal."
                )
            return "Recepção de voz disponível — pendente ligar STT local ao stream."
        except Exception as e:
            return f"Voz indisponível agora: {e}"

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
