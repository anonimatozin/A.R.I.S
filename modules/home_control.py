"""Home control — comando de casa em qualquer canal, sem mockar execução.

Reconhece "acende/apaga/liga/desliga a luz da sala" etc. e resolve
dispositivo+cômodo+ação. Como a integração de interruptores (hardware)
ainda está pendente de detalhe, SEM hardware configurado (HOME_API_URL
ausente) a resposta diz isso explicitamente — nunca finge que executou.
"""

from __future__ import annotations

import os
import re

_ACTIONS = {
    "acende": "on", "acender": "on", "liga": "on", "ligar": "on",
    "apaga": "off", "apagar": "off", "desliga": "off", "desligar": "off",
}
_DEVICES = {
    "luz": "luz", "luzes": "luz", "lâmpada": "luz", "lampada": "luz",
    "ar": "ar-condicionado", "ar-condicionado": "ar-condicionado",
    "arcondicionado": "ar-condicionado", "tv": "tv", "televisão": "tv",
    "televisao": "tv", "ventilador": "ventilador",
}
_ROOMS = ("sala", "quarto", "cozinha", "banheiro", "escritório", "escritorio",
          "varanda", "quintal", "garagem", "corredor", "casa")


def _word(tl: str, key: str) -> bool:
    return re.search(rf"\b{re.escape(key)}\b", tl) is not None


def parse(text: str) -> dict | None:
    """Extrai {action, device, room} ou None se não for comando de casa."""
    tl = (text or "").lower().strip()
    action = next((a for k, a in _ACTIONS.items() if _word(tl, k)), None)
    device = next((d for k, d in _DEVICES.items() if _word(tl, k)), None)
    if not action or not device:
        return None
    room = next((r for r in _ROOMS if _word(tl, r)), "casa")
    return {"action": action, "device": device, "room": room}


def handle(text: str) -> str | None:
    """Roteador de texto. None = não é comando de casa."""
    cmd = parse(text)
    if not cmd:
        return None
    if not (os.getenv("HOME_API_URL", "") or "").strip():
        verb = "acender" if cmd["action"] == "on" else "apagar"
        return (f"Entendi: {verb} {cmd['device']} ({cmd['room']}). "
                f"A integração dos interruptores ainda está pendente de "
                f"detalhe de hardware (sem HOME_API_URL configurada), "
                f"então não executei nada — me fala qual módulo vai usar "
                f"que eu ligo o comando de verdade.")
    # Com hardware configurado, o envio real entra aqui (nunca simulado).
    return (f"Hardware configurado, mas o driver de envio ainda não foi "
            f"implementado pra {cmd['device']} — comando registrado, "
            f"nada executado.")
