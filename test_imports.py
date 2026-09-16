#!/usr/bin/env python3
"""Testa importacao dos modulos."""

import sys
from pathlib import Path

# Adiciona o diretorio raiz ao path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

print("Testando imports...")
print()

# Testar utils
try:
    from utils.logger import Logger
    print("✓ utils.logger.Logger")
except Exception as e:
    print(f"✗ utils.logger.Logger: {e}")

try:
    from utils.terminal import Terminal
    print("✓ utils.terminal.Terminal")
except Exception as e:
    print(f"✗ utils.terminal.Terminal: {e}")

try:
    from utils.voice import Voice
    print("✓ utils.voice.Voice")
except Exception as e:
    print(f"✗ utils.voice.Voice: {e}")

# Testar edge
try:
    from edge.edge_config import EdgeConfig
    print("✓ edge.edge_config.EdgeConfig")
except Exception as e:
    print(f"✗ edge.edge_config.EdgeConfig: {e}")

try:
    from edge.edge_chat import EdgeChat
    print("✓ edge.edge_chat.EdgeChat")
except Exception as e:
    print(f"✗ edge.edge_chat.EdgeChat: {e}")

# Testar cll1
try:
    from cll1.router import Router
    print("✓ cll1.router.Router")
except Exception as e:
    print(f"✗ cll1.router.Router: {e}")

# Testar modules
try:
    from modules.discord_bot import DiscordBot
    print("✓ modules.discord_bot.DiscordBot")
except Exception as e:
    print(f"✗ modules.discord_bot.DiscordBot: {e}")

print()
print("Teste de importacao completo.")
